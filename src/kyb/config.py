"""Project configuration: config/settings.yaml plus optional .env overrides.

Paths in settings.yaml are resolved relative to the project root, so commands
work no matter which directory they are started from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Polish registers and the VAT White List quota work on Polish local time
# (the VAT block lasts "until midnight"), so partitions use the same calendar.
LOCAL_TZ = ZoneInfo("Europe/Warsaw")


def local_today() -> date:
    """Current date in Europe/Warsaw, used for ingest_date partitions and quotas."""
    return datetime.now(LOCAL_TZ).date()


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file; real environment variables win."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any]
    project_root: Path
    data_dir: Path

    def layer_dir(self, name: str) -> Path:
        """Directory of a data layer or helper area (bronze, silver, state, ...)."""
        return self.data_dir / self.raw["paths"][name]

    @property
    def bronze_dir(self) -> Path:
        return self.layer_dir("bronze")

    @property
    def state_dir(self) -> Path:
        return self.layer_dir("state")

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def watchlist_path(self) -> Path:
        return self.project_root / self.raw["paths"]["watchlist"]

    @property
    def http(self) -> dict[str, Any]:
        return self.raw["http"]

    def source(self, name: str) -> dict[str, Any]:
        return self.raw["sources"][name]


def load_settings(settings_path: Path | None = None) -> Settings:
    root = Path(os.environ.get("KYB_PROJECT_ROOT", PROJECT_ROOT)).resolve()
    load_dotenv(root / ".env")
    path = Path(settings_path or os.environ.get("KYB_SETTINGS", root / "config" / "settings.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    data_dir = Path(os.environ.get("KYB_DATA_DIR") or raw["paths"]["data_dir"])
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    return Settings(raw=raw, project_root=root, data_dir=data_dir)
