"""PSMF, the PSP's movie format: a 2 KiB header, then an MPEG program stream
with one H.264 video stream (0xE0) and ATRAC3plus audio (private stream 1,
0xBD)."""
import struct

CLOCK = 90000  # MPEG timestamps tick at 90 kHz
MAGIC = b'PSMF'


def header(data):
    """What the header says, or None when `data` is not a PSMF header."""
    if data[:4] != MAGIC or len(data) < 0x100:
        return None
    info = {
        'version': data[4:8].decode('ascii', 'replace'),
        'stream_offset': struct.unpack_from('>I', data, 0x08)[0],
        'stream_size': struct.unpack_from('>I', data, 0x0C)[0],
        # 48-bit presentation times of the first and the last picture.
        'start_pts': int.from_bytes(data[0x54:0x5A], 'big'),
        'end_pts': int.from_bytes(data[0x5A:0x60], 'big'),
    }
    # The stream table: a count at 0x80, then 16-byte entries; a video entry
    # keeps its width and height in units of 16 pixels at +12 and +13.
    count = struct.unpack_from('>H', data, 0x80)[0]
    streams = []
    for i in range(min(count, 16)):
        e = data[0x82 + i * 16:0x82 + (i + 1) * 16]
        if len(e) < 16:
            break
        stream = {'id': e[0], 'channel': e[1]}
        if 0xE0 <= e[0] <= 0xEF:
            stream.update(kind='video', width=e[12] * 16, height=e[13] * 16)
        elif e[0] == 0xBD:
            stream['kind'] = 'audio'
        streams.append(stream)
    info['streams'] = streams
    return info


def video_stream(info):
    return next((s for s in info['streams'] if s.get('kind') == 'video'), {'id': 0xE0})


def duration(info):
    return max(0, info['end_pts'] - info['start_pts']) / CLOCK


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
        if code != stream_id or len(packet) < 3:
            continue
        # MPEG-2 PES header: two flag bytes, then the header data length.
        flags = packet[1]
        header_length = packet[2]
        pts = None
        if flags & 0x80 and len(packet) >= 8:
            p = packet[3:8]
            pts = (((p[0] >> 1) & 7) << 30) | (p[1] << 22) | ((p[2] >> 1) << 15) | (p[3] << 7) | (p[4] >> 1)
        yield pts, packet[3 + header_length:]


def picture_count(stream):
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


# The PSP's movie rates, as fractions; a measured rate snaps to the nearest.
STANDARD_RATES = ((30000, 1001), (30, 1), (25, 1), (24000, 1001), (60000, 1001))


def frame_rate(info, pts_values, frames):
    """Frames per second: the frame count over the duration the header gives
    (from the first picture's start to the last one's end), else over the
    spread of the video's timestamps. A {'fps', 'num', 'den'} dict, or None."""
    rate = None
    if frames > 0 and info['end_pts'] > info['start_pts']:
        rate = frames * CLOCK / (info['end_pts'] - info['start_pts'])
    else:
        pts = sorted(p for p in pts_values if p is not None)
        if len(pts) >= 2 and frames >= 2 and pts[-1] > pts[0]:
            rate = (frames - 1) * CLOCK / (pts[-1] - pts[0])
    if rate is None:
        return None
    for num, den in STANDARD_RATES:
        if abs(rate - num / den) < 0.3:
            return {'fps': round(num / den, 3), 'num': num, 'den': den}
    return {'fps': round(rate, 3), 'num': round(rate * 1000), 'den': 1000}
