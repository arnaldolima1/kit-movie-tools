# psp-movie-tools

**English** · [Português (Brasil)](README.pt-BR.md)

Lists and extracts the cutscene movies of a PSP game from **your own** disc image, so you can watch them, or upscale them and put them back in a port that supports replacement movies. It works with any game that keeps its movies as PSMF files (`.pmf`), which is most of them.

> [!IMPORTANT]
> This repository contains no game data. The tool only reads a disc image you provide and writes the movies to a folder you choose. Keep what you extract to yourself.

## Use

Python 3.9 or newer, nothing else. [ffmpeg](https://ffmpeg.org/) on the PATH is optional: with it, every movie is also written as an `.mp4` (the same video, not re-encoded), which is what most video and AI upscaling tools open.

```bash
python psp_movies.py list    "My Game.iso"
python psp_movies.py extract "My Game.iso" movies/                    # every movie
python psp_movies.py extract "My Game.iso" movies/ --only R6_INTRO    # just one
```

For each movie, `extract` writes:

| File | What it is |
| --- | --- |
| `NAME.264` | the video stream exactly as it is on the disc (H.264) |
| `NAME.mp4` | the same video in an MP4 file, when ffmpeg is installed |
| `NAME.json` | size, frame rate, frame count and timing: what putting a replacement back needs |

Audio (ATRAC3plus, often one track per language) stays on the disc: a replacement movie only replaces the picture, and the game keeps playing its own sound in sync.

## Upscaling a movie

`upscale` does it with [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)'s `realesrgan-ncnn-vulkan` (download its release for your system; it runs on any GPU with Vulkan, AMD included) and ffmpeg:

```bash
python psp_movies.py upscale movies/R6_INTRO.mp4 upscaled/R6_INTRO.mp4 --tool path/to/realesrgan-ncnn-vulkan
```

It keeps the frame rate and the frame count, writes 1920x1088 by default (`--height`), and works in blocks of 300 frames, so the disk holds one block of images at a time; run it again after a stop and it goes on from the last finished block. Models: `realesrgan-x4plus` (the default, best for rendered video; about 1 frame a second on a Radeon RX 7600) or `realesr-animevideov3` (about 10 times faster, smoother and less detailed).

Or upscale `NAME.mp4` with any other tool:

1. Upscale it with the tool you like. Keep the **frame rate and the frame count** (`NAME.json`): the replacement is shown frame for frame against the game's own audio.
2. Keep the 480:272 picture shape, at any size (for example 1920×1088 or 3840×2176).
3. Put the result where the port looks for replacement movies (in Sparta: planned, see its documentation).

## How it works

A PSMF file is a 2 KiB header (the stream table, the picture size, the first and last presentation time) followed by an MPEG program stream: H.264 video in stream `0xE0`, ATRAC3plus audio in private stream 1 (`0xBD`). The tool reads the disc image's ISO 9660 directories itself, finds files that start with `PSMF`, and copies the video stream's PES payloads out, in order.

## License

MIT ([LICENSE](LICENSE)).
