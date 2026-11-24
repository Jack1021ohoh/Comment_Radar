"""Logging and run records.

Everything logs to the "radar" logger: stderr always (Cloud Run sends it to Cloud Logging), and locally
also logs/radar.log. Set LOG_FILE= (empty) to turn the file off.

Every analysis saves a JSON record to logs/runs/ (RUNS_DIR; off on Cloud Run), however it ends, so runs
can be compared when tuning prompts and thresholds.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def setup() -> logging.Logger:
    log = logging.getLogger("radar")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    path = os.environ.get("LOG_FILE", "" if os.environ.get("K_SERVICE") else str(ROOT / "logs" / "radar.log"))
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    return log


def save_run(record: dict) -> Path | None:
    """Write one run's record. Never raises: a run mustn't fail because its record couldn't be saved."""
    default = "" if os.environ.get("K_SERVICE") else str(ROOT / "logs" / "runs")
    directory = os.environ.get("RUNS_DIR", default)
    if not directory:
        return None
    try:
        path = Path(directory) / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{record['run_id'][:8]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        return path
    except Exception:
        logging.getLogger("radar").exception("couldn't save the run record")
        return None
