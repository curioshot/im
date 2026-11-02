#!/usr/bin/env python3
"""
Standalone im command entry point.
This script can be installed directly as a console script.
"""

import sys
import os
import subprocess

# Find the im package root
def find_im_root():
    # Try to find the im package in common locations
    possible_paths = [
        os.path.join(os.path.dirname(__file__), 'im'),  # Next to script
        os.path.join(os.path.dirname(__file__), '..', 'im'),  # Parent
        '/home/tareq1/Downloads/im',  # Development path
    ]
    
    # Also check site-packages
    for path in sys.path:
        im_path = os.path.join(path, 'im')
        if os.path.isdir(im_path) and os.path.exists(os.path.join(im_path, 'cli')):
            possible_paths.append(im_path)
    
    for path in possible_paths:
        path = os.path.abspath(path)
        if os.path.exists(os.path.join(path, 'cli', '__main__.py')):
            return path
    
    return None

IM_ROOT = find_im_root()

if IM_ROOT:
    sys.path.insert(0, IM_ROOT)
    
    # Also add parent of IM_ROOT if it contains the subpackages
    parent = os.path.dirname(IM_ROOT)
    if parent not in sys.path:
        sys.path.insert(0, parent)

from im.cli.__main__ import app

if __name__ == "__main__":
    app()