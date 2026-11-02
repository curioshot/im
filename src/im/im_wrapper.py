#!/usr/bin/env python3
"""
Wrapper script for im command.
This can be installed as a console script entry point.
"""

import sys
import os

# Add the im package directory to sys.path
# This allows the script to work when installed via pipx or as a standalone script
IM_ROOT = os.path.dirname(os.path.abspath(__file__))
if IM_ROOT not in sys.path:
    sys.path.insert(0, IM_ROOT)

from im.cli.__main__ import app

if __name__ == "__main__":
    app()