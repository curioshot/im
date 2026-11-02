"""Windows installer implementation."""

import subprocess
import shutil
import sys
import os
import ctypes
from typing import Dict, List

from .base import InstallerInterface, Dependency, DepType, DepStatus


class WindowsInstaller(InstallerInterface):
    """Windows installer using winget/choco/scoop."""

    platform_name = "windows"

    def __init__(self):
        self._pm = None

    def detect_platform(self) -> Dict:
        # Check for package managers in priority order
        for pm in ["winget", "choco", "scoop"]:
            if shutil.which(pm):
                self._pm = pm
                break
        if not self._pm:
            self._pm = "winget"  # Default (built-in on Win 10/11)

        return {
            "system": "windows",
            "distro": "windows",
            "version": sys.getwindowsversion().major,
            "package_manager": self._pm,
            "has_admin": self._check_admin(),
        }

    def _check_admin(self) -> bool:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False

    def get_package_manager(self) -> str:
        if self._pm is None:
            self.detect_platform()
        return self._pm

    def get_required_dependencies(self) -> List[Dependency]:
        return [
            Dependency(
                name="rich",
                dep_type=DepType.PYTHON,
                description="Rich TUI rendering library",
                required=True,
                package_name="rich",
                version_check="python -c \"import rich; print(rich.__version__)\"",
            ),
            Dependency(
                name="typer",
                dep_type=DepType.PYTHON,
                description="CLI framework",
                required=True,
                package_name="typer",
                version_check="python -c \"import typer; print(typer.__version__)\"",
            ),
            Dependency(
                name="psutil",
                dep_type=DepType.PYTHON,
                description="Cross-platform system/process utilities",
                required=False,
                package_name="psutil",
                version_check="python -c \"import psutil; print(psutil.__version__)\"",
            ),
            Dependency(
                name="distro",
                dep_type=DepType.PYTHON,
                description="Platform detection",
                required=True,
                package_name="distro",
                version_check="python -c \"import distro; print(distro.__version__)\"",
            ),
            Dependency(
                name="wmi",
                dep_type=DepType.PYTHON,
                description="WMI interface for network info",
                required=False,
                package_name="wmi",
                version_check="python -c \"import wmi; print(wmi.__version__)\"",
            ),
            Dependency(
                name="pywin32",
                dep_type=DepType.PYTHON,
                description="Windows API access",
                required=False,
                package_name="pywin32",
                version_check="python -c \"import win32api; print(win32api.__version__)\"",
            ),
            # System packages via package manager
            Dependency(
                name="tcpdump/npcap",
                dep_type=DepType.SYSTEM,
                description="Npcap for packet capture (--root)",
                required=False,
                package_name="npcap",
                version_check="npcap --version 2>&1 || echo 'check dll'",
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
        else:
            if dep.name == "tcpdump/npcap":
                # Check for Npcap DLL
                paths = [
                    r"C:\Program Files\Npcap\npcap.dll",
                    r"C:\Program Files (x86)\Npcap\npcap.dll",
                ]
                for p in paths:
                    if os.path.exists(p):
                        return DepStatus.OK
                return DepStatus.MISSING
            return DepStatus.MISSING

    def install_dependency(self, dep: Dependency) -> bool:
        dep.status = DepStatus.INSTALLING

        try:
            if dep.dep_type == DepType.PYTHON:
                return self._install_python(dep)
            else:
                return self._install_system(dep)
        except Exception:
            dep.status = DepStatus.FAILED
            return False

    def _install_python(self, dep: Dependency) -> bool:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", dep.package_name],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0:
                dep.status = DepStatus.INSTALLED
                return True
            dep.status = DepStatus.FAILED
            return False
        except Exception:
            dep.status = DepStatus.FAILED
            return False

    def _install_system(self, dep: Dependency) -> bool:
        pm = self.get_package_manager()

        if dep.name == "tcpdump/npcap":
            return self._install_npcap()

        # For other system packages, try package manager
        pkg_name = dep.package_name
        if pm == "winget":
            cmd = ["winget", "install", "--id", pkg_name, "--silent", "--accept-source-agreements", "--accept-package-agreements"]
        elif pm == "choco":
            cmd = ["choco", "install", pkg_name, "-y"]
        elif pm == "scoop":
            cmd = ["scoop", "install", pkg_name]
        else:
            dep.status = DepStatus.FAILED
            return False

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=180)
            if result.returncode == 0:
                dep.status = DepStatus.INSTALLED
                return True
            dep.status = DepStatus.FAILED
            return False
        except Exception:
            dep.status = DepStatus.FAILED
            return False

    def _install_npcap(self) -> bool:
        """Download and silently install Npcap."""
        import urllib.request
        import tempfile

        # Check if already installed
        for p in [r"C:\Program Files\Npcap\npcap.dll", r"C:\Program Files (x86)\Npcap\npcap.dll"]:
            if os.path.exists(p):
                return True

        try:
            # Use latest stable Npcap version
            url = "https://npcap.com/dist/npcap-1.75.exe"
            with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
                installer_path = f.name
                urllib.request.urlretrieve(url, installer_path)
            
            # Silent install with WinPcap compatibility mode
            result = subprocess.run(
                [installer_path, "/S", "/winpcap_mode=yes"],
                capture_output=True, timeout=180,
            )
            os.unlink(installer_path)
            
            if result.returncode == 0:
                # Verify installation
                for p in [r"C:\Program Files\Npcap\npcap.dll", r"C:\Program Files (x86)\Npcap\npcap.dll"]:
                    if os.path.exists(p):
                        return True
            return False
        except Exception:
            return False

    def supports_auto_install(self) -> bool:
        # Need admin for system packages
        return self._check_admin()