"""Installer factory and unified interface."""

import sys
import os
from typing import Optional

from .base import InstallerInterface
from .linux import LinuxInstaller
from .termux import TermuxInstaller
from .windows import WindowsInstaller
from .macos import MacOSInstaller


def get_installer() -> InstallerInterface:
    """Factory function to get the platform-specific installer."""
    if sys.platform.startswith("linux"):
        # Check for Termux
        if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
            return TermuxInstaller()
        return LinuxInstaller()
    elif sys.platform == "win32":
        return WindowsInstaller()
    elif sys.platform == "darwin":
        return MacOSInstaller()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


__all__ = ["InstallerInterface", "get_installer"]