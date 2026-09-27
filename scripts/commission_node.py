#!/usr/bin/env python3
"""Check whether this machine is ready to take production work, and say what is not.

Read-only: it inspects, it never changes the machine. Run it on the Mac Studio
the day it arrives, fix whatever it names, run it again. Policy lives in
`stigdev.node`; this file is only the macOS-specific measurement half.

    python3 scripts/commission_node.py --profile studio-m5-ultra
    python3 scripts/commission_node.py --profile studio-m5-ultra --json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stigdev.node import (  # noqa: E402
    PROFILES,
    RESOURCE_CLASSES,
    Allocation,
    HostFacts,
    admit,
    commissioning_gate,
)

CACHE_VOLUME_ENV = "STIGDEV_CACHE_VOLUME"
ARCHIVE_VOLUME_ENV = "STIGDEV_ARCHIVE_VOLUME"
BACKUP_TARGET_ENV = "STIGDEV_BACKUP_TARGET"


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def memory_pressure() -> str:
    """Read the `System-wide memory free percentage` line; unknown reads as yellow."""
    for line in _run("memory_pressure").splitlines():
        low = line.lower()
        if "percentage" in low and "free" in low:
            digits = "".join(c if c.isdigit() else " " for c in line).split()
            if digits:
                free = int(digits[-1])
                return "green" if free >= 20 else "yellow" if free >= 10 else "red"
    return "yellow"  # could not measure: do not report a calm machine on a guess


def _swap_used_mb() -> float:
    """Swap bytes currently in use, in MB."""
    out = _run("sysctl", "-n", "vm.swapusage")
    parts = out.replace("=", " ").split()
    for i, token in enumerate(parts):
        if token == "used" and i + 1 < len(parts):
            value = parts[i + 1]
            try:
                return float(value.rstrip("MG")) * (1024 if value.endswith("G") else 1)
            except ValueError:
                return 0.0
    return 0.0


def swap_growth_mb_per_min(sample_seconds: float = 5.0) -> float:
    """Growth rate, not the standing total.

    A machine that swapped hours ago and settled is fine; one that is swapping
    *now* is not. Measuring the total instead of the rate was a real bug here:
    it refused every resource class on a perfectly healthy laptop.
    """
    first = _swap_used_mb()
    time.sleep(sample_seconds)
    delta = _swap_used_mb() - first
    return round(max(delta, 0.0) * (60.0 / sample_seconds), 2)


def total_memory_gb() -> float:
    out = _run("sysctl", "-n", "hw.memsize")
    return round(int(out) / 1024**3, 1) if out.isdigit() else 0.0


def thermal_throttled() -> bool:
    out = _run("pmset", "-g", "therm")
    return "CPU_Speed_Limit = 100" not in out and "CPU_Speed_Limit" in out


def filevault_on() -> bool:
    return "FileVault is On" in _run("fdesetup", "status")


def no_public_remote_access() -> bool:
    """Remote Login and Screen Sharing must not be listening on all interfaces."""
    ssh_off = "Remote Login: Off" in _run("systemsetup", "-getremotelogin")
    listening = _run("sh", "-c", "netstat -an -p tcp 2>/dev/null | grep LISTEN || true")
    exposed = any(
        line.split()[3].startswith(("*.", "0.0.0.0.")) and line.split()[3].rsplit(".", 1)[-1] in ("22", "5900")
        for line in listening.splitlines()
        if len(line.split()) > 3
    )
    return ssh_off or not exposed


def time_synchronised() -> bool | None:
    """None when the answer needs sudo — unknown must not read as confirmed."""
    out = _run("systemsetup", "-getusingnetworktime")
    if "administrator" in out.lower() or not out:
        return None
    return "Network Time: On" in out


def agent_user_is_not_admin() -> bool | None:
    """The 24/7 service account must not be in the admin group."""
    user = os.environ.get("USER", "")
    members = _run("dscl", ".", "-read", "/Groups/admin", "GroupMembership")
    if not user or not members:
        return None
    return user not in members.split()


def volume_present(env_var: str) -> bool:
    path = os.environ.get(env_var)
    return bool(path) and Path(path).is_dir()


def free_disk_gb(path: str = "/") -> float:
    return round(shutil.disk_usage(path).free / 1024**3, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="studio-m5-ultra", choices=sorted(PROFILES))
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    facts = HostFacts(
        memory_pressure=memory_pressure(),
        swap_growth_mb_per_min=swap_growth_mb_per_min(),
        free_disk_gb=free_disk_gb(),
        thermal_throttled=thermal_throttled(),
    )
    checks = {
        "filevault": filevault_on(),
        "no_public_remote_access": no_public_remote_access(),
        "backup_target": volume_present(BACKUP_TARGET_ENV),
        "external_cache_volume": volume_present(CACHE_VOLUME_ENV),
        "archive_volume": volume_present(ARCHIVE_VOLUME_ENV),
        "time_synchronised": time_synchronised(),
        "agent_user_is_not_admin": agent_user_is_not_admin(),
    }
    # An unknown answer is not a pass. Fold None to False for the gate, but keep
    # the distinction in the report so the operator knows to re-run with sudo.
    decision = commissioning_gate(profile, facts, checks={k: bool(v) for k, v in checks.items()})
    unknown = sorted(k for k, v in checks.items() if v is None)
    measured = total_memory_gb()
    admissions = {
        name: admit(profile, Allocation(), name, facts).passed for name in sorted(RESOURCE_CLASSES)
    }
    report = {
        "host": socket.gethostname(),
        "profile": profile.node_id,
        "declared_memory_gb": profile.total_memory_gb,
        "measured_memory_gb": measured,
        "facts": facts.to_dict(),
        "checks": checks,
        "admits_when_idle": admissions,
        "unverifiable_without_sudo": unknown,
        "ready": decision.passed,
        "blockers": list(decision.reasons),
    }
    if measured and abs(measured - profile.total_memory_gb) > 4:
        report["blockers"].append(
            f"measured {measured} GB but profile {profile.node_id} declares "
            f"{profile.total_memory_gb} GB — wrong profile for this machine"
        )
        report["ready"] = False

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"host      {report['host']}  profile {profile.node_id}")
        print(f"memory    {measured} GB measured, {profile.usable_memory_gb} GB usable after reserve")
        print(f"pressure  {facts.memory_pressure}   free disk {facts.free_disk_gb} GB")
        print()
        for name, ok in sorted(checks.items()):
            mark = "ok" if ok else "??" if ok is None else "--"
            suffix = "  (needs sudo to verify)" if ok is None else ""
            print(f"  [{mark}] {name}{suffix}")
        print()
        for name, ok in admissions.items():
            print(f"  [{'ok' if ok else '--'}] admits {name} when idle")
        print()
        if report["ready"]:
            print("READY — this node may take production work.")
        else:
            print("NOT READY:")
            for reason in report["blockers"]:
                print(f"  - {reason}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
