"""Platform abstraction layer for cross-platform network monitoring."""

from .base import PlatformInterface, PlatformInfo, get_platform

__all__ = ["PlatformInterface", "PlatformInfo", "get_platform"]