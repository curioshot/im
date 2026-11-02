"""Termux installer implementation."""

import subprocess
import shutil
import sys
import os
from typing import Dict, List

from .base import InstallerInterface, Dependency, DepType, DepStatus


class TermuxInstaller(InstallerInterface):
    """Termux installer using pkg."""

    platform_name = "termux"

    def detect_platform(self) -> Dict:
        return {
            "system": "linux",
            "distro": "termux",
            "version": os.environ.get("TERMUX_VERSION", "unknown"),
            "package_manager": "pkg",
        }

    def get_package_manager(self) -> str:
        return "pkg"

    def get_required_dependencies(self) -> List[Dependency]:
        return [
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
            Dependency(
                name="iproute2",
                dep_type=DepType.SYSTEM,
                description="Network interface/routing tools (ip command)",
                required=True,
                package_name="iproute2",
                version_check="ip --version",
            ),
            Dependency(
                name="tcpdump",
                dep_type=DepType.SYSTEM,
                description="Packet capture for DNS sniffing (--root)",
                required=False,
                package_name="tcpdump",
                version_check="tcpdump --version",
            ),
            # Termux-specific
            Dependency(
                name="termux-api",
                dep_type=DepType.SYSTEM,
                description="Termux API for Wi-Fi info",
                required=False,
                package_name="termux-api",
                version_check="termux-wifi-connectioninfo",
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
            if dep.name == "iproute2":
                return DepStatus.OK if shutil.which("ip") else DepStatus.MISSING
            elif dep.name == "tcpdump":
                return DepStatus.OK if shutil.which("tcpdump") else DepStatus.MISSING
            elif dep.name == "termux-api":
                return DepStatus.OK if shutil.which("termux-wifi-connectioninfo") else DepStatus.MISSING
            else:
                return DepStatus.OK if shutil.which(dep.package_name) else DepStatus.MISSING

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
        pkg_name = dep.package_name
        try:
            # Termux pkg doesn't need sudo
            result = subprocess.run(
                ["pkg", "install", "-y", pkg_name],
                capture_output=True, timeout=180,
            )
            if result.returncode == 0:
                dep.status = DepStatus.INSTALLED
                return True
            dep.status = DepStatus.FAILED
            return False
        except Exception:
            dep.status = DepStatus.FAILED
            return False