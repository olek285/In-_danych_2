"""Run logging: console plus a daily log file in data/logs/."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from kyb.config import local_today

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_dir: Path | None = None, level: str | None = None) -> None:
    level_name = (level or os.environ.get("KYB_LOG_LEVEL", "INFO")).upper()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"kyb_{local_today().isoformat()}.log"
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level_name, format=LOG_FORMAT, handlers=handlers, force=True)
    # urllib3 logs every retry/connection at DEBUG; keep our own messages readable
    logging.getLogger("urllib3").setLevel(logging.WARNING)
