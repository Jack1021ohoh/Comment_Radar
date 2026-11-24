"""The radar's memory of fetched threads, keyed by thread id ("youtube:<video id>").

In memory, in the MCP server's process, with an optional copy on disk (CACHE_DIR, default
data/cache locally and off on Cloud Run) so a restart doesn't spend quota again.

YouTube's developer policies say API data must be refreshed or deleted within 30 days, so a
thread older than MAX_AGE is fetched again rather than served.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger("radar")

ROOT = Path(__file__).resolve().parent.parent
MAX_AGE = dt.timedelta(days=30)

_threads: dict[str, dict] = {}
_lock = threading.Lock()


def cache_dir() -> Path | None:
    default = "" if os.environ.get("K_SERVICE") else str(ROOT / "data" / "cache")
    path = os.environ.get("CACHE_DIR", default)
    return Path(path) if path else None


def _fresh(thread: dict) -> bool:
    fetched = dt.datetime.fromisoformat(thread["fetched_at"])
    return dt.datetime.now(dt.timezone.utc) - fetched < MAX_AGE


def _file(thread_id: str) -> Path | None:
    d = cache_dir()
    return d / f"{thread_id.replace(':', '_')}.json" if d else None


def get(thread_id: str) -> dict | None:
    with _lock:
        thread = _threads.get(thread_id)
    if thread and _fresh(thread):
        return thread
    path = _file(thread_id)
    if path and path.exists():
        try:
            thread = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("unreadable cache file %s", path)
            return None
        if _fresh(thread):
            with _lock:
                _threads[thread_id] = thread
            return thread
        path.unlink(missing_ok=True)  # past 30 days: delete, don't keep
    return None


def put(thread: dict) -> None:
    """Store a thread. Analysis results (sentiment, groups) are added to it later with `update`."""
    with _lock:
        _threads[thread["thread_id"]] = thread
    _save(thread)


def update(thread_id: str, **fields) -> dict:
    thread = get(thread_id)
    if thread is None:
        raise KeyError(thread_id)
    thread.update(fields)
    _save(thread)
    return thread


def _save(thread: dict) -> None:
    path = _file(thread["thread_id"])
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(thread, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("couldn't cache %s", thread["thread_id"])
