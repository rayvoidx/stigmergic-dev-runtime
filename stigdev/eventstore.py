"""Durable event store v2 (ADR 0006): stdlib SQLite in WAL mode.

One database file per store root (``<root>/store.sqlite``). One write connection
per store is a deployment rule; SQLite serialises concurrent writers with
``BEGIN IMMEDIATE`` and ``busy_timeout`` as defense in depth.

Guarantees: append-only events with a v2 envelope, idempotent append by key,
compare-and-swap pointers, content-addressed blobs and trees with hash
verification on read, and all-or-nothing transactions. Redaction is a
forbidden-value check at the store boundary (defense in depth, not a secret
detector). This is not a distributed store and not a security boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .store import StoreIntegrityError

SCHEMA_VERSION = 2
_FILENAME = "store.sqlite"
_SYNCHRONOUS = ("NORMAL", "FULL")
_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE events (
    seq INTEGER PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    store_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    ts REAL NOT NULL,
    causation_id TEXT,
    correlation_id TEXT,
    idempotency_key TEXT,
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX events_idempotency ON events(store_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE TABLE pointers (name TEXT PRIMARY KEY, version INTEGER NOT NULL, value TEXT NOT NULL);
CREATE TABLE blobs (digest TEXT PRIMARY KEY, kind TEXT NOT NULL, content BLOB NOT NULL);
"""
_SELECT = (
    "SELECT seq, schema_version, store_id, run_id, event_id, type, ts, causation_id, "
    "correlation_id, idempotency_key, payload FROM events"
)


class RedactionError(ValueError):
    pass


class PointerConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    seq: int
    schema_version: int
    store_id: str
    run_id: str
    event_id: str
    type: str
    ts: float
    causation_id: str | None
    correlation_id: str | None
    idempotency_key: str | None
    payload: dict[str, Any]


