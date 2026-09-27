"""Non-destructive bridge between v1 run directories and the v2 event store (ADR 0006).

``import_run`` copies a v1 run (events.jsonl, artifacts, canonical pointer,
manifest) into a v2 store without modifying the source; re-importing is a
no-op. ``export_run`` writes a v1-layout directory back so ``stigdev replay``
can verify the imported evidence. Export assumes one v1 run per store: all
``py`` blobs are exported together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .eventstore import PointerConflict, SqliteEventStore
from .model import content_hash
from .store import RunStore, StoreIntegrityError

_ENVELOPE = ("seq", "type", "ts")


def import_run(run_dir: Path, store: SqliteEventStore, *, run_id: str | None = None) -> int:
    """Import a v1 run directory into ``store`` atomically; returns the event count."""
    v1 = RunStore.open(Path(run_dir))
    manifest = v1.manifest() if v1.manifest_path.exists() else None
    run_id = run_id or _run_id(manifest, Path(run_dir).name)
    records = v1.events()
    with store.transaction():
        for path in sorted(v1.artifacts_dir.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if content_hash(source) != path.stem:
                raise StoreIntegrityError(f"artifact {path.name} content does not match its hash")
            if store.put_blob(source.encode("utf-8"), kind="py") != path.stem:
                raise StoreIntegrityError(f"artifact {path.name}: v1 hash scheme differs from blob digest")
        event_ids: dict[int, str] = {}
        for record in records:
            payload = {
                "v1_seq": record["seq"],
                **{key: value for key, value in record.items() if key not in _ENVELOPE},
            }
            caused_by = record.get("caused_by_seq")
            event = store.append(
                record["type"],
                payload,
                run_id=run_id,
                ts=record["ts"],
                causation_id=event_ids.get(caused_by) if isinstance(caused_by, int) else None,
                correlation_id=record.get("attempt_id"),
                idempotency_key=f"v1:{run_id}:{record['seq']}",
            )
            event_ids[record["seq"]] = event.event_id
        _pointer(store, "canonical", v1.canonical())
        _pointer(store, "manifest", manifest)
    return len(records)


def export_run(store: SqliteEventStore, run_id: str, dest: Path) -> Path:
    """Write the run back in v1 layout (events.jsonl, artifacts/, canonical, manifest)."""
    events = store.events(run_id=run_id)
    if not events:
        raise KeyError(run_id)
    v1 = RunStore.create(Path(dest))
    with v1.events_path.open("w", encoding="utf-8") as fh:
        for event in events:
            payload = dict(event.payload)
            record = {"seq": payload.pop("v1_seq", event.seq), "type": event.type, "ts": event.ts, **payload}
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    for _, content in store.blobs(kind="py"):
        v1.put_artifact(content.decode("utf-8"))
    canonical = store.pointer("canonical")
    if canonical is not None:
        value = canonical[1]
        v1.set_canonical(value["artifact_hash"], value["generation"], value["score"])
    manifest = store.pointer("manifest")
    if manifest is not None:
        v1.write_manifest(manifest[1])
    return v1.root


def _run_id(manifest: dict[str, Any] | None, fallback: str) -> str:
    if manifest:
        return manifest.get("run_id") or manifest.get("config", {}).get("run_id") or fallback
    return fallback


def _pointer(store: SqliteEventStore, name: str, value: dict[str, Any] | None) -> None:
    if value is None:
        return
    current = store.pointer(name)
    if current is None:
        store.set_pointer(name, value, expected_version=0)
    elif current[1] != value:
        raise PointerConflict(f"pointer {name} already holds a different value")
