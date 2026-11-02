"""Platform abstraction base class."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable, Iterator, Any


@dataclass
class PlatformInfo:
    """Information about the current platform."""
    system: str          # "linux", "windows", "darwin"
    distro: str          # "debian", "ubuntu", "arch", "fedora", "termux", etc.
    distro_version: str  # Version string
    arch: str            # "x86_64", "aarch64", "arm64", etc.
    python_version: str  # "3.12.3"
    has_sudo: bool       # Can run sudo (Linux/macOS)
    has_admin: bool      # Running as Admin (Windows)
    is_termux: bool      # Running in Termux
    is_wsl: bool         # Running in WSL


class PlatformInterface(ABC):
    """Abstract base class for platform-specific operations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Platform identifier: 'linux', 'windows', 'macos', 'termux'."""
        ...

    @abstractmethod
    def get_default_gateway(self) -> str:
        """Return default gateway IP or '-' if unknown."""
        ...

    @abstractmethod
    def get_interface_counters(self) -> Dict[str, Tuple[int, int]]:
        """
        Return interface counters: {iface_name: (rx_bytes, tx_bytes)}.
        Excludes loopback.
        """
        ...

    @abstractmethod
    def get_arp_table(self) -> List[Dict[str, str]]:
        """
        Return ARP/neighbor table entries.
        Each entry: {"ip": "...", "mac": "...", "state": "REACHABLE|STALE|..."}
        """
        ...

    @abstractmethod
    def get_wifi_info(self) -> str:
        """Return Wi-Fi info string like 'SSID (-45 dBm)' or '-' if unavailable."""
        ...

    @abstractmethod
    def setup_raw_keyboard(self) -> Callable[[], None]:
        """
        Set up raw keyboard input (non-blocking, no echo).
        Returns a restore function to call on exit.
        """
        ...

    @abstractmethod
    def check_admin(self) -> bool:
        """Return True if running with root/Admin privileges."""
        ...

    @abstractmethod
    def create_dns_sniffer(self) -> Optional[Iterator[Tuple[str, str]]]:
        """
        Create a DNS sniffer that yields (source_ip, domain) tuples.
        Returns None if not available (needs root/Admin, tcpdump/Npcap).
        """
        ...

    @abstractmethod
    def get_platform_info(self) -> PlatformInfo:
        """Return detailed platform information."""
        ...


def get_platform() -> PlatformInterface:
    """Factory function to get the platform-specific implementation."""
    import sys
    import os

    if sys.platform.startswith("linux"):
        # Check for Termux
        if os.environ.get("TERMUX_VERSION") or os.path.exists("/data/data/com.termux"):
            from .termux import TermuxPlatform
            return TermuxPlatform()
        from .linux import LinuxPlatform
        return LinuxPlatform()
    elif sys.platform == "win32":
        from .windows import WindowsPlatform
        return WindowsPlatform()
    elif sys.platform == "darwin":
        from .macos import MacOSPlatform
        return MacOSPlatform()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")