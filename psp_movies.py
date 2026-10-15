#!/usr/bin/env python3
"""Lists and extracts the movies of a PSP game from your own disc image.

    python psp_movies.py list    GAME.iso
    python psp_movies.py extract GAME.iso OUT_DIR [--only NAME ...] [--no-mp4]
    python psp_movies.py upscale MOVIE.mp4 OUT.mp4 --tool PATH [--model NAME] [--height 1088]

A PSP movie is a PSMF file (.pmf): a 2 KiB header, then an MPEG program
stream holding one H.264 video stream (0xE0) and ATRAC3plus audio (private
stream 1, 0xBD). `extract` writes, for each movie:

    NAME.264    the video stream exactly as it is on the disc (H.264 Annex B)
    NAME.json   what putting a replacement back needs: size, frame rate,
                frame count, start and end time
    NAME.mp4    the same video in an MP4 file, without re-encoding, when
                ffmpeg is on the PATH (--no-mp4 skips it)

`extract` decodes and re-encodes nothing, and nothing is sent anywhere.
Only the standard library is used; ffmpeg is optional for `extract`.

`upscale` makes a sharper, larger copy of an extracted movie with
Real-ESRGAN (realesrgan-ncnn-vulkan, which runs on any Vulkan GPU) and
ffmpeg, keeping its frame rate and frame count, so the result can replace the
original picture frame for frame. It works in blocks of frames, so the disk
holds only one block of images at a time, and it picks up where it stopped
if it is run again.
"""
import argparse
import json
import os
import tempfile
import time
import shutil
import struct
import subprocess
import sys
from pathlib import Path

SECTOR = 2048
PSMF_MAGIC = b'PSMF'
CLOCK = 90000  # MPEG timestamps tick at 90 kHz


# ---------------------------------------------------------------------------
# ISO 9660: just enough to walk the directories of a disc image.

