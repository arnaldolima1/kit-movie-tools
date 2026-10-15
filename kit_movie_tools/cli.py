"""The command line: list, extract, upscale, download."""
import argparse
import sys
from pathlib import Path

from . import tools
from .extract import extract_movie, list_movies
from .iso import Iso
from .upscale import install_movie, upscale_movie


def command_list(args):
    with Iso(args.iso) as iso:
        movies = list_movies(iso)
        for m in movies:
            print(f'{m.path:48} {m.width or "?"}x{m.height or "?"}  {m.seconds:7.1f} s  '
                  f'{m.audio_tracks} audio  {m.size / 1048576:6.1f} MiB')
        print(f'{len(movies)} movies')


def command_extract(args):
    settings = tools.load_settings()
    ffmpeg = None if args.no_mp4 else tools.find_ffmpeg(settings)[0]
    if not args.no_mp4 and ffmpeg is None:
        print('note: no ffmpeg found; writing .264 files only (python kit_movies.py download ffmpeg)')
    wanted = {n.upper().removesuffix('.PMF') for n in args.only} if args.only else None
    done = 0
    with Iso(args.iso) as iso:
        for movie in list_movies(iso):
            if wanted is not None and movie.name.upper() not in wanted:
                continue
            meta = extract_movie(iso, movie, args.out, ffmpeg)
            rate = meta['frame_rate']
            print(f"{movie.name}: {meta['width']}x{meta['height']}, {meta['frames']} frames"
                  + (f", {rate['fps']} fps" if rate else '') + (', mp4 written' if ffmpeg else ''))
            done += 1
    print(f'{done} movies extracted to {args.out}')


def command_upscale(args):
    settings = tools.load_settings()
    if args.tool:
        settings['realesrgan'] = str(Path(args.tool) / tools._exe('realesrgan-ncnn-vulkan')
                                     if Path(args.tool).is_dir() else args.tool)
    ffmpeg, ffprobe = tools.find_ffmpeg(settings)
    realesrgan = tools.find_realesrgan(settings)
    if ffmpeg is None:
        raise SystemExit('no ffmpeg found: python kit_movies.py download ffmpeg (or install it)')
    if realesrgan is None:
        raise SystemExit('no realesrgan-ncnn-vulkan found: python kit_movies.py download realesrgan, or --tool')

    def show(p):
        print(f'\r  {p.frames_done}/{p.frames} frames, {p.fps:.2f} frames/s, '
              f'about {p.seconds_left / 60:.0f} min left   ', end='', flush=True)

    result = upscale_movie(args.movie, args.out, ffmpeg, ffprobe, realesrgan, args.model, args.height, args.crf,
                           args.block, args.work, args.keep_parts, progress=show)
    print(f"\n{args.out}: {result['frames']} frames, {result['width']}x{result['height']}, "
          f"in {result['minutes']:.1f} min")


def command_install(args):
    settings = tools.load_settings()
    ffmpeg = tools.find_ffmpeg(settings)[0]
    if ffmpeg is None:
        raise SystemExit('no ffmpeg found: python kit_movies.py download ffmpeg (or install it)')
    for movie in args.movies:
        print(f'{install_movie(ffmpeg, movie, args.mods)}')


def command_download(args):
    settings = tools.load_settings()

    def show(done, total):
        print(f'\r  {done / 1048576:.0f}' + (f'/{total / 1048576:.0f}' if total else '') + ' MiB', end='', flush=True)

    folder = tools.download(args.what, settings, show)
    tools.save_settings(settings)
    print(f'\n{args.what} ready in {folder}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='List, extract and upscale the movies of a PSP game from your '
                                                 'own disc image.')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('list', help='list the movies on a disc image')
    p.add_argument('iso')
    p.set_defaults(run=command_list)
    p = commands.add_parser('extract', help="extract movies' video")
    p.add_argument('iso')
    p.add_argument('out')
    p.add_argument('--only', nargs='+', metavar='NAME', help='only these movies (e.g. R6_INTRO)')
    p.add_argument('--no-mp4', action='store_true', help='do not write .mp4 files even with ffmpeg')
    p.set_defaults(run=command_extract)
    p = commands.add_parser('upscale', help='make a sharper, larger copy of an extracted movie')
    p.add_argument('movie', help='an .mp4 that extract wrote')
    p.add_argument('out', help='the .mp4 to write')
    p.add_argument('--tool', help='realesrgan-ncnn-vulkan, or its folder (default: downloaded or on the PATH)')
    p.add_argument('--model', default='realesrgan-x4plus',
                   help='realesrgan-x4plus (default, best for rendered video), realesr-animevideov3-x4 (fast)')
    p.add_argument('--height', type=int, default=1088, help='output height (default 1088: 1920x1088)')
    p.add_argument('--crf', type=int, default=14, help='x264 quality, lower is better (default 14)')
    p.add_argument('--block', type=int, default=300, help='frames per block (default 300)')
    p.add_argument('--work', help='where blocks go while it runs (default: OUT.parts beside OUT)')
    p.add_argument('--keep-parts', action='store_true', help='keep the blocks after joining them')
    p.set_defaults(run=command_upscale)
    p = commands.add_parser('install', help="put upscaled movies in a port's movie mod folder, as NAME.264")
    p.add_argument('mods', help='the mod folder, e.g. %%APPDATA%%/Sparta/UCES01401/mods/movies for Sparta')
    p.add_argument('movies', nargs='+', help='upscaled .mp4 files')
    p.set_defaults(run=command_install)
    p = commands.add_parser('download', help='download ffmpeg or Real-ESRGAN into the tools folder')
    p.add_argument('what', choices=('ffmpeg', 'realesrgan'))
    p.set_defaults(run=command_download)
    p = commands.add_parser('gui', help='open the window')
    p.set_defaults(run=lambda _: __import__('kit_movie_tools.gui', fromlist=['main']).main())
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except (ValueError, RuntimeError) as error:
        raise SystemExit(f'error: {error}')
    except KeyboardInterrupt:
        raise SystemExit('stopped')


if __name__ == '__main__':
    sys.exit(main())
