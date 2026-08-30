"""Entry point executed inside the sandbox subprocess (python -I).

Reads a JSON payload {"entrypoint": str, "args": list} from stdin, imports the
artifact module from the path given as argv[1], calls the entrypoint, and
prints a JSON result envelope to stdout. Any exception is reported in the
envelope; the process itself always exits 0 so the parent distinguishes
"artifact failed" from "sandbox failed".
"""

from __future__ import annotations

import importlib.util
import json
import sys


def _run() -> dict:
    artifact_path = sys.argv[1]
    payload = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("stigdev_artifact", artifact_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load artifact from {artifact_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entrypoint = getattr(module, payload["entrypoint"])
    return {"ok": True, "result": entrypoint(*payload["args"])}


def main() -> None:
    try:
        envelope = _run()
    except BaseException as exc:  # report every artifact failure, never crash the envelope
        envelope = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    json.dump(envelope, sys.stdout)


if __name__ == "__main__":
    main()
