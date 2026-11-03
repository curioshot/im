"""macOS installer implementation."""

import subprocess
import shutil
import sys
import os
from typing import Dict, List

from .base import InstallerInterface, Dependency, DepType, DepStatus, MacOSSudoHelper


class MacOSInstaller(InstallerInterface):
    """macOS installer using Homebrew."""

    platform_name = "macos"

    def detect_platform(self) -> Dict:
        has_brew = shutil.which("brew") is not None
        return {
            "system": "darwin",
            "distro": "macos",
            "version": subprocess.run(
                ["sw_vers", "-productVersion"], capture_output=True, text=True
            ).stdout.strip() or "unknown",
            "package_manager": "brew" if has_brew else "none",
            "has_brew": has_brew,
        }

    def get_package_manager(self) -> str:
        return "brew" if shutil.which("brew") else "none"

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
                description="Platform detection",
                required=True,
                package_name="distro",
                version_check="python3 -c \"import distro; print(distro.__version__)\"",
            ),
            # System packages via Homebrew
            Dependency(
                name="tcpdump",
                dep_type=DepType.SYSTEM,
                description="Packet capture for DNS sniffing (--root)",
                required=False,
                package_name="tcpdump",
                version_check="tcpdump --version",
            ),
            Dependency(
                name="iproute2mac",
                dep_type=DepType.SYSTEM,
                description="ip command alternative for macOS",
                required=False,
                package_name="iproute2mac",
                version_check="ip --version",
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
            if dep.name == "tcpdump":
                return DepStatus.OK if shutil.which("tcpdump") else DepStatus.MISSING
            elif dep.name == "iproute2mac":
                return DepStatus.OK if shutil.which("ip") else DepStatus.MISSING
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
        if not shutil.which("brew"):
            dep.status = DepStatus.FAILED
            return False

        pkg_name = dep.package_name
        try:
            # Homebrew packages don't need sudo
            result = subprocess.run(
                ["brew", "install", pkg_name],
                capture_output=True, timeout=180,
            )
            if result.returncode == 0:
                dep.status = DepStatus.INSTALLED
                return True
            else:
                if result.stderr:
                    print(f"Error installing {pkg_name}: {result.stderr.decode().strip()}")
                dep.status = DepStatus.FAILED
                return False
        except Exception as e:
            print(f"Failed to install {pkg_name}: {e}")
            dep.status = DepStatus.FAILED
            return False

    def install_homebrew(self) -> bool:
        """Install Homebrew if not present."""
        if shutil.which("brew"):
            return True

        try:
            # Homebrew install script
            script = "/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            result = subprocess.run(
                script, shell=True, capture_output=True, timeout=300,
            )
            return result.returncode == 0
        except Exception:
            return False