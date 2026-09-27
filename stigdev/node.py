"""Node profiles, resource classes, and Metal admission (ADR 0012).

Apple unified memory has no hardware partition like NVIDIA MIG, so a GPU-heavy
job cannot be fenced off by the driver. The substitute is a lease: a job
declares a resource class, and admission refuses it unless the node has the
slots, the memory headroom, and a calm machine to run it on.

Pure policy. Nothing here inspects a host or starts a process — the caller
measures :class:`HostFacts` and passes them in. ``scripts/commission_node.py``
is the macOS-specific half.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .portfolio import GateDecision

ADMISSION_GATE_ID = "node-admission/v1"
COMMISSION_GATE_ID = "node-commissioning/v1"
MEMORY_PRESSURE = ("green", "yellow", "red")
# macOS reports pressure long before it swaps hard; yellow is already a stop
# signal for *new* leases, never a reason to kill a running one.
ADMITTING_PRESSURE = ("green",)


class NodeError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NodeError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value: object, name: str) -> float:
    _require(_finite(value) and float(value) > 0, f"{name} must be a finite positive number")
    return float(value)


def _non_negative(value: object, name: str) -> float:
    _require(_finite(value) and float(value) >= 0, f"{name} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True)
class ResourceClass:
    """What one kind of job costs. `metal_slots` is fractional on purpose."""

    name: str
    metal_slots: float = 0.0
    memory_gb: float = 0.0
    cpu_slots: int = 0
    exclusive: bool = False
    preemptible: bool = False
    max_parallel: int | None = None

    def __post_init__(self) -> None:
        _require(bool(self.name.strip()), "resource class needs a name")
        _non_negative(self.metal_slots, "metal_slots")
        _non_negative(self.memory_gb, "memory_gb")
        _require(isinstance(self.cpu_slots, int) and self.cpu_slots >= 0, "cpu_slots must be >= 0")
        _require(
            self.max_parallel is None or (isinstance(self.max_parallel, int) and self.max_parallel >= 1),
            "max_parallel must be a positive integer or None",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ResourceClass":
        return ResourceClass(**raw)


# Blueprint §9.2. These are the first benchmark's safe ceilings, not measured
# numbers: lower them when a real model profile says so.
RESOURCE_CLASSES: dict[str, ResourceClass] = {
    c.name: c
    for c in (
        ResourceClass("text_small", metal_slots=0.25, memory_gb=10, preemptible=True),
        ResourceClass("text_coder", metal_slots=1.0, memory_gb=28),
        ResourceClass("vision", metal_slots=1.0, memory_gb=30),
        ResourceClass("image_final", metal_slots=1.0, memory_gb=40, max_parallel=1),
        ResourceClass("video_heavy", metal_slots=4.0, memory_gb=72, exclusive=True),
        ResourceClass("render_cpu", metal_slots=0.0, memory_gb=12, cpu_slots=4),
    )
}


@dataclass(frozen=True)
class NodeProfile:
    """One machine's ceilings. `hard_metal_slots` is the absolute cap; `normal` is the working cap."""

    node_id: str
    total_memory_gb: float
    max_logical_runs: int
    normal_metal_slots: float
    hard_metal_slots: float
    cpu_workers: int
    io_workers: int
    reserve_memory_gb: float
    interactive_reserve_runs: int = 1

    def __post_init__(self) -> None:
        _require(bool(self.node_id.strip()), "node_id must be a non-empty string")
        _positive(self.total_memory_gb, "total_memory_gb")
        _require(isinstance(self.max_logical_runs, int) and self.max_logical_runs >= 1,
                 "max_logical_runs must be >= 1")
        _positive(self.normal_metal_slots, "normal_metal_slots")
        _positive(self.hard_metal_slots, "hard_metal_slots")
        _require(self.hard_metal_slots >= self.normal_metal_slots,
                 "hard_metal_slots must be at least normal_metal_slots")
        _require(isinstance(self.cpu_workers, int) and self.cpu_workers >= 1, "cpu_workers must be >= 1")
        _require(isinstance(self.io_workers, int) and self.io_workers >= 1, "io_workers must be >= 1")
        _non_negative(self.reserve_memory_gb, "reserve_memory_gb")
        _require(self.reserve_memory_gb < self.total_memory_gb, "reserve leaves no usable memory")
        _require(
            isinstance(self.interactive_reserve_runs, int) and 0 <= self.interactive_reserve_runs < self.max_logical_runs,
            "interactive_reserve_runs must leave at least one run for background work",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "NodeProfile":
        return NodeProfile(**raw)

    @property
    def usable_memory_gb(self) -> float:
        return self.total_memory_gb - self.reserve_memory_gb

    def can_ever_run(self, klass: ResourceClass) -> bool:
        """Whether this node could admit the class on a completely idle machine."""
        return klass.memory_gb <= self.usable_memory_gb and klass.metal_slots <= self.hard_metal_slots


MOBILE_M4 = NodeProfile(
    node_id="mobile-m4",
    total_memory_gb=24,
    max_logical_runs=4,
    normal_metal_slots=1,
    hard_metal_slots=1,
    cpu_workers=3,
    io_workers=6,
    reserve_memory_gb=8,
)
STUDIO_M5_ULTRA = NodeProfile(
    node_id="studio-m5-ultra",
    total_memory_gb=96,
    max_logical_runs=24,
    normal_metal_slots=2,
    hard_metal_slots=4,
    cpu_workers=6,
    io_workers=12,
    reserve_memory_gb=20,
)
PROFILES: dict[str, NodeProfile] = {p.node_id: p for p in (MOBILE_M4, STUDIO_M5_ULTRA)}


@dataclass(frozen=True)
class HostFacts:
    """What the caller measured on the machine, just before deciding."""

    memory_pressure: str = "green"
    swap_growth_mb_per_min: float = 0.0
    free_disk_gb: float = 0.0
    thermal_throttled: bool = False

    def __post_init__(self) -> None:
        _require(self.memory_pressure in MEMORY_PRESSURE, f"unknown memory_pressure {self.memory_pressure!r}")
        _non_negative(self.swap_growth_mb_per_min, "swap_growth_mb_per_min")
        _non_negative(self.free_disk_gb, "free_disk_gb")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "HostFacts":
        return HostFacts(**raw)


MAX_SWAP_GROWTH_MB_PER_MIN = 64.0
MIN_FREE_DISK_GB = 50.0


@dataclass(frozen=True)
class Allocation:
    """Leases currently held on a node, by resource-class name."""

    classes: tuple[str, ...] = ()
    interactive_runs: int = 0

    def __post_init__(self) -> None:
        for name in self.classes:
            _require(name in RESOURCE_CLASSES, f"unknown resource class {name!r}")
        _require(isinstance(self.interactive_runs, int) and self.interactive_runs >= 0,
                 "interactive_runs must be >= 0")

    @property
    def held(self) -> tuple[ResourceClass, ...]:
        return tuple(RESOURCE_CLASSES[n] for n in self.classes)

    @property
    def metal_slots(self) -> float:
        return round(sum(c.metal_slots for c in self.held), 6)

    @property
    def memory_gb(self) -> float:
        return round(sum(c.memory_gb for c in self.held), 6)

    @property
    def cpu_slots(self) -> int:
        return sum(c.cpu_slots for c in self.held)

    def count_of(self, name: str) -> int:
        return sum(1 for n in self.classes if n == name)


def admit(
    profile: NodeProfile,
    allocation: Allocation,
    requested: str,
    facts: HostFacts = HostFacts(),
    *,
    interactive: bool = False,
) -> GateDecision:
    """Decide whether one more job of class `requested` may lease this node.

    Fails closed: every unmet condition is reported, and an unknown class raises
    rather than being waved through.
    """
    _require(requested in RESOURCE_CLASSES, f"unknown resource class {requested!r}")
    klass = RESOURCE_CLASSES[requested]
    reasons: list[str] = []

    if not profile.can_ever_run(klass):
        reasons.append(f"{requested} never fits on {profile.node_id}")

    runs = len(allocation.classes)
    ceiling = profile.max_logical_runs - (0 if interactive else profile.interactive_reserve_runs)
    if runs + 1 > ceiling:
        reasons.append(f"logical run limit {ceiling} reached on {profile.node_id}")

    # `normal` is the steady-state ceiling for work that must not be disturbed.
    # Preemptible and exclusive classes are measured against the hard ceiling:
    # the first can be evicted under pressure, the second holds the node alone.
    metal = allocation.metal_slots + klass.metal_slots
    cap = profile.hard_metal_slots if (klass.preemptible or klass.exclusive) else profile.normal_metal_slots
    if metal > cap:
        reasons.append(f"metal slots {metal:g} over the {cap:g} limit")

    memory = allocation.memory_gb + klass.memory_gb
    if memory > profile.usable_memory_gb:
        reasons.append(f"memory {memory:g} GB over the {profile.usable_memory_gb:g} GB budget")

    if allocation.cpu_slots + klass.cpu_slots > profile.cpu_workers:
        reasons.append(f"cpu slots over the {profile.cpu_workers} worker limit")

    if klass.exclusive and allocation.classes:
        reasons.append(f"{requested} is exclusive and the node is busy")
    if any(c.exclusive for c in allocation.held):
        reasons.append("an exclusive job holds the node")

    if klass.max_parallel is not None and allocation.count_of(requested) >= klass.max_parallel:
        reasons.append(f"{requested} already at its parallel limit of {klass.max_parallel}")

    if facts.memory_pressure not in ADMITTING_PRESSURE:
        reasons.append(f"memory pressure is {facts.memory_pressure}")
    if facts.swap_growth_mb_per_min > MAX_SWAP_GROWTH_MB_PER_MIN:
        reasons.append(f"swap growing at {facts.swap_growth_mb_per_min:g} MB/min")
    if facts.thermal_throttled:
        reasons.append("host is thermally throttled")

    return GateDecision(ADMISSION_GATE_ID, not reasons, tuple(reasons))


def commissioning_reasons(profile: NodeProfile, facts: HostFacts, *, checks: dict[str, bool]) -> tuple[str, ...]:
    """Everything that must hold before a node is allowed to take production work.

    `checks` carries the host answers the caller gathered: `filevault`,
    `no_public_remote_access`, `backup_target`, `external_cache_volume`,
    `archive_volume`, `time_synchronised`, `agent_user_is_not_admin`.
    """
    required = (
        "filevault",
        "no_public_remote_access",
        "backup_target",
        "external_cache_volume",
        "archive_volume",
        "time_synchronised",
        "agent_user_is_not_admin",
    )
    reasons = [f"{name} not confirmed" for name in required if not checks.get(name)]
    unknown = sorted(set(checks) - set(required))
    reasons.extend(f"unknown commissioning check {name!r}" for name in unknown)
    if facts.free_disk_gb < MIN_FREE_DISK_GB:
        reasons.append(f"free disk {facts.free_disk_gb:g} GB below the {MIN_FREE_DISK_GB:g} GB floor")
    if facts.memory_pressure != "green":
        reasons.append(f"memory pressure is {facts.memory_pressure} on an idle machine")
    if facts.thermal_throttled:
        reasons.append("host is thermally throttled")
    if not profile.can_ever_run(RESOURCE_CLASSES["text_coder"]):
        reasons.append(f"{profile.node_id} cannot host the writer alias")
    return tuple(reasons)


def commissioning_gate(profile: NodeProfile, facts: HostFacts, *, checks: dict[str, bool]) -> GateDecision:
    reasons = commissioning_reasons(profile, facts, checks=checks)
    return GateDecision(COMMISSION_GATE_ID, not reasons, reasons)
