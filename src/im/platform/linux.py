"""Linux platform implementation."""

import os
import re
import json
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple, Optional, Callable, Iterator

from .base import PlatformInterface, PlatformInfo


def read_file_maybe_su(path: str) -> str:
    """Read file, trying sudo if permission denied."""
    try:
        with open(path, encoding="ascii") as f:
            return f.read()
    except OSError:
        pass
    if su_works():
        try:
            return subprocess.run(
                ["su", "-c", f"cat {path}"],
                capture_output=True, text=True, timeout=4,
            ).stdout or ""
        except (OSError, subprocess.SubprocessError):
            return ""
    return ""


_SU_STATE = {}


def su_works() -> bool:
    """Check if su command works (Termux root)."""
    if "ok" not in _SU_STATE:
        try:
            out = subprocess.run(
                ["su", "-c", "id"], capture_output=True, text=True, timeout=4,
            )
            _SU_STATE["ok"] = out.returncode == 0 and "uid=" in (out.stdout or "")
        except (OSError, subprocess.SubprocessError):
            _SU_STATE["ok"] = False
    return _SU_STATE["ok"]


def valid_mac(mac: str) -> bool:
    if not mac:
        return False
    parts = mac.split(":")
    if len(parts) != 6:
        return False
    uniq = {p.lower() for p in parts}
    return uniq not in ({"00"}, {"ff"})


NEIGH_LIVE = ("REACHABLE", "DELAY", "PROBE")


class LinuxPlatform(PlatformInterface):
    """Linux platform implementation (standard Linux, not Termux)."""

    name = "linux"

    def __init__(self):
        self._info_cache: Optional[PlatformInfo] = None

    def get_platform_info(self) -> PlatformInfo:
        if self._info_cache:
            return self._info_cache

        import sys
        import distro

        # Detect distro
        distro_id = distro.id().lower()
        distro_version = distro.version()

        # Check for WSL
        is_wsl = "microsoft" in (os.uname().release.lower())

        # Check sudo
        has_sudo = False
        try:
            subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=2)
            has_sudo = True
        except (OSError, subprocess.SubprocessError):
            pass

        self._info_cache = PlatformInfo(
            system="linux",
            distro=distro_id,
            distro_version=distro_version,
            arch=os.uname().machine,
            python_version=sys.version.split()[0],
            has_sudo=has_sudo,
            has_admin=False,
            is_termux=False,
            is_wsl=is_wsl,
        )
        return self._info_cache

    def get_default_gateway(self) -> str:
        try:
            for line in read_file_maybe_su("/proc/net/route").splitlines()[1:]:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    raw = int(fields[2], 16).to_bytes(4, "little")
                    return ".".join(str(b) for b in raw)
        except Exception:
            pass
        return "-"

    def get_interface_counters(self) -> Dict[str, Tuple[int, int]]:
        counts = {}
        try:
            for line in read_file_maybe_su("/proc/net/dev").splitlines()[2:]:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                fields = rest.split()
                if len(fields) >= 9:
                    try:
                        counts[name.strip()] = (int(fields[0]), int(fields[8]))
                    except ValueError:
                        continue
        except Exception:
            pass
        return counts

    def get_arp_table(self) -> List[Dict[str, str]]:
        # Try ip command first
        for command in (
            ["ip", "-f", "inet", "neigh", "show"],
            ["su", "-c", "ip -f inet neigh show"],
        ):
            try:
                out = subprocess.run(command, capture_output=True, text=True, timeout=4)
                if out.returncode == 0 and out.stdout.strip():
                    entries = []
                    for line in out.stdout.splitlines():
                        fields = line.split()
                        if len(fields) < 2:
                            continue
                        mac = None
                        for i, word in enumerate(fields):
                            if word == "lladdr" and i + 1 < len(fields):
                                mac = fields[i + 1]
                        entries.append({
                            "ip": fields[0],
                            "mac": mac or "",
                            "state": fields[-1].upper(),
                        })
                    return [e for e in entries if valid_mac(e["mac"])]
            except (OSError, subprocess.SubprocessError):
                pass

        # Fallback to /proc/net/arp
        entries = []
        for line in read_file_maybe_su("/proc/net/arp").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4 or not valid_mac(fields[3]):
                continue
            state = "REACHABLE" if fields[2] in ("0x2", "0x6") else "STALE"
            entries.append({"ip": fields[0], "mac": fields[3], "state": state})
        return entries

    def get_wifi_info(self) -> str:
        # Try NetworkManager first
        try:
            out = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid,signal", "dev", "wifi"],
                capture_output=True, text=True, timeout=4,
            )
            if out.returncode == 0:
                for line in out.stdout.strip().split("\n"):
                    if line.startswith("yes:"):
                        _, ssid, signal = line.split(":", 2)
                        return f"{ssid} ({signal} dBm)"
        except (OSError, subprocess.SubprocessError):
            pass

        # Try iwconfig
        try:
            out = subprocess.run(
                ["iwconfig"], capture_output=True, text=True, timeout=4
            )
            if out.returncode == 0:
                for line in out.stdout.splitlines():
                    if "ESSID:" in line:
                        import re
                        ssid_match = re.search(r'ESSID:"([^"]+)"', line)
                        signal_match = re.search(r"Signal level=(-?\d+)", line)
                        ssid = ssid_match.group(1) if ssid_match else "-"
                        signal = signal_match.group(1) if signal_match else "?"
                        return f"{ssid} ({signal} dBm)"
        except (OSError, subprocess.SubprocessError):
            pass

        return "-"

    def setup_raw_keyboard(self) -> Callable[[], None]:
        import sys
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
        """Create DNS sniffer using tcpdump. Needs root."""
        if not self.check_admin() and not su_works():
            return None

        if not shutil.which("tcpdump"):
            return None

        cmd = "tcpdump -i any -n -l -s 0 port 53"
        try:
            if su_works():
                proc = subprocess.Popen(
                    ["su", "-c", cmd],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1,
                )
            else:
                proc = subprocess.Popen(
                    ["sudo", "-n"] + cmd.split(),
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
        """Return the package manager for this distro."""
        info = self.get_platform_info()
        distro = info.distro.lower()

        if distro in ("debian", "ubuntu", "mint", "kali", "pop", "elementary", "zorin"):
            return "apt"
        elif distro in ("arch", "manjaro", "endeavouros", "garuda", "artix"):
            return "pacman"
        elif distro in ("fedora", "rhel", "centos", "rocky", "alma", "nobara"):
            return "dnf"
        elif distro in ("opensuse", "suse"):
            return "zypper"
        elif distro == "alpine":
            return "apk"
        else:
            return "apt"  # default fallback


# Import shutil at module level for dns_sniffer
import shutil