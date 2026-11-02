"""Installer abstraction base class."""

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
    package_name: str = ""  # Actual package name for package manager
    version_check: str = ""  # Command to check version


@dataclass
class InstallPlan:
    dependencies: List[Dependency]
    package_manager: str
    needs_admin: bool = False
    estimated_time: int = 0  # seconds


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