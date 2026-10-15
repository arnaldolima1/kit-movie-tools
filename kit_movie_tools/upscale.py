"""Sharper, larger copies of extracted movies: Real-ESRGAN on every frame,
then x264 at the movie's own frame rate and frame count."""
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .tools import Cancelled, no_window

# The models Real-ESRGAN's release has, best first for rendered video.
MODELS = {
    'realesrgan-x4plus': 4,
    'realesr-animevideov3-x4': 4,
    'realesrgan-x4plus-anime': 4,
    'realesr-animevideov3-x2': 2,
    'realesr-animevideov3-x3': 3,
}


def model_scale(model):
    return MODELS.get(model, 4)


def model_arguments(model):
    """realesrgan-ncnn-vulkan's -n and -s for a model file name: the
    animevideov3 files are named with their scale, the program wants the
    base name and the scale apart."""
    if model.startswith('realesr-animevideov3-x'):
        return 'realesr-animevideov3', int(model.rsplit('x', 1)[1])
    return model, model_scale(model)


@dataclass
class Progress:
    movie: str
    frames_done: int
    frames: int
    fps: float          # frames upscaled a second, so far
    seconds_left: float


def run(command, cancel=None):
    """Runs a program, killing it if `cancel` is set; raises RuntimeError
    with its error output if it fails."""
    process = subprocess.Popen([str(c) for c in command], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               text=True, **no_window())
    try:
        while True:
            try:
                _, err = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    process.kill()
                    process.wait()
                    raise Cancelled()
    finally:
        if process.poll() is None:
            process.kill()
    if process.returncode != 0:
        raise RuntimeError(f'{Path(str(command[0])).name} failed: {(err or "").strip()[-1500:]}')


def probe(ffprobe, movie):
    """Frame rate (as a fraction string), frame count, width and height."""
    out = subprocess.run([str(ffprobe), '-v', 'error', '-select_streams', 'v:0', '-count_packets',
                          '-show_entries', 'stream=r_frame_rate,nb_read_packets,width,height', '-of', 'json',
                          str(movie)], capture_output=True, text=True, **no_window())
    if out.returncode != 0:
        raise RuntimeError(f'{Path(movie).name}: ffprobe cannot read it: {out.stderr.strip()[-500:]}')
    stream = json.loads(out.stdout)['streams'][0]
    return stream['r_frame_rate'], int(stream['nb_read_packets']), int(stream['width']), int(stream['height'])


def output_size(width, height, out_height):
    """The size an upscaled movie gets: `out_height` tall, the picture shape
    kept, both even."""
    return round(out_height * width / height / 2) * 2, out_height // 2 * 2


def upscale_movie(movie, out, ffmpeg, ffprobe, realesrgan, model='realesrgan-x4plus', out_height=1088, crf=14,
                  block=300, work=None, keep_parts=False, progress=None, cancel=None):
    """Writes `out`, an upscaled copy of `movie`. Works in blocks of `block`
    frames under `work` (default OUT.parts beside OUT): a block is extracted,
    upscaled, encoded and its images deleted before the next, and a block
    already encoded by an earlier, stopped run is kept. `progress(Progress)`
    after every few frames; `cancel` an Event."""
    movie, out = Path(movie), Path(out)
    rate, frames, width, height = probe(ffprobe, movie)
    out_width, out_height = output_size(width, height, out_height)
    work = Path(work) if work else out.with_name(out.stem + '.parts')
    work.mkdir(parents=True, exist_ok=True)
    name, scale = model_arguments(model)
    models = Path(realesrgan).parent / 'models'
    blocks = (frames + block - 1) // block
    started = time.time()
    made_now = 0  # frames upscaled by this run, for the speed

    def report(done_total):
        if progress is None:
            return
        elapsed = max(time.time() - started, 1e-6)
        speed = made_now / elapsed if made_now else 0.0
        left = (frames - done_total) / speed if speed else 0.0
        progress(Progress(movie.stem, done_total, frames, speed, left))

    for index in range(blocks):
        part = work / f'part_{index:04d}.mp4'
        first = index * block
        count = min(block, frames - first)
        if part.exists():
            report(first + count)
            continue
        with tempfile.TemporaryDirectory(dir=work) as temp:
            source, bigger = Path(temp) / 'in', Path(temp) / 'out'
            source.mkdir()
            bigger.mkdir()
            # Frames chosen by number, not time, so none is lost or doubled
            # at a block's edge.
            run([ffmpeg, '-v', 'error', '-i', movie, '-vf', f'select=between(n\\,{first}\\,{first + count - 1})',
                 '-fps_mode', 'passthrough', '-frames:v', count, source / '%06d.png'], cancel)
            # Its progress goes to a file: a pipe nobody reads fills up and
            # stops the program.
            log_path = Path(temp) / 'realesrgan.log'
            with open(log_path, 'w', encoding='utf-8', errors='replace') as log:
                process = subprocess.Popen([str(c) for c in (realesrgan, '-i', source, '-o', bigger, '-n', name,
                                                             '-s', scale, '-f', 'png', '-m', models)],
                                           stdout=subprocess.DEVNULL, stderr=log, **no_window())
                try:
                    seen = 0
                    while process.poll() is None:
                        if cancel is not None and cancel.is_set():
                            process.kill()
                            process.wait()
                            raise Cancelled()
                        time.sleep(0.5)
                        now = sum(1 for _ in bigger.iterdir())
                        if now != seen:
                            made_now += now - seen
                            seen = now
                            report(first + now)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            if process.returncode != 0:
                err = log_path.read_text(encoding='utf-8', errors='replace')
                raise RuntimeError(f'realesrgan-ncnn-vulkan failed: {err.strip()[-1500:]}')
            made_now += count - seen
            temporary = part.with_name(part.stem + '.tmp.mp4')
            run([ffmpeg, '-v', 'error', '-y', '-framerate', rate, '-i', bigger / '%06d.png',
                 '-vf', f'scale={out_width}:{out_height}:flags=lanczos', '-c:v', 'libx264', '-crf', crf,
                 '-preset', 'slow', '-pix_fmt', 'yuv420p', temporary], cancel)
            temporary.replace(part)
        report(first + count)
    listing = work / 'parts.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in sorted(work.glob('part_*.mp4'))
                               if not p.name.endswith('.tmp.mp4')), encoding='utf-8')
    out.parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', out], cancel)
    _, made, _, _ = probe(ffprobe, out)
    if made != frames:
        raise RuntimeError(f'{out.name}: {made} frames, but {movie.name} has {frames}; the blocks are kept in {work}')
    if not keep_parts:
        shutil.rmtree(work, ignore_errors=True)
    return {'frames': made, 'width': out_width, 'height': out_height, 'minutes': (time.time() - started) / 60}
