"""Installer abstraction base class."""

import sys
import subprocess
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class DepType(Enum):
    PYTHON = "python"
    SYSTEM = "system"


class DepStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    WILL_INSTALL = "will_install"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Dependency:
    name: str
    dep_type: DepType
    description: str
    required: bool = True
    status: DepStatus = DepStatus.MISSING
    install_cmd: str = ""
    package_name: str = ""
    version_check: str = ""


@dataclass
class InstallPlan:
    dependencies: List[Dependency]
    package_manager: str
    needs_admin: bool = False
    estimated_time: int = 0


class SudoHelper:
    """Helper for running commands with sudo/admin privileges."""
    
    @staticmethod
    def has_passwordless_sudo() -> bool:
        """Check if sudo works without password."""
        try:
            result = subprocess.run(
                ["sudo", "-n", "true"],
                capture_output=True, timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False
    
    @staticmethod
    def run_with_sudo(command: List[str], prompt: str = "Password:") -> subprocess.CompletedProcess:
        """Run command with sudo, prompting for password if needed."""
        if SudoHelper.has_passwordless_sudo():
            return subprocess.run(
                ["sudo", "-n"] + command,
                capture_output=True, timeout=180
            )
        
        # Use sudo with -A (askpass) and provide a simple askpass script
        # This will prompt in the terminal
        env = os.environ.copy()
        # Create a simple askpass that reads from terminal
        askpass_script = '''#!/bin/bash
read -r -p "{} " PASS </dev/tty
echo "$PASS"
'''.format(prompt.replace('"', '\\"'))
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(askpass_script)
            askpass_path = f.name
        
        try:
            os.chmod(askpass_path, 0o755)
            env = os.environ.copy()
            env['SUDO_ASKPASS'] = askpass_path
            return subprocess.run(
                ["sudo", "-A"] + command,
                capture_output=True, timeout=180, env=env
            )
        finally:
            try:
                os.unlink(askpass_path)
            except Exception:
                pass
    
    @staticmethod
    def run_sudo_shell(command: str, prompt: str = "Password:") -> subprocess.CompletedProcess:
        """Run shell command with sudo, prompting for password if needed."""
        if SudoHelper.has_passwordless_sudo():
            return subprocess.run(
                ["sudo", "-n", "bash", "-c", command],
                capture_output=True, timeout=180, shell=True
            )
        
        env = os.environ.copy()
        askpass_script = '''#!/bin/bash
read -r -p "{} " PASS </dev/tty
echo "$PASS"
'''.format(prompt.replace('"', '\\"'))
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(askpass_script)
            askpass_path = f.name
        
        try:
            os.chmod(askpass_path, 0o755)
            env = os.environ.copy()
            env['SUDO_ASKPASS'] = askpass_path
            return subprocess.run(
                ["sudo", "-A", "bash", "-c", command],
                capture_output=True, timeout=180, shell=True, env=env
            )
        finally:
            try:
                os.unlink(askpass_path)
            except Exception:
                pass


class InstallerInterface(ABC):
    """Abstract base class for platform-specific installers."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Platform identifier."""
        ...

    @abstractmethod
    def detect_platform(self) -> Dict:
        """Return platform detection info."""
        ...

    @abstractmethod
    def get_required_dependencies(self) -> List[Dependency]:
        """Return list of all required dependencies for this platform."""
        ...

    @abstractmethod
    def check_dependencies(self) -> List[Dependency]:
        """Check which dependencies are installed, return with status."""
        ...

    @abstractmethod
    def install_dependency(self, dep: Dependency) -> bool:
        """Install a single dependency. Return True on success."""
        ...

    @abstractmethod
    def get_package_manager(self) -> str:
        """Return package manager name."""
        ...

    def supports_auto_install(self) -> bool:
        """Whether this platform supports automatic installation."""
        return True
    
    def needs_admin_for_system_packages(self) -> bool:
        """Whether system packages require admin/root."""
        return True

    def create_install_plan(self) -> InstallPlan:
        """Create an installation plan for missing dependencies."""
        deps = self.check_dependencies()
        missing = [d for d in deps if d.status == DepStatus.MISSING and d.required]
        optional_missing = [d for d in deps if d.status == DepStatus.MISSING and not d.required]

        plan = InstallPlan(
            dependencies=missing + optional_missing,
            package_manager=self.get_package_manager(),
            needs_admin=any(d.dep_type == DepType.SYSTEM for d in missing),
        )
        return plan


class WindowsAdminHelper:
    """Helper for Windows admin operations."""
    
    @staticmethod
    def is_admin() -> bool:
        """Check if running as admin."""
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False
    
    @staticmethod
    def run_as_admin(command: List[str]) -> subprocess.CompletedProcess:
        """Run command elevated via UAC."""
        import ctypes
        from ctypes import wintypes
        
        shell32 = ctypes.windll.shell32
        # ShellExecuteEx with runas verb
        sei = ctypes.c_void_p()
        # Use shell32.ShellExecuteW with "runas" verb
        # For Python subprocess, we can use runas verb via shell
        return subprocess.run(
            ["powershell", "-Command", f"Start-Process {' '.join(command)} -Verb RunAs -Wait"],
            capture_output=True, timeout=180
        )
    
    @staticmethod
    def run_admin_shell(command: str) -> subprocess.CompletedProcess:
        """Run shell command elevated via UAC."""
        return subprocess.run(
            ["powershell", "-Command", f"Start-Process powershell -ArgumentList '-Command', '{command}' -Verb RunAs -Wait"],
            capture_output=True, timeout=180
        )


class MacOSSudoHelper:
    """Helper for macOS sudo operations."""
    
    @staticmethod
    def has_passwordless_sudo() -> bool:
        try:
            result = subprocess.run(
                ["sudo", "-n", "true"],
                capture_output=True, timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False
    
    @staticmethod
    def run_with_sudo(command: List[str], prompt: str = "Password:") -> subprocess.CompletedProcess:
        """Run command with sudo, prompting for password if needed."""
        if MacOSSudoHelper.has_passwordless_sudo():
            return subprocess.run(
                ["sudo", "-n"] + command,
                capture_output=True, timeout=180
            )
        
        # On macOS, we can use osascript to prompt for password
        script = f'''
        do shell script "{' '.join(command)}" with administrator privileges
        '''
        return subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=180
        )
    
    @staticmethod
    def run_sudo_shell(command: str) -> subprocess.CompletedProcess:
        """Run shell command with sudo, prompting for password if needed."""
        if MacOSSudoHelper.has_passwordless_sudo():
            return subprocess.run(
                ["sudo", "-n", "bash", "-c", command],
                capture_output=True, timeout=180, shell=True
            )
        
        script = f'''
        do shell script "{command}" with administrator privileges
        '''
        return subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=180
        )