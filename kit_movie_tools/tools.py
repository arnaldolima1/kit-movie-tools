"""The programs the tool runs (ffmpeg, Real-ESRGAN), where they are, and
downloading them; and the settings the app keeps."""
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

APP_NAME = 'kit-movie-tools'


def no_window():
    """On Windows, child processes of a GUI open no console window."""
    return {'creationflags': 0x08000000} if os.name == 'nt' else {}


def data_dir():
    """Where settings and downloaded tools live, per user."""
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / APP_NAME


# ---------------------------------------------------------------------------
# Settings.

DEFAULTS = {
    'iso': '',
    'output': str(Path.home() / 'Kit Movies'),
    'tools': '',            # '' = data_dir() / 'tools'
    'ffmpeg': '',           # '' = found automatically
    'realesrgan': '',       # '' = found automatically
    'model': 'realesrgan-x4plus',
    'height': 1088,
    'crf': 14,
    'language': '',         # '' = the system's
}


def load_settings():
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads((data_dir() / 'settings.json').read_text(encoding='utf-8')))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')


def tools_dir(settings):
    return Path(settings['tools']) if settings.get('tools') else data_dir() / 'tools'


# ---------------------------------------------------------------------------
# Finding the programs.

def _exe(name):
    return name + '.exe' if os.name == 'nt' else name


def find_ffmpeg(settings):
    """(ffmpeg, ffprobe) paths, or (None, None)."""
    candidates = []
    if settings.get('ffmpeg'):
        candidates.append(Path(settings['ffmpeg']).parent)
    candidates += sorted(tools_dir(settings).glob('ffmpeg*/bin'))
    for folder in candidates:
        ffmpeg, ffprobe = folder / _exe('ffmpeg'), folder / _exe('ffprobe')
        if ffmpeg.is_file() and ffprobe.is_file():
            return ffmpeg, ffprobe
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        return Path(ffmpeg), Path(ffprobe)
    return None, None


def find_realesrgan(settings):
    """The realesrgan-ncnn-vulkan program, or None. Its models are in the
    models folder beside it."""
    candidates = []
    if settings.get('realesrgan'):
        candidates.append(Path(settings['realesrgan']))
    candidates += sorted(tools_dir(settings).glob(f"realesrgan*/{_exe('realesrgan-ncnn-vulkan')}"))
    for program in candidates:
        if program.is_file() and (program.parent / 'models').is_dir():
            return program
    found = shutil.which('realesrgan-ncnn-vulkan')
    return Path(found) if found and (Path(found).parent / 'models').is_dir() else None


def models_of(program):
    """The model names a Real-ESRGAN install has (its .param files)."""
    if program is None:
        return []
    return sorted(p.stem for p in (Path(program).parent / 'models').glob('*.param'))


def ffmpeg_has_x264(ffmpeg):
    try:
        out = subprocess.run([str(ffmpeg), '-hide_banner', '-encoders'], capture_output=True, text=True,
                             timeout=20, **no_window()).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return 'libx264' in out


# ---------------------------------------------------------------------------
# Downloads: pinned releases, checked against their SHA-256.

REALESRGAN = {
    'windows': ('https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/'
                'realesrgan-ncnn-vulkan-20220424-windows.zip',
                'abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d'),
    'linux': ('https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/'
              'realesrgan-ncnn-vulkan-20220424-ubuntu.zip',
              'e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96'),
    'macos': ('https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/'
              'realesrgan-ncnn-vulkan-20220424-macos.zip',
              'e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a'),
}

# A GPL build: the libx264 encoder the upscaled movies are written with is GPL.
FFMPEG = {
    'windows': ('https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-06-30-13-34/'
                'ffmpeg-n7.1.5-1-g7d0e842004-win64-gpl-7.1.zip',
                '405b190f746db40539eb453967f72c0e69d8bf260b10ceff36e0c2149a9ad22f'),
}


def system():
    if os.name == 'nt':
        return 'windows'
    return 'macos' if sys.platform == 'darwin' else 'linux'


def can_download(kind):
    table = REALESRGAN if kind == 'realesrgan' else FFMPEG
    return system() in table and (system() != 'windows' or platform.machine().lower() in ('amd64', 'x86_64'))


class Cancelled(Exception):
    pass


def download(kind, settings, progress=None, cancel=None):
    """Downloads and unpacks `kind` ('realesrgan' or 'ffmpeg') into the tools
    folder, checking its SHA-256. `progress(done_bytes, total_bytes)`;
    `cancel` an Event. Returns the folder it unpacked into."""
    table = REALESRGAN if kind == 'realesrgan' else FFMPEG
    if system() not in table:
        raise RuntimeError(f'no {kind} download for this system; install it yourself and pick it in the settings')
    url, sha256 = table[system()]
    folder = tools_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / Path(url).name
    partial = archive.with_suffix('.part')
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={'User-Agent': APP_NAME})
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, 'wb') as out:
        total = int(response.headers.get('Content-Length') or 0)
        done = 0
        while True:
            if cancel is not None and cancel.is_set():
                out.close()
                partial.unlink(missing_ok=True)
                raise Cancelled()
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if digest.hexdigest() != sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f'{archive.name}: the download does not match its checksum; try again')
    partial.replace(archive)
    target = folder / ('realesrgan' if kind == 'realesrgan' else archive.stem)
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(archive) as z:
        z.extractall(target if kind == 'realesrgan' else folder)
    archive.unlink()
    if kind == 'realesrgan' and system() != 'windows':
        program = target / 'realesrgan-ncnn-vulkan'
        program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if system() == 'macos':
            subprocess.run(['xattr', '-dr', 'com.apple.quarantine', str(target)], capture_output=True)
    if kind == 'ffmpeg':
        settings['ffmpeg'] = ''
    else:
        settings['realesrgan'] = ''
    return target


def open_file(path):
    """Opens a file in the program the system has for it (a video player)."""
    if os.name == 'nt':
        os.startfile(str(path))  # noqa: S606 - the user's own file
    elif sys.platform == 'darwin':
        subprocess.run(['open', str(path)])
    else:
        subprocess.run(['xdg-open', str(path)])


def open_folder(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        os.startfile(str(path))  # noqa: S606 - the user's own folder
    elif sys.platform == 'darwin':
        subprocess.run(['open', str(path)])
    else:
        subprocess.run(['xdg-open', str(path)])
