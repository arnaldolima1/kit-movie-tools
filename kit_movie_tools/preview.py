"""One frame before and after, to choose a model: the same piece of the
picture, at the size the upscaled movie would have, stretched from the
original and upscaled."""
import subprocess
import tempfile
from pathlib import Path

from .tools import no_window
from .upscale import model_arguments, output_size, probe, run


def preview(movie, frame, ffmpeg, ffprobe, realesrgan, model, out_height, crop_width, crop_height,
            centre=(0.5, 0.5), cancel=None):
    """Returns (original, upscaled, crop_width, crop_height): two RGBA byte
    strings of the same crop, centred at `centre` (fractions of the picture)."""
    rate, frames, width, height = probe(ffprobe, movie)
    frame = max(0, min(frame, frames - 1))
    out_width, out_height = output_size(width, height, out_height)
    crop_width, crop_height = min(crop_width, out_width), min(crop_height, out_height)
    x = int(max(0, min(out_width - crop_width, centre[0] * out_width - crop_width / 2)))
    y = int(max(0, min(out_height - crop_height, centre[1] * out_height - crop_height / 2)))
    crop = f'crop={crop_width}:{crop_height}:{x}:{y}'
    name, scale = model_arguments(model)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        source = temp / 'frame.png'
        bigger = temp / 'frame_up.png'
        run([ffmpeg, '-v', 'error', '-i', movie, '-vf', f'select=eq(n\\,{frame})', '-fps_mode', 'passthrough',
             '-frames:v', '1', source], cancel)
        run([realesrgan, '-i', source, '-o', bigger, '-n', name, '-s', scale, '-f', 'png',
             '-m', Path(realesrgan).parent / 'models'], cancel)
        original = _rgba(ffmpeg, source, f'scale={out_width}:{out_height}:flags=bicubic,{crop}')
        upscaled = _rgba(ffmpeg, bigger, f'scale={out_width}:{out_height}:flags=lanczos,{crop}')
    return original, upscaled, crop_width, crop_height


def _rgba(ffmpeg, image, filters):
    result = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(image), '-vf', filters, '-f', 'rawvideo',
                             '-pix_fmt', 'rgba', '-'], capture_output=True, **no_window())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip()[-500:])
    return result.stdout
