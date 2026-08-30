"""Persistent run store: content-addressed artifacts, append-only event log,
canonical-state pointer, and run manifest.

Layout of one run directory:
    manifest.json     run config, environment, pinned versions, final summary
    events.jsonl      append-only runtime event log (seq, type, ts, payload)
    canonical.json    pointer to the current accepted artifact
    artifacts/<sha256>.py   immutable content-addressed artifact bytes
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator

from .model import content_hash


class StoreIntegrityError(RuntimeError):
    pass


class RunStore:
    def __init__(self, root: Path):
        # absolute: artifact paths cross the sandbox boundary, which runs in its own cwd
        self.root = Path(root).resolve()
        self.artifacts_dir = self.root / "artifacts"
        self.events_path = self.root / "events.jsonl"
        self.canonical_path = self.root / "canonical.json"
        self.manifest_path = self.root / "manifest.json"
        self._seq = self._last_seq() + 1

    @staticmethod
    def create(root: Path) -> "RunStore":
        root = Path(root)
        if root.exists():
            raise FileExistsError(f"run directory already exists: {root}")
        (root / "artifacts").mkdir(parents=True)
        return RunStore(root)

    @staticmethod
    def open(root: Path) -> "RunStore":
        root = Path(root)
        if not (root / "events.jsonl").exists():
            raise FileNotFoundError(f"not a run directory (no events.jsonl): {root}")
        return RunStore(root)

    # -- artifacts ---------------------------------------------------------

    def put_artifact(self, source: str) -> str:
        digest = content_hash(source)
        path = self.artifacts_dir / f"{digest}.py"
        if not path.exists():
            path.write_text(source, encoding="utf-8")
        return digest

    def artifact_path(self, digest: str) -> Path:
        return self.artifacts_dir / f"{digest}.py"

    def get_artifact(self, digest: str) -> str:
        source = self.artifact_path(digest).read_text(encoding="utf-8")
        if content_hash(source) != digest:
            raise StoreIntegrityError(f"artifact {digest} content does not match its hash")
        return source

    # -- events ------------------------------------------------------------

    def append_event(self, event_type: str, **payload: Any) -> dict[str, Any]:
        record = {"seq": self._seq, "type": event_type, "ts": time.time(), **payload}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        self._seq += 1
        return record

    def events(self, event_type: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self._iter_events() if event_type is None or e["type"] == event_type]

    def _iter_events(self) -> Iterator[dict[str, Any]]:
        if not self.events_path.exists():
            return
        with self.events_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def _last_seq(self) -> int:
        last = 0
        for event in self._iter_events():
            last = max(last, int(event["seq"]))
        return last

    # -- canonical pointer -------------------------------------------------

    def set_canonical(self, digest: str, generation: int, score: float) -> None:
        self.canonical_path.write_text(
            json.dumps(
                {"artifact_hash": digest, "generation": generation, "score": score},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def canonical(self) -> dict[str, Any] | None:
        if not self.canonical_path.exists():
            return None
        return json.loads(self.canonical_path.read_text(encoding="utf-8"))

    # -- derived views -----------------------------------------------------

    def failures(self) -> list[dict[str, Any]]:
        return self.events("rejected")

    def lineage_edges(self) -> list[dict[str, Any]]:
        return [
            {
                "parent_hash": e["parent_hash"],
                "child_hash": e["artifact_hash"],
                "generation": e["generation"],
                "episode": e["episode"],
                "mutation": e.get("mutation"),
                "score": e["score"],
            }
            for e in self.events("promoted")
        ]

    # -- manifest ----------------------------------------------------------

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))
