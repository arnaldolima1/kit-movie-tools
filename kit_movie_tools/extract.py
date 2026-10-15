"""Finding a disc's movies and copying their video out."""
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import psmf
from .iso import SECTOR, Iso
from .tools import no_window


@dataclass
class Movie:
    path: str          # on the disc, e.g. /PSP_GAME/USRDIR/MOVIES/R6_INTRO.PMF
    lba: int
    size: int
    info: dict         # psmf.header()

    @property
    def name(self):
        return Path(self.path).stem

    @property
    def seconds(self):
        return psmf.duration(self.info)

    @property
    def width(self):
        return psmf.video_stream(self.info).get('width')

    @property
    def height(self):
        return psmf.video_stream(self.info).get('height')

    @property
    def audio_tracks(self):
        return sum(1 for s in self.info['streams'] if s.get('kind') == 'audio')


def list_movies(iso):
    """Every PSMF file on the disc, in disc order."""
    found = []
    for path, entry in iso.walk():
        if entry['size'] < 0x800:
            continue
        info = psmf.header(iso.read(entry['lba'] * SECTOR, 0x800))
        if info is not None:
            found.append(Movie(path, entry['lba'], entry['size'], info))
    return found


def video_bytes(iso, movie):
    """A movie's H.264 stream (Annex B) as it is on the disc, and the PTS of
    its PES packets. Raises RuntimeError if it has no video."""
    info = movie.info
    data = iso.read(movie.lba * SECTOR + info['stream_offset'],
                    min(info['stream_size'], movie.size - info['stream_offset']))
    video = psmf.video_stream(info)
    pts_values, chunks = [], []
    for pts, payload in psmf.pes_payloads(data, video['id']):
        pts_values.append(pts)
        chunks.append(payload)
    stream = b''.join(chunks)
    if not stream:
        raise RuntimeError(f'{movie.path}: no video stream found')
    return stream, pts_values


def extract_movie(iso, movie, out_dir, ffmpeg=None):
    """Writes NAME.264, NAME.json and (with ffmpeg) NAME.mp4 into `out_dir`.
    Returns the metadata written to NAME.json; raises RuntimeError if the
    movie holds no video or ffmpeg fails."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = movie.info
    stream, pts_values = video_bytes(iso, movie)
    frames = psmf.picture_count(stream)
    rate = psmf.frame_rate(info, pts_values, frames)
    name = movie.name
    (out_dir / f'{name}.264').write_bytes(stream)
    meta = {
        'source': movie.path,
        'game': Path(iso.path).name,
        'width': movie.width,
        'height': movie.height,
        'frames': frames,
        'frame_rate': rate,
        'start_pts': info['start_pts'],
        'end_pts': info['end_pts'],
        'duration_seconds': round(movie.seconds, 3),
        'audio_streams': movie.audio_tracks,
    }
    (out_dir / f'{name}.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
    if ffmpeg is not None:
        fps = f"{rate['num']}/{rate['den']}" if rate else '30000/1001'
        result = subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-r', fps, '-f', 'h264',
                                 '-i', str(out_dir / f'{name}.264'), '-c', 'copy', str(out_dir / f'{name}.mp4')],
                                capture_output=True, text=True, **no_window())
        if result.returncode != 0:
            raise RuntimeError(f'ffmpeg could not write {name}.mp4: {result.stderr.strip()[-500:]}')
    return meta