class Iso:
    def __init__(self, path):
        self.file = open(path, 'rb')
        pvd = self.read(16 * SECTOR, SECTOR)
        if pvd[1:6] != b'CD001':
            raise SystemExit(f'{path}: not an ISO 9660 disc image')
        self.root = self._record(pvd[156:190])

    def read(self, offset, size):
        self.file.seek(offset)
        return self.file.read(size)

    @staticmethod
    def _record(data):
        lba = struct.unpack_from('<I', data, 2)[0]
        size = struct.unpack_from('<I', data, 10)[0]
        name = data[33:33 + data[32]]
        return {'lba': lba, 'size': size, 'dir': bool(data[25] & 2), 'name': name}

    def entries(self, directory):
        data = self.read(directory['lba'] * SECTOR, (directory['size'] + SECTOR - 1) // SECTOR * SECTOR)
        at = 0
        while at < len(data):
            length = data[at]
            if length == 0:  # records do not cross sectors: the rest is padding
                at = (at // SECTOR + 1) * SECTOR
                continue
            entry = self._record(data[at:at + length])
            at += length
            if entry['name'] in (b'\x00', b'\x01'):
                continue
            entry['name'] = entry['name'].decode('ascii', 'replace').split(';')[0]
            yield entry

    def walk(self, directory=None, path=''):
        for entry in self.entries(directory or self.root):
            full = f"{path}/{entry['name']}"
            if entry['dir']:
                yield from self.walk(entry, full)
            else:
                yield full, entry


# ---------------------------------------------------------------------------
# PSMF.

def psmf_header(iso, entry):
    """What the header says: where the stream starts, how long it is, and its
    first and last presentation times."""
    head = iso.read(entry['lba'] * SECTOR, 0x800)
    if head[:4] != PSMF_MAGIC:
        return None
    info = {
        'version': head[4:8].decode('ascii', 'replace'),
        'stream_offset': struct.unpack_from('>I', head, 0x08)[0],
        'stream_size': struct.unpack_from('>I', head, 0x0C)[0],
        # 48-bit presentation times of the first and the last picture.
        'start_pts': int.from_bytes(head[0x54:0x5A], 'big'),
        'end_pts': int.from_bytes(head[0x5A:0x60], 'big'),
    }
    # The stream table: a count at 0x80, then 16-byte entries; a video entry
    # keeps its width and height in units of 16 pixels at +12 and +13.
    count = struct.unpack_from('>H', head, 0x80)[0]
    streams = []
    for i in range(min(count, 16)):
        e = head[0x82 + i * 16:0x82 + (i + 1) * 16]
        stream = {'id': e[0], 'channel': e[1]}
        if 0xE0 <= e[0] <= 0xEF:
            stream.update(kind='video', width=e[12] * 16, height=e[13] * 16)
        elif e[0] == 0xBD:
            stream['kind'] = 'audio'
        streams.append(stream)
    info['streams'] = streams
    return info


def pes_payloads(data, stream_id):
    """The payload of every PES packet of `stream_id` in an MPEG program
    stream, in order, with its PTS (or None)."""
    at = 0
    end = len(data)
    while at + 4 <= end:
        if data[at:at + 3] != b'\x00\x00\x01':
            # Lost sync (padding at the end): look for the next start code.
            next_start = data.find(b'\x00\x00\x01', at + 1)
            if next_start < 0:
                return
            at = next_start
            continue
        code = data[at + 3]
        if code == 0xBA:  # pack header: MPEG-2, stuffing in the low 3 bits of byte 13
            at += 14 + (data[at + 13] & 7)
            continue
        if code == 0xB9:  # end code
            return
        length = struct.unpack_from('>H', data, at + 4)[0]
        packet = data[at + 6:at + 6 + length]
        at += 6 + length
        if code != stream_id:
            continue
        # MPEG-2 PES header: two flag bytes, then the header data length.
        flags = packet[1]
        header_length = packet[2]
        pts = None
        if flags & 0x80:
            p = packet[3:8]
            pts = (((p[0] >> 1) & 7) << 30) | (p[1] << 22) | ((p[2] >> 1) << 15) | (p[3] << 7) | (p[4] >> 1)
        yield pts, packet[3 + header_length:]


def access_units(stream):
    """How many H.264 pictures an Annex B stream holds: NAL units of type 1
    or 5 that start a picture (first_mb_in_slice 0, an exp-Golomb '1')."""
    count = 0
    at = stream.find(b'\x00\x00\x01')
    while at >= 0:
        nal = stream[at + 3] if at + 3 < len(stream) else 0
        if (nal & 0x1F) in (1, 5) and at + 4 < len(stream) and stream[at + 4] & 0x80:
            count += 1
        at = stream.find(b'\x00\x00\x01', at + 3)
    return count


def frame_rate(info, pts_values, frames):
    """Frames per second: the frame count over the duration the header gives
    (from the first picture's start to the last one's end), else over the
    spread of the video's timestamps."""
    rate = None
    if frames > 0 and info['end_pts'] > info['start_pts']:
        rate = frames * CLOCK / (info['end_pts'] - info['start_pts'])
    else:
        pts = sorted(p for p in pts_values if p is not None)
        if len(pts) >= 2 and frames >= 2 and pts[-1] > pts[0]:
            rate = (frames - 1) * CLOCK / (pts[-1] - pts[0])
    # The PSP's movie rates: snap to the nearest standard one.
    for standard, exact in ((29.97, 30000 / 1001), (30.0, 30.0), (25.0, 25.0), (23.976, 24000 / 1001),
                            (59.94, 60000 / 1001)):
        if rate is not None and abs(rate - exact) < 0.3:
            return {'fps': standard, 'num': round(exact * 1001) if exact % 1 else int(exact),
                    'den': 1001 if exact % 1 else 1}
    return {'fps': round(rate, 3), 'num': round(rate * 1000), 'den': 1000} if rate else None


# ---------------------------------------------------------------------------
# Commands.

def movies(iso):
    for path, entry in iso.walk():
        if entry['size'] < 0x800:
            continue
        info = psmf_header(iso, entry)
        if info is not None:
            yield path, entry, info


def command_list(args):
    iso = Iso(args.iso)
    found = 0
    for path, entry, info in movies(iso):
        video = next((s for s in info['streams'] if s.get('kind') == 'video'), {})
        audio = sum(1 for s in info['streams'] if s.get('kind') == 'audio')
        seconds = (info['end_pts'] - info['start_pts']) / CLOCK
        print(f"{path:48} {video.get('width', '?')}x{video.get('height', '?')}  {seconds:7.1f} s  "
              f"{audio} audio  {entry['size'] / 1048576:6.1f} MiB")
        found += 1
    print(f'{found} movies')


def command_extract(args):
    iso = Iso(args.iso)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = {n.upper().removesuffix('.PMF') for n in args.only} if args.only else None
    ffmpeg = None if args.no_mp4 else shutil.which('ffmpeg')
    if not args.no_mp4 and ffmpeg is None:
        print('note: no ffmpeg on the PATH; writing .264 files only (install ffmpeg for .mp4)')
    done = 0
    for path, entry, info in movies(iso):
        name = Path(path).stem
        if wanted is not None and name.upper() not in wanted:
            continue
        data = iso.read(entry['lba'] * SECTOR + info['stream_offset'],
                        min(info['stream_size'], entry['size'] - info['stream_offset']))
        video = next((s for s in info['streams'] if s.get('kind') == 'video'), {'id': 0xE0})
        pts_values, chunks = [], []
        for pts, payload in pes_payloads(data, video['id']):
            pts_values.append(pts)
            chunks.append(payload)
        stream = b''.join(chunks)
        if not stream:
            print(f'{path}: no video stream found')
            continue
        frames = access_units(stream)
        rate = frame_rate(info, pts_values, frames)
        (out / f'{name}.264').write_bytes(stream)
        meta = {
            'source': path,
            'width': video.get('width'),
            'height': video.get('height'),
            'frames': frames,
            'frame_rate': rate,
            'start_pts': info['start_pts'],
            'end_pts': info['end_pts'],
            'duration_seconds': round((info['end_pts'] - info['start_pts']) / CLOCK, 3),
            'audio_streams': sum(1 for s in info['streams'] if s.get('kind') == 'audio'),
        }
        (out / f'{name}.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
        line = f"{name}: {meta['width']}x{meta['height']}, {frames} frames"
        if rate:
            line += f", {rate['fps']} fps"
        if ffmpeg is not None:
            fps = f"{rate['num']}/{rate['den']}" if rate else '30000/1001'
            result = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-r', fps, '-f', 'h264',
                                     '-i', str(out / f'{name}.264'), '-c', 'copy', str(out / f'{name}.mp4')],
                                    capture_output=True, text=True)
            line += ', mp4 written' if result.returncode == 0 else f', mp4 failed: {result.stderr.strip()}'
        print(line)
        done += 1
    print(f'{done} movies extracted to {out}')


def run(command):
    result = subprocess.run([str(c) for c in command], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f'{Path(str(command[0])).name} failed:\n{result.stderr.strip()[-2000:]}')
    return result.stdout


def probe(ffprobe, movie):
    """Frame rate (as a fraction) and frame count of a movie's video."""
    out = run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_packets',
               '-show_entries', 'stream=r_frame_rate,nb_read_packets,width,height', '-of', 'json', movie])
    stream = json.loads(out)['streams'][0]
    return stream['r_frame_rate'], int(stream['nb_read_packets']), int(stream['width']), int(stream['height'])


