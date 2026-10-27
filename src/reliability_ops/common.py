"""Finite local operating contracts; no vendor credentials or implicit source authority."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from marketing_reliability.contracts import canonical, digest

OWNERS = {"advertising": ["campaigns", "paid_media"], "website": ["web"], "crm": ["crm"]}
LIMIT = 2_000_000


def hash_value(value):
    return digest(canonical(value).encode())


def now():
    return datetime.now(UTC).isoformat()


def save(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")


@contextmanager
def sqlite(path, readonly=False):
    path = Path(path).resolve()
    c = (
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        if readonly
        else sqlite3.connect(path, timeout=5)
    )
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()


@contextmanager
def single_writer(path):
    """A process-level controller lock, additional to DuckDB's own writer exclusion."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("a+b")
    try:
        # Windows mandatory byte locks can refuse this read before locking itself.
        f.seek(0)
        if not f.read(1):
            f.write(b"0")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise RuntimeError("another_controller_holds_the_writer_lock") from None
    try:
        yield
    finally:
        f.close()
