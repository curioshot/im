"""Termux (Android) platform implementation."""

import os
import re
import json
import subprocess
import shutil
from typing import Dict, List, Tuple, Optional, Callable, Iterator

from .base import PlatformInterface, PlatformInfo
from .linux import read_file_maybe_su, su_works, valid_mac, NEIGH_LIVE


class TermuxPlatform(PlatformInterface):
    """Termux platform implementation."""

    name = "termux"

    def __init__(self):
        self._info_cache: Optional[PlatformInfo] = None

    def get_platform_info(self) -> PlatformInfo:
        if self._info_cache:
            return self._info_cache

        import sys

        # Termux doesn't have sudo, uses su for root
        has_su = su_works()

        self._info_cache = PlatformInfo(
            system="linux",
            distro="termux",
            distro_version=os.environ.get("TERMUX_VERSION", "unknown"),
            arch=os.uname().machine,
            python_version=sys.version.split()[0],
            has_sudo=False,
            has_admin=has_su,
            is_termux=True,
            is_wsl=False,
        )
        return self._info_cache

    def get_default_gateway(self) -> str:
        # Same as Linux
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
        # Same as Linux
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
        # Same as Linux but with Termux-specific paths
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

        entries = []
        for line in read_file_maybe_su("/proc/net/arp").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4 or not valid_mac(fields[3]):
                continue
            state = "REACHABLE" if fields[2] in ("0x2", "0x6") else "STALE"
            entries.append({"ip": fields[0], "mac": fields[3], "state": state})
        return entries

    def get_wifi_info(self) -> str:
        # Termux-specific Wi-Fi info
        try:
            out = subprocess.run(
                ["termux-wifi-connectioninfo"],
                capture_output=True, text=True, timeout=4,
            )
            data = json.loads(out.stdout)
            ssid = data.get("ssid") or "-"
            rssi = data.get("rssi")
            return f"{ssid} ({rssi} dBm)" if rssi is not None else ssid
        except Exception:
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
        return su_works()

    def create_dns_sniffer(self) -> Optional[Iterator[Tuple[str, str]]]:
        if not su_works():
            return None

        if not shutil.which("tcpdump"):
            return None

        cmd = "tcpdump -i any -n -l -s 0 port 53"
        try:
            proc = subprocess.Popen(
                ["su", "-c", cmd],
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
        return "pkg"