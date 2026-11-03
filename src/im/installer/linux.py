"""Linux installer implementation."""

import subprocess
import shutil
import sys
import os
from typing import List, Dict, Optional

from .base import InstallerInterface, Dependency, DepType, DepStatus, SudoHelper


class LinuxInstaller(InstallerInterface):
    """Linux installer using apt/dnf/pacman/zypper/apk."""

    platform_name = "linux"

    # Distro to package manager mapping
    DISTRO_PM = {
        "debian": "apt",
        "ubuntu": "apt",
        "mint": "apt",
        "kali": "apt",
        "pop": "apt",
        "elementary": "apt",
        "zorin": "apt",
        "arch": "pacman",
        "manjaro": "pacman",
        "endeavouros": "pacman",
        "garuda": "pacman",
        "artix": "pacman",
        "fedora": "dnf",
        "rhel": "dnf",
        "centos": "dnf",
        "rocky": "dnf",
        "alma": "dnf",
        "nobara": "dnf",
        "opensuse": "zypper",
        "suse": "zypper",
        "alpine": "apk",
    }

    # Package name mappings per package manager
    PKG_MAP = {
        "apt": {
            "iproute2": "iproute2",
            "tcpdump": "tcpdump",
            "network-manager": "network-manager",
            "python3-rich": "python3-rich",
            "python3-psutil": "python3-psutil",
            "python3-distro": "python3-distro",
        },
        "dnf": {
            "iproute2": "iproute",
            "tcpdump": "tcpdump",
            "network-manager": "NetworkManager",
            "python3-rich": "python3-rich",
            "python3-psutil": "python3-psutil",
            "python3-distro": "python3-distro",
        },
        "pacman": {
            "iproute2": "iproute2",
            "tcpdump": "tcpdump",
            "network-manager": "networkmanager",
            "python3-rich": "python-rich",
            "python3-psutil": "python-psutil",
            "python3-distro": "python-distro",
        },
        "zypper": {
            "iproute2": "iproute2",
            "tcpdump": "tcpdump",
            "network-manager": "NetworkManager",
            "python3-rich": "python3-rich",
            "python3-psutil": "python3-psutil",
            "python3-distro": "python3-distro",
        },
        "apk": {
            "iproute2": "iproute2",
            "tcpdump": "tcpdump",
            "network-manager": "networkmanager",
            "python3-rich": "py3-rich",
            "python3-psutil": "py3-psutil",
            "python3-distro": "py3-distro",
        },
    }

    def __init__(self):
        self._pm = None
        self._distro = None

    def detect_platform(self) -> Dict:
        import distro
        distro_id = distro.id().lower()
        self._distro = distro_id
        self._pm = self.DISTRO_PM.get(distro_id, "apt")
        return {
            "system": "linux",
            "distro": distro_id,
            "version": distro.version(),
            "package_manager": self._pm,
        }

    def get_package_manager(self) -> str:
        if self._pm is None:
            self.detect_platform()
        return self._pm

    def get_required_dependencies(self) -> List[Dependency]:
        pm = self.get_package_manager()
        pkg_map = self.PKG_MAP.get(pm, self.PKG_MAP["apt"])

        return [
            # Python packages (installed via pip)
            Dependency(
                name="rich",
                dep_type=DepType.PYTHON,
                description="Rich TUI rendering library",
                required=True,
                package_name="rich",
                version_check="python3 -c \"import rich; print(rich.__version__)\"",
            ),
            Dependency(
                name="typer",
                dep_type=DepType.PYTHON,
                description="CLI framework",
                required=True,
                package_name="typer",
                version_check="python3 -c \"import typer; print(typer.__version__)\"",
            ),
            Dependency(
                name="psutil",
                dep_type=DepType.PYTHON,
                description="Cross-platform system/process utilities",
                required=False,
                package_name="psutil",
                version_check="python3 -c \"import psutil; print(psutil.__version__)\"",
            ),
            Dependency(
                name="distro",
                dep_type=DepType.PYTHON,
                description="Linux distribution detection",
                required=True,
                package_name="distro",
                version_check="python3 -c \"import distro; print(distro.__version__)\"",
            ),
            # System packages
            Dependency(
                name="iproute2",
                dep_type=DepType.SYSTEM,
                description="Network interface/routing tools (ip command)",
                required=True,
                package_name=pkg_map.get("iproute2", "iproute2"),
                version_check="ip --version",
            ),
            Dependency(
                name="tcpdump",
                dep_type=DepType.SYSTEM,
                description="Packet capture for DNS sniffing (--root)",
                required=False,
                package_name=pkg_map.get("tcpdump", "tcpdump"),
                version_check="tcpdump --version",
            ),
            Dependency(
                name="network-manager",
                dep_type=DepType.SYSTEM,
                description="NetworkManager for Wi-Fi info (nmcli)",
                required=False,
                package_name=pkg_map.get("network-manager", "network-manager"),
                version_check="nmcli --version",
            ),
        ]

    def check_dependencies(self) -> List[Dependency]:
        deps = self.get_required_dependencies()
        for dep in deps:
            dep.status = self._check_single(dep)
        return deps

    def _check_single(self, dep: Dependency) -> DepStatus:
        if dep.dep_type == DepType.PYTHON:
            try:
                __import__(dep.package_name.replace("-", "_"))
                return DepStatus.OK
            except ImportError:
                return DepStatus.MISSING
        else:  # SYSTEM
            if dep.name == "iproute2":
                return DepStatus.OK if shutil.which("ip") else DepStatus.MISSING
            elif dep.name == "tcpdump":
                return DepStatus.OK if shutil.which("tcpdump") else DepStatus.MISSING
            elif dep.name == "network-manager":
                return DepStatus.OK if shutil.which("nmcli") else DepStatus.MISSING
            else:
                # Generic check
                return DepStatus.OK if shutil.which(dep.package_name) else DepStatus.MISSING

    def install_dependency(self, dep: Dependency) -> bool:
        dep.status = DepStatus.INSTALLING

        try:
            if dep.dep_type == DepType.PYTHON:
                return self._install_python(dep)
            else:
                return self._install_system(dep)
        except Exception as e:
            dep.status = DepStatus.FAILED
            return False

    def _install_python(self, dep: Dependency) -> bool:
        """Install Python package via pip."""
        try:
            # Use sys.executable to ensure correct pip
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", dep.package_name],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0:
                dep.status = DepStatus.INSTALLED
                return True
            else:
                dep.status = DepStatus.FAILED
                return False
        except Exception:
            dep.status = DepStatus.FAILED
            return False

    def _install_system(self, dep: Dependency) -> bool:
        """Install system package via package manager with proper sudo handling."""
        pm = self.get_package_manager()
        pkg_name = dep.package_name

        if pm == "apt":
            full_cmd = f"sudo apt update && sudo apt install -y {pkg_name}"
        elif pm == "dnf":
            full_cmd = f"sudo dnf install -y {pkg_name}"
        elif pm == "pacman":
            full_cmd = f"sudo pacman -S --noconfirm {pkg_name}"
        elif pm == "zypper":
            full_cmd = f"sudo zypper install -y {pkg_name}"
        elif pm == "apk":
            full_cmd = f"sudo apk add {pkg_name}"
        else:
            dep.status = DepStatus.FAILED
            return False

        try:
            # Use SudoHelper to handle password prompting
            result = SudoHelper.run_sudo_shell(full_cmd, f"Enter password to install {pkg_name}:")
            if result.returncode == 0:
                dep.status = DepStatus.INSTALLED
                return True
            else:
                # Show error to user
                if result.stderr:
                    print(f"Error installing {pkg_name}: {result.stderr.decode().strip()}")
                dep.status = DepStatus.FAILED
                return False
        except Exception as e:
            print(f"Failed to install {pkg_name}: {e}")
            dep.status = DepStatus.FAILED
            return False