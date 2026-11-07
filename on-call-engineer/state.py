"""De-duplication state for the alert poller (T7.1, issue #61).

The state file records one episode per alert label set. It is written with a
temporary file plus ``os.replace`` so a crash leaves either the previous file or
the new one, never a half-written one. A per-directory ``flock`` makes a second
poller exit without writing a duplicate packet.

The file is local runtime state (``on-call-engineer/.state/``) and is
gitignored. A corrupt file is reported as a structured log line and treated as
empty; it never raises into the poll loop.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

STATE_VERSION = 1
STATE_FILE_NAME = "state.json"
LOCK_FILE_NAME = "poller.lock"

LOGGER = logging.getLogger("stockroom.oncall.state")


def _log_event(level: int, event: str, **fields: Any) -> None:
    LOGGER.log(level, json.dumps({"event": event, **fields}, sort_keys=True))


def empty_state() -> dict[str, Any]:
    """The state a fresh or corrupt store starts from."""
    return {"version": STATE_VERSION, "episodes": {}}


def write_atomic(path: Path, payload: str) -> None:
    """Write ``payload`` to ``path`` through a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


class StateStore:
    """The de-duplication state file and the process lock beside it."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def state_file(self) -> Path:
        return self.directory / STATE_FILE_NAME

    @property
    def lock_file(self) -> Path:
        return self.directory / LOCK_FILE_NAME

    @contextmanager
    def locked(self) -> Iterator[bool]:
        """Hold the poller lock for the duration of the block.

        Yields ``False`` when another poller already holds it; the caller then
        exits without writing anything.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def load(self) -> dict[str, Any]:
        """Read the state; a corrupt or unreadable file becomes empty state."""
        try:
            raw = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty_state()
        except OSError as exc:
            _log_event(logging.ERROR, "state_corrupt", error=type(exc).__name__)
            return empty_state()

        try:
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError("state is not an object")
            if document.get("version") != STATE_VERSION:
                raise ValueError("unexpected state version")
            if not isinstance(document.get("episodes"), dict):
                raise ValueError("state has no episodes object")
        except ValueError as exc:
            _log_event(logging.ERROR, "state_corrupt", error=type(exc).__name__)
            return empty_state()

        return {"version": STATE_VERSION, "episodes": document["episodes"]}

    def save(self, state: dict[str, Any]) -> None:
        """Flush the state atomically."""
        write_atomic(
            self.state_file,
            json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        )
