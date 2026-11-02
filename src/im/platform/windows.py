"""Windows platform implementation."""

import os
import re
import socket
import subprocess
import sys
import ctypes
from typing import Dict, List, Tuple, Optional, Callable, Iterator

from .base import PlatformInterface, PlatformInfo


class WindowsPlatform(PlatformInterface):
    """Windows platform implementation."""

    name = "windows"

    def __init__(self):
        self._info_cache: Optional[PlatformInfo] = None
        self._wmi = None
        self._psutil = None

    def get_platform_info(self) -> PlatformInfo:
        if self._info_cache:
            return self._info_cache

        # Check for Admin
        has_admin = False
        try:
            has_admin = ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            pass

        # Check for WSL
        is_wsl = "microsoft" in (os.uname().release.lower() if hasattr(os, 'uname') else "")

        self._info_cache = PlatformInfo(
            system="windows",
            distro="windows",
            distro_version=sys.getwindowsversion().major,
            arch=os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64"),
            python_version=sys.version.split()[0],
            has_sudo=False,
            has_admin=has_admin,
            is_termux=False,
            is_wsl=is_wsl,
        )
        return self._info_cache

    def _get_wmi(self):
        if self._wmi is None:
            try:
                import wmi
                self._wmi = wmi.WMI()
            except ImportError:
                self._wmi = False
        return self._wmi

    def _get_psutil(self):
        if self._psutil is None:
            try:
                import psutil
                self._psutil = psutil
            except ImportError:
                self._psutil = False
        return self._psutil

    def get_default_gateway(self) -> str:
        # Try WMI first
        wmi_obj = self._get_wmi()
        if wmi_obj:
            try:
                for nic in wmi_obj.Win32_NetworkAdapterConfiguration(IPEnabled=True):
                    if nic.DefaultIPGateway:
                        return nic.DefaultIPGateway[0]
            except Exception:
                pass

        # Fallback to route print
        try:
            out = subprocess.run(
                ["route", "print", "0.0.0.0"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                if "0.0.0.0" in line and "0.0.0.0" == line.split()[0]:
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
        except Exception:
            pass

        return "-"

    def get_interface_counters(self) -> Dict[str, Tuple[int, int]]:
        # Prefer psutil
        psutil = self._get_psutil()
        if psutil:
            try:
                counters = psutil.net_io_counters(pernic=True)
                return {name: (c.bytes_recv, c.bytes_sent) for name, c in counters.items()
                        if name.lower() != "loopback" and name.lower() != "lo"}
            except Exception:
                pass

        # Fallback to netsh
        try:
            out = subprocess.run(
                ["netsh", "interface", "ip", "show", "interface"],
                capture_output=True, text=True, timeout=5,
            )
            # This doesn't give byte counters, so return empty
            return {}
        except Exception:
            pass

        return {}

    def get_arp_table(self) -> List[Dict[str, str]]:
        entries = []

        # Try GetIpNetTable2 via PowerShell
        try:
            ps_script = """
            Get-NetNeighbor | Where-Object {$_.State -ne 'Unreachable'} |
            Select-Object IPAddress, LinkLayerAddress, State | ConvertTo-Json
            """
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                import json
                data = json.loads(out.stdout)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    ip = item.get("IPAddress", "")
                    mac = item.get("LinkLayerAddress", "").replace("-", ":").lower()
                    state = item.get("State", "").upper()
                    if ip and mac and mac != "00:00:00:00:00:00":
                        entries.append({"ip": ip, "mac": mac, "state": state})
                return entries
        except Exception:
            pass

        # Fallback to arp -a
        try:
            out = subprocess.run(
                ["arp", "-a"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                # Format: "  192.168.1.1          00-11-22-33-44-55     dynamic"
                parts = line.split()
                if len(parts) >= 3:
                    ip = parts[0]
                    mac = parts[1].replace("-", ":").lower()
                    state = "REACHABLE" if parts[2].lower() == "dynamic" else "STALE"
                    if ip and mac and mac != "00:00:00:00:00:00":
                        entries.append({"ip": ip, "mac": mac, "state": state})
        except Exception:
            pass

        return entries

    def get_wifi_info(self) -> str:
        # Try netsh wlan
        try:
            out = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=5,
            )
            ssid = None
            signal = None
            for line in out.stdout.splitlines():
                line = line.strip()
                if line.startswith("SSID"):
                    ssid = line.split(":", 1)[1].strip()
                elif line.startswith("Signal"):
                    signal = line.split(":", 1)[1].strip().replace("%", "")
                    if signal.isdigit():
                        # Convert percentage to approximate dBm
                        signal = str(int(signal) - 100)
            if ssid and signal:
                return f"{ssid} ({signal} dBm)"
            elif ssid:
                return ssid
        except Exception:
            pass

        # Try WMI
        wmi_obj = self._get_wmi()
        if wmi_obj:
            try:
                for nic in wmi_obj.Win32_NetworkAdapterConfiguration(IPEnabled=True):
                    if "wireless" in (nic.Description or "").lower() or "wi-fi" in (nic.Description or "").lower():
                        return nic.Description or "-"
            except Exception:
                pass

        return "-"

    def setup_raw_keyboard(self) -> Callable[[], None]:
        import msvcrt

        def check_key():
            return msvcrt.kbhit()

        def get_key():
            return msvcrt.getch().decode(errors="ignore").lower()

        # Store original state (not much to restore on Windows)
        return lambda: None

    def check_admin(self) -> bool:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False

    def create_dns_sniffer(self) -> Optional[Iterator[Tuple[str, str]]]:
        # On Windows, need Npcap + scapy
        # Check if Npcap is installed
        npcap_path = r"C:\Program Files\Npcap\npcap.dll"
        if not os.path.exists(npcap_path):
            npcap_path = r"C:\Program Files (x86)\Npcap\npcap.dll"
        if not os.path.exists(npcap_path):
            return None

        try:
            from scapy.all import sniff, DNS, DNSQR, IP
        except ImportError:
            return None

        if not self.check_admin():
            return None

        def packet_handler(pkt):
            if pkt.haslayer(DNS) and pkt.haslayer(DNSQR):
                if IP in pkt:
                    src_ip = pkt[IP].src
                    domain = pkt[DNSQR].qname.decode().rstrip(".")
                    return src_ip, domain
            return None

        def generator():
            # This is a simplified version - in practice you'd use a queue
            # and run sniff in a thread
            try:
                sniff(filter="port 53", prn=lambda p: None, store=0, count=1)
            except Exception:
                pass
            return
            yield  # Make it a generator

        return None  # Placeholder - full implementation needs threading

    def get_package_manager(self) -> str:
        # Priority: winget > choco > scoop
        for pm in ["winget", "choco", "scoop"]:
            if shutil.which(pm):
                return pm
        return "winget"  # Default (built-in on Win 10/11)

    def install_npcap(self) -> bool:
        """Download and silently install Npcap."""
        import urllib.request
        import tempfile

        if os.path.exists(r"C:\Program Files\Npcap\npcap.dll"):
            return True

        try:
            url = "https://npcap.com/dist/npcap-1.75.exe"  # Version may need updating
            with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
                urllib.request.urlretrieve(url, f.name)
                # Silent install with WinPcap compatibility mode
                subprocess.run([
                    f.name, "/S", "/winpcap_mode=yes"
                ], check=True, timeout=120)
            return True
        except Exception:
            return False


import shutil