def command_upscale(args):
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if ffmpeg is None or ffprobe is None:
        raise SystemExit('upscale needs ffmpeg and ffprobe on the PATH')
    tool = Path(args.tool)
    if tool.is_dir():
        tool = tool / ('realesrgan-ncnn-vulkan.exe' if os.name == 'nt' else 'realesrgan-ncnn-vulkan')
    if not tool.is_file():
        raise SystemExit(f'{tool}: no realesrgan-ncnn-vulkan there (--tool takes the program or its folder)')
    models = Path(args.models) if args.models else tool.parent / 'models'
    movie = Path(args.movie)
    out = Path(args.out)
    rate, frames, width, height = probe(ffprobe, movie)
    # The PSP's picture shape, at the height asked for (a multiple of 16).
    out_height = args.height
    out_width = round(out_height * width / height / 2) * 2
    work = Path(args.work) if args.work else out.with_name(out.stem + '.parts')
    work.mkdir(parents=True, exist_ok=True)
    block = args.block
    blocks = (frames + block - 1) // block
    print(f'{movie.name}: {frames} frames at {rate} fps, {width}x{height} -> {out_width}x{out_height} '
          f'with {args.model}, {blocks} blocks of {block}')
    started = time.time()
    done_frames = 0
    for index in range(blocks):
        part = work / f'part_{index:04d}.mp4'
        first = index * block
        count = min(block, frames - first)
        if part.exists():
            continue  # made by an earlier run
        with tempfile.TemporaryDirectory(dir=work) as temp:
            source = Path(temp) / 'in'
            bigger = Path(temp) / 'out'
            source.mkdir()
            bigger.mkdir()
            # Frames `first`..`first + count - 1`, chosen by number, not time,
            # so no frame is lost or doubled at a block's edge.
            run([ffmpeg, '-v', 'error', '-i', movie, '-vf', f'select=between(n\\,{first}\\,{first + count - 1})',
                 '-fps_mode', 'passthrough', '-frames:v', count, source / '%06d.png'])
            run([tool, '-i', source, '-o', bigger, '-n', args.model, '-s', args.scale, '-f', 'png', '-m', models])
            run([ffmpeg, '-v', 'error', '-y', '-framerate', rate, '-i', bigger / '%06d.png',
                 '-vf', f'scale={out_width}:{out_height}:flags=lanczos', '-c:v', 'libx264', '-crf', args.crf,
                 '-preset', 'slow', '-pix_fmt', 'yuv420p', part.with_suffix('.tmp.mp4')])
            part.with_suffix('.tmp.mp4').replace(part)
        done_frames += count
        elapsed = time.time() - started
        left = (frames - first - count) * elapsed / done_frames
        print(f'  block {index + 1}/{blocks}: {first + count}/{frames} frames, '
              f'{done_frames / elapsed:.2f} frames/s, about {left / 60:.0f} min left', flush=True)
    listing = work / 'parts.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in sorted(work.glob('part_*.mp4'))
                               if not p.name.endswith('.tmp.mp4')), encoding='utf-8')
    run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', out])
    _, made, _, _ = probe(ffprobe, out)
    if made != frames:
        raise SystemExit(f'{out}: {made} frames, but {movie.name} has {frames}; keeping {work} to look at')
    if not args.keep_parts:
        shutil.rmtree(work)
    print(f'{out}: {made} frames, {out_width}x{out_height}, in {(time.time() - started) / 60:.1f} min')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list', help='list the movies on a disc image')
    listing.add_argument('iso')
    listing.set_defaults(run=command_list)
    extract = commands.add_parser('extract', help="extract movies' video")
    extract.add_argument('iso')
    extract.add_argument('out')
    extract.add_argument('--only', nargs='+', metavar='NAME', help='only these movies (e.g. R6_INTRO)')
    extract.add_argument('--no-mp4', action='store_true', help='do not write .mp4 files even with ffmpeg')
    extract.set_defaults(run=command_extract)
    upscale = commands.add_parser('upscale', help='make a sharper, larger copy of an extracted movie')
    upscale.add_argument('movie', help='an .mp4 that extract wrote')
    upscale.add_argument('out', help='the .mp4 to write')
    upscale.add_argument('--tool', required=True, help='realesrgan-ncnn-vulkan, or the folder it is in')
    upscale.add_argument('--models', help='its models folder (default: models beside it)')
    upscale.add_argument('--model', default='realesrgan-x4plus',
                         help='realesrgan-x4plus (default: best for rendered video), realesr-animevideov3, '
                              'realesrgan-x4plus-anime')
    upscale.add_argument('--scale', type=int, default=4, help="the model's scale (default 4)")
    upscale.add_argument('--height', type=int, default=1088,
                         help='output height; the width keeps the picture shape (default 1088, 1920 wide)')
    upscale.add_argument('--crf', type=int, default=14, help='x264 quality, lower is better (default 14)')
    upscale.add_argument('--block', type=int, default=300, help='frames per block (default 300)')
    upscale.add_argument('--work', help='where blocks go while it runs (default: OUT.parts beside OUT)')
    upscale.add_argument('--keep-parts', action='store_true', help='keep the blocks after joining them')
    upscale.set_defaults(run=command_upscale)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    sys.exit(main())
