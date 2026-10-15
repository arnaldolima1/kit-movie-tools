"""Still frames of movies for the lists: from an extracted .mp4, or straight
from the disc image's bytes, kept in a cache so they show at once next time."""
import hashlib
import subprocess
from pathlib import Path

from .tools import data_dir, no_window

THUMB_SIZE = (128, 72)


def cache_dir():
    return data_dir() / 'thumbs'


def _cache_file(key, frame, size):
    digest = hashlib.sha1(f'{key}|{frame}|{size[0]}x{size[1]}'.encode('utf-8')).hexdigest()[:20]
    return cache_dir() / f'{digest}.rgba'


def cached(key, frame, size):
    """The cached picture for `key`, or None."""
    file = _cache_file(key, frame, size)
    if file.is_file() and file.stat().st_size == size[0] * size[1] * 4:
        return file.read_bytes()
    return None


def frame_rgba(ffmpeg, frame, size, path=None, data=None, key=None):
    """RGBA bytes of picture number `frame`, scaled to `size` (the picture
    shape kept, letterboxed in black), from an .mp4 at `path` or from raw
    H.264 `data`. Cached under `key` (default: the path and its time)."""
    width, height = size
    if key is None and path is not None:
        stat = Path(path).stat()
        key = f'{path}|{stat.st_size}|{stat.st_mtime_ns}'
    cached = _cache_file(key, frame, size) if key else None
    if cached is not None and cached.is_file() and cached.stat().st_size == width * height * 4:
        return cached.read_bytes()
    source = ['-i', str(path)] if path is not None else ['-f', 'h264', '-i', '-']
    filters = (f'select=gte(n\\,{frame}),scale={width}:{height}:force_original_aspect_ratio=decrease:flags=bicubic,'
               f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black')
    result = subprocess.run([str(ffmpeg), '-v', 'error', *source, '-vf', filters, '-frames:v', '1', '-f', 'rawvideo',
                             '-pix_fmt', 'rgba', '-'], input=data, capture_output=True, **no_window())
    pixels = result.stdout
    if result.returncode != 0 or len(pixels) != width * height * 4:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip()[-300:] or 'no picture')
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(pixels)
    return pixels


def as_floats(rgba):
    """The float list a Dear PyGui texture takes."""
    return [b / 255.0 for b in rgba]
