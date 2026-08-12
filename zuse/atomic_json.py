"""Crash-safe, reader-safe JSON writes.

A run's `orchestrator_state.json`, `params.json` and `lifecycle.json` are
written by the run worker while the backend serves `GET /runs/{id}` from the
same files. `Path.write_text` truncates before it writes, so a reader that
arrives mid-write observes zero bytes and fails to parse -- intermittently,
and more often the busier the run.

`os.replace` is atomic on POSIX and Windows, so a reader sees either the
previous complete file or the new one, never a partial one. This is a file
utility, not domain logic: it makes no decision about what any value means,
so the backend may use it without violating BACKEND_PLAN.md's separation.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, payload: Any, *, indent: int | None = 2) -> None:
    """Serialise `payload` to `path` atomically.

    The temp file is created in the destination's own directory so the
    replace never crosses a filesystem boundary (which would make it a
    non-atomic copy), and is removed if anything fails before the replace.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=indent, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
