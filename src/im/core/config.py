"""Configuration management."""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """Persistent configuration for im."""

    DEFAULT_CONFIG = {
        "interval": 1.0,
        "timeout": 1.5,
        "duration": 0,
        "no_speed": False,
        "root": False,
        "theme": "default",
    }

    def __init__(self):
        self.config_dir = self._get_config_dir()
        self.config_file = self.config_dir / "config.json"
        self._config = self.DEFAULT_CONFIG.copy()
        self.load()

    def _get_config_dir(self) -> Path:
        """Get platform-appropriate config directory."""
        if os.name == "nt":  # Windows
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return Path(base) / "im"

    def load(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                    self._config.update(loaded)
            except Exception:
                pass
        return self._config

    def save(self):
        """Save configuration to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, "w") as f:
                json.dump(self._config, f, indent=2)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        self._config[key] = value
        self.save()

    def update(self, values: Dict[str, Any]):
        self._config.update(values)
        self.save()

    def all(self) -> Dict[str, Any]:
        return self._config.copy()

    def reset(self):
        self._config = self.DEFAULT_CONFIG.copy()
        self.save()


# Global config instance
config = Config()