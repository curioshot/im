"""macOS platform implementation."""

import os
import re
import subprocess
import sys
import shutil
from typing import Dict, List, Tuple, Optional, Callable, Iterator

from .base import PlatformInterface, PlatformInfo


class MacOSPlatform(PlatformInterface):
    """macOS platform implementation."""

    name = "macos"

    def __init__(self):
        self._info_cache: Optional[PlatformInfo] = None

    def get_platform_info(self) -> PlatformInfo:
        if self._info_cache:
            return self._info_cache

        has_sudo = False
        try:
            subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=2)
            has_sudo = True
        except (OSError, subprocess.SubprocessError):
            pass

        self._info_cache = PlatformInfo(
            system="darwin",
            distro="macos",
            distro_version=subprocess.run(
                ["sw_vers", "-productVersion"], capture_output=True, text=True
            ).stdout.strip() or "unknown",
            arch=os.uname().machine,
            python_version=sys.version.split()[0],
            has_sudo=has_sudo,
            has_admin=False,
            is_termux=False,
            is_wsl=False,
        )
        return self._info_cache

    def get_default_gateway(self) -> str:
        # Try route command
        try:
            out = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                if "gateway:" in line:
                    return line.split("gateway:")[1].strip()
        except Exception:
            pass

        # Try scutil
        try:
            out = subprocess.run(
                ["scutil", "--dns"],
                capture_output=True, text=True, timeout=5,
            )
            # Parse for router
            for line in out.stdout.splitlines():
                if "router" in line.lower():
                    parts = line.split()
                    for p in parts:
                        if re.match(r"\d+\.\d+\.\d+\.\d+", p):
                            return p
        except Exception:
            pass

        return "-"

    def get_interface_counters(self) -> Dict[str, Tuple[int, int]]:
        # Try netstat -ib
        try:
            out = subprocess.run(
                ["netstat", "-ib"],
                capture_output=True, text=True, timeout=5,
            )
            counts = {}
            for line in out.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 10:
                    name = parts[0]
                    if name in ("lo0", "lo"):
                        continue
                    try:
                        rx = int(parts[6])  # ibytes
                        tx = int(parts[9])  # obytes
                        counts[name] = (rx, tx)
                    except (ValueError, IndexError):
                        continue
            if counts:
                return counts
        except Exception:
            pass

        return {}

    def get_arp_table(self) -> List[Dict[str, str]]:
        entries = []
        try:
            out = subprocess.run(
                ["arp", "-an"],
                capture_output=True, text=True, timeout=5,
            )
            # Format: "? (192.168.1.1) at 00:11:22:33:44:55 on en0 ifscope [ethernet]"
            for line in out.stdout.splitlines():
                match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-f:]+) on (\w+)", line)
                if match:
                    ip, mac, iface = match.groups()
                    state = "REACHABLE"  # arp -an doesn't show state on macOS
                    entries.append({"ip": ip, "mac": mac.lower(), "state": state})
        except Exception:
            pass
        return entries

    def get_wifi_info(self) -> str:
        # Try airport utility (private framework)
        airport_path = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
        if os.path.exists(airport_path):
            try:
                out = subprocess.run(
                    [airport_path, "-I"],
                    capture_output=True, text=True, timeout=5,
                )
                ssid = None
                rssi = None
                for line in out.stdout.splitlines():
                    if "SSID:" in line and "BSSID" not in line:
                        ssid = line.split(":", 1)[1].strip()
                    elif "agrCtlRSSI:" in line:
                        rssi = line.split(":", 1)[1].strip()
                if ssid and rssi:
                    return f"{ssid} ({rssi} dBm)"
                elif ssid:
                    return ssid
            except Exception:
                pass

        # Fallback to networksetup
        try:
            out = subprocess.run(
                ["networksetup", "-getairportnetwork", "en0"],
                capture_output=True, text=True, timeout=5,
            )
            if "Current Wi-Fi Network:" in out.stdout:
                ssid = out.stdout.split(":", 1)[1].strip()
                return ssid
        except Exception:
            pass

        return "-"

    def setup_raw_keyboard(self) -> Callable[[], None]:
        import termios
        import tty

        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return lambda: None

        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)

        def restore():
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass

        return restore

    def check_admin(self) -> bool:
        return os.geteuid() == 0

    def create_dns_sniffer(self) -> Optional[Iterator[Tuple[str, str]]]:
        if not self.check_admin():
            return None

        if not shutil.which("tcpdump"):
            return None

        cmd = ["sudo", "tcpdump", "-i", "any", "-n", "-l", "-s", "0", "port", "53"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
        except OSError:
            return None

        def parse_dns_line(line: str) -> Optional[Tuple[str, str]]:
            if " > " not in line or "?" not in line:
                return None
            src = re.search(r"IP (\d+\.\d+\.\d+\.\d+)\.\d+ > ", line)
            dom = re.search(r"\?\s+([A-Za-z0-9._-]+)", line)
            if src is None or dom is None:
                return None
            return src.group(1), dom.group(1).rstrip(".")

        def generator():
            for line in proc.stdout:
                parsed = parse_dns_line(line)
                if parsed:
                    yield parsed

        return generator()

    def get_package_manager(self) -> str:
        if shutil.which("brew"):
            return "brew"
        return "none"