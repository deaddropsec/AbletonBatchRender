#!/usr/bin/env python3
"""Ableton Offline Renderer.

Batch export Ableton Live projects to audio files without manual interaction.
Requires Ableton Live 12 with the RenderMonitor Remote Script.

Usage:
    python main.py <als-file-or-directory> [--export-dir <path>]
"""

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
