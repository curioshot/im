"""CLI commands package."""

from .install import app as install_app
from .doctor import app as doctor_app
from .config import app as config_app
from .update import app as update_app

__all__ = ["install_app", "doctor_app", "config_app", "update_app"]