def assert_public(value: Any, forbidden: tuple[str, ...] | list[str]) -> None:
    """Reject known transient values (instructions, env values, locators, logs).

    Values shorter than eight characters match whole strings only so that
    ``CI=1`` style values stay usable; longer values also match as substrings.
    Encoded or split secrets are not detected.
    """
    secrets = [s for s in forbidden if s]
    if not secrets:
        return
    if isinstance(value, str):
        if any(s == value or (len(s) >= 8 and s in value) for s in secrets):
            raise RedactionError("forbidden transient value in public data")
    elif isinstance(value, dict):
        for key, item in value.items():
            assert_public(key, secrets)
            assert_public(item, secrets)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_public(item, secrets)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_object(value: Any, what: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object")
    try:
        return _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} is not JSON: {exc}") from exc


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SqliteEventStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.path = self.root / _FILENAME
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._depth = 0
        meta = self.meta()
        if meta.get("schema_version") != str(SCHEMA_VERSION):
            raise StoreIntegrityError(f"unsupported store schema: {meta.get('schema_version')}")
        self.store_id = meta["store_id"]
        self._conn.execute(f"PRAGMA synchronous = {meta['synchronous']}")

    @classmethod
    def create(cls, root: Path, *, store_id: str, synchronous: str = "NORMAL") -> "SqliteEventStore":
        root = Path(root)
        if synchronous not in _SYNCHRONOUS:
            raise ValueError(f"synchronous must be one of {_SYNCHRONOUS}")
        if root.exists():
            raise FileExistsError(f"store root already exists: {root}")
        root.mkdir(parents=True)
        conn = sqlite3.connect(root / _FILENAME)
        with conn:
            conn.executescript(_SCHEMA)
            conn.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [
                    ("store_id", store_id),
                    ("schema_version", str(SCHEMA_VERSION)),
                    ("synchronous", synchronous),
                ],
            )
        conn.close()
        return cls(root)

    @classmethod
    def open(cls, root: Path) -> "SqliteEventStore":
        if not (Path(root) / _FILENAME).exists():
            raise FileNotFoundError(f"not a store root (no {_FILENAME}): {root}")
        return cls(root)

    def close(self) -> None:
        self._conn.close()

    def meta(self) -> dict[str, str]:
        return dict(self._conn.execute("SELECT key, value FROM meta").fetchall())

    # -- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """All-or-nothing scope; nested scopes join the outermost transaction."""
        if self._depth == 0:
            self._conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self._conn.execute("ROLLBACK")
            raise
        self._depth -= 1
        if self._depth == 0:
            self._conn.execute("COMMIT")

    # -- events ------------------------------------------------------------

    def append(
        self,
        type: str,
        payload: dict[str, Any],
        *,
        run_id: str,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        ts: float | None = None,
        forbidden: tuple[str, ...] | list[str] = (),
    ) -> Event:
        """Append one event; a repeated idempotency key returns the stored event."""
        if not type or not isinstance(type, str):
            raise ValueError("event type must be a non-empty string")
        encoded = _json_object(payload, "payload")
        assert_public(payload, forbidden)
        with self.transaction():
            if idempotency_key is not None:
                row = self._conn.execute(
                    _SELECT + " WHERE store_id = ? AND idempotency_key = ?",
                    (self.store_id, idempotency_key),
                ).fetchone()
                if row is not None:
                    return self._event(row)
            if causation_id is not None and self.event(causation_id) is None:
                raise StoreIntegrityError(f"causation event not found: {causation_id}")
            cursor = self._conn.execute(
                "INSERT INTO events (schema_version, store_id, run_id, event_id, type, ts, "
                "causation_id, correlation_id, idempotency_key, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    SCHEMA_VERSION,
                    self.store_id,
                    run_id,
                    os.urandom(16).hex(),
                    type,
                    float(time.time() if ts is None else ts),
                    causation_id,
                    correlation_id,
                    idempotency_key,
                    encoded,
                ),
            )
            row = self._conn.execute(_SELECT + " WHERE seq = ?", (cursor.lastrowid,)).fetchone()
        return self._event(row)

    def by_idempotency_key(self, key: str) -> Event | None:
        row = self._conn.execute(
            _SELECT + " WHERE store_id = ? AND idempotency_key = ?", (self.store_id, key)
        ).fetchone()
        return None if row is None else self._event(row)

    def event(self, event_id: str) -> Event | None:
        row = self._conn.execute(_SELECT + " WHERE event_id = ?", (event_id,)).fetchone()
        return None if row is None else self._event(row)

    def events(
        self, *, type: str | None = None, run_id: str | None = None, after_seq: int = 0
    ) -> list[Event]:
        clauses, params = ["seq > ?"], [after_seq]
        if type is not None:
            clauses.append("type = ?")
            params.append(type)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        rows = self._conn.execute(
            _SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY seq", params
        ).fetchall()
        return [self._event(row) for row in rows]

    @staticmethod
    def _event(row: tuple[Any, ...]) -> Event:
        return Event(*row[:10], payload=json.loads(row[10]))

    # -- blobs and trees ---------------------------------------------------

    def put_blob(
        self, data: bytes, *, kind: str = "blob", forbidden: tuple[str, ...] | list[str] = ()
    ) -> str:
        if not isinstance(data, bytes):
            raise ValueError("blob content must be bytes")
        assert_public(data.decode("utf-8", "replace"), forbidden)
        digest = _digest(data)
        with self.transaction():
            self._conn.execute(
                "INSERT OR IGNORE INTO blobs (digest, kind, content) VALUES (?, ?, ?)",
                (digest, kind, data),
            )
        return digest

    def get_blob(self, digest: str) -> bytes:
        return self._blob(digest)[1]

    def _blob(self, digest: str) -> tuple[str, bytes]:
        row = self._conn.execute("SELECT kind, content FROM blobs WHERE digest = ?", (digest,)).fetchone()
        if row is None:
            raise KeyError(digest)
        kind, content = row
        if _digest(content) != digest:
            raise StoreIntegrityError(f"blob {digest} content does not match its hash")
        return kind, bytes(content)

    def blobs(self, *, kind: str | None = None) -> list[tuple[str, bytes]]:
        rows = self._conn.execute(
            "SELECT digest FROM blobs" + ("" if kind is None else " WHERE kind = ?") + " ORDER BY digest",
            () if kind is None else (kind,),
        ).fetchall()
        return [(digest, self.get_blob(digest)) for (digest,) in rows]

    def put_tree(self, entries: dict[str, str]) -> str:
        """Store a content-addressed tree: sorted path -> blob digest mapping."""
        for path, digest in entries.items():
            if not path or path.startswith("/") or ".." in path.split("/"):
                raise ValueError(f"invalid tree path: {path!r}")
            if self._conn.execute("SELECT 1 FROM blobs WHERE digest = ?", (digest,)).fetchone() is None:
                raise StoreIntegrityError(f"tree references unknown blob: {digest}")
        return self.put_blob(_canonical_json(entries).encode("utf-8"), kind="tree")

    def get_tree(self, digest: str) -> dict[str, str]:
        kind, content = self._blob(digest)
        if kind != "tree":
            raise StoreIntegrityError(f"blob {digest} is not a tree")
        return json.loads(content)

    # -- pointers ----------------------------------------------------------

    def pointer(self, name: str) -> tuple[int, dict[str, Any]] | None:
        row = self._conn.execute("SELECT version, value FROM pointers WHERE name = ?", (name,)).fetchone()
        return None if row is None else (int(row[0]), json.loads(row[1]))

    def set_pointer(self, name: str, value: dict[str, Any], *, expected_version: int) -> int:
        """Compare-and-swap; version 0 means the pointer must not exist yet."""
        encoded = _json_object(value, "pointer value")
        with self.transaction():
            current = self.pointer(name)
            version = 0 if current is None else current[0]
            if version != expected_version:
                raise PointerConflict(f"pointer {name}: expected version {expected_version}, found {version}")
            if current is None:
                self._conn.execute("INSERT INTO pointers VALUES (?, 1, ?)", (name, encoded))
            else:
                updated = self._conn.execute(
                    "UPDATE pointers SET version = version + 1, value = ? WHERE name = ? AND version = ?",
                    (encoded, name, version),
                ).rowcount
                if updated != 1:
                    raise PointerConflict(f"pointer {name}: concurrent update")
        return version + 1
