#!/usr/bin/env python3
"""The command line: python kit_movies.py --help. The window: python kit_movies.py gui."""
import sys

from kit_movie_tools.cli import main

if __name__ == '__main__':
    sys.exit(main())
