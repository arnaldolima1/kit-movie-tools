#!/usr/bin/env python3
"""The command line: python psp_movies.py --help. The window: python psp_movies.py gui."""
import sys

from psp_movie_tools.cli import main

if __name__ == '__main__':
    sys.exit(main())
