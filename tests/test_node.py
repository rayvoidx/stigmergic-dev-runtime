"""Offline tests for node profiles and Metal admission (ADR 0012)."""

import pytest

from stigdev.node import (
    MOBILE_M4,
    PROFILES,
    RESOURCE_CLASSES,
    STUDIO_M5_ULTRA,
    Allocation,
    HostFacts,
    NodeError,
    NodeProfile,
    ResourceClass,
    admit,
    commissioning_gate,
)
from stigdev.portfolio import GateDecision

READY = {
    "filevault": True,
    "no_public_remote_access": True,
    "backup_target": True,
    "external_cache_volume": True,
    "archive_volume": True,
    "time_synchronised": True,
    "agent_user_is_not_admin": True,
}
CALM = HostFacts(memory_pressure="green", swap_growth_mb_per_min=0.0, free_disk_gb=500.0)


@pytest.mark.parametrize("record", [MOBILE_M4, RESOURCE_CLASSES["text_coder"], CALM])
def test_records_round_trip_through_dict(record):
    assert type(record).from_dict(record.to_dict()) == record


def test_both_shipped_profiles_are_registered_and_reserve_real_memory():
    assert set(PROFILES) == {"mobile-m4", "studio-m5-ultra"}
    assert MOBILE_M4.usable_memory_gb == 16
    assert STUDIO_M5_ULTRA.usable_memory_gb == 76


def test_the_laptop_cannot_host_the_big_local_models():
    """24 GB minus an 8 GB reserve genuinely does not fit a 28 GB writer."""
    assert not MOBILE_M4.can_ever_run(RESOURCE_CLASSES["text_coder"])
    assert not MOBILE_M4.can_ever_run(RESOURCE_CLASSES["video_heavy"])
    assert MOBILE_M4.can_ever_run(RESOURCE_CLASSES["text_small"])
    assert all(STUDIO_M5_ULTRA.can_ever_run(c) for c in RESOURCE_CLASSES.values())


def test_an_idle_studio_admits_every_class():
    for name in RESOURCE_CLASSES:
        assert admit(STUDIO_M5_ULTRA, Allocation(), name, CALM).passed, name


def test_admission_reports_every_unmet_condition_at_once():
    decision = admit(MOBILE_M4, Allocation(), "video_heavy", CALM)
    assert decision == GateDecision(
        "node-admission/v1",
        False,
        (
            "video_heavy never fits on mobile-m4",
            "metal slots 4 over the 1 limit",
            "memory 72 GB over the 16 GB budget",
        ),
    )


def test_memory_budget_is_enforced_against_what_is_already_leased():
    two = Allocation(("vision", "vision"))  # 60 GB of the 76 GB budget
    assert "memory 90 GB over the 76 GB budget" in admit(STUDIO_M5_ULTRA, two, "vision", CALM).reasons


def test_the_normal_cap_holds_steady_work_and_preemptible_work_rides_above_it():
    busy = Allocation(("vision", "vision"))  # 2.0 slots, exactly at the normal cap
    # another full-slot job would exceed the steady-state ceiling
    assert "metal slots 3 over the 2 limit" in admit(STUDIO_M5_ULTRA, busy, "vision", CALM).reasons
    # a preemptible 0.25-slot job may still start: it can be evicted under pressure
    assert admit(STUDIO_M5_ULTRA, busy, "text_small", CALM).passed
    # and an exclusive job is measured against the hard cap, but needs an idle node
    assert "video_heavy is exclusive and the node is busy" in admit(
        STUDIO_M5_ULTRA, busy, "video_heavy", CALM
    ).reasons


def test_an_exclusive_job_locks_the_node_in_both_directions():
    held = Allocation(("video_heavy",))
    assert "an exclusive job holds the node" in admit(STUDIO_M5_ULTRA, held, "text_small", CALM).reasons


def test_max_parallel_is_respected():
    one = Allocation(("image_final",))
    assert "image_final already at its parallel limit of 1" in admit(
        STUDIO_M5_ULTRA, one, "image_final", CALM
    ).reasons


def test_the_interactive_reserve_keeps_one_run_for_the_operator():
    full = Allocation(tuple("text_small" for _ in range(MOBILE_M4.max_logical_runs - 1)))
    assert "logical run limit 3 reached on mobile-m4" in admit(MOBILE_M4, full, "text_small", CALM).reasons
    # the operator's own request may use the reserved slot
    assert "logical run limit" not in " ".join(
        admit(MOBILE_M4, full, "text_small", CALM, interactive=True).reasons
    )


@pytest.mark.parametrize(
    "facts,fragment",
    [
        (HostFacts(memory_pressure="yellow"), "memory pressure is yellow"),
        (HostFacts(swap_growth_mb_per_min=100.0), "swap growing at 100 MB/min"),
        (HostFacts(thermal_throttled=True), "thermally throttled"),
    ],
)
def test_an_unhappy_host_stops_new_leases(facts, fragment):
    assert fragment in " ".join(admit(STUDIO_M5_ULTRA, Allocation(), "text_small", facts).reasons)


def test_commissioning_passes_only_when_every_check_is_confirmed():
    assert commissioning_gate(STUDIO_M5_ULTRA, CALM, checks=READY).passed
    for name in READY:
        missing = dict(READY, **{name: False})
        assert f"{name} not confirmed" in commissioning_gate(
            STUDIO_M5_ULTRA, CALM, checks=missing
        ).reasons


def test_commissioning_rejects_a_thin_disk_and_an_unknown_check():
    thin = commissioning_gate(STUDIO_M5_ULTRA, HostFacts(free_disk_gb=10.0), checks=READY)
    assert "free disk 10 GB below the 50 GB floor" in thin.reasons
    odd = commissioning_gate(STUDIO_M5_ULTRA, CALM, checks=dict(READY, vibes=True))
    assert "unknown commissioning check 'vibes'" in odd.reasons


def test_commissioning_refuses_a_node_too_small_for_the_writer():
    assert "mobile-m4 cannot host the writer alias" in commissioning_gate(
        MOBILE_M4, CALM, checks=READY
    ).reasons


@pytest.mark.parametrize(
    "build",
    [
        lambda: admit(STUDIO_M5_ULTRA, Allocation(), "mystery_class"),
        lambda: Allocation(("mystery_class",)),
        lambda: ResourceClass("", metal_slots=1),
        lambda: ResourceClass("x", metal_slots=-1),
        lambda: ResourceClass("x", max_parallel=0),
        lambda: NodeProfile("n", 24, 4, 1, 1, 3, 6, reserve_memory_gb=24),
        lambda: NodeProfile("n", 24, 4, 2, 1, 3, 6, reserve_memory_gb=8),
        lambda: NodeProfile("n", 24, 1, 1, 1, 3, 6, reserve_memory_gb=8, interactive_reserve_runs=1),
        lambda: HostFacts(memory_pressure="teal"),
        lambda: HostFacts(swap_growth_mb_per_min=-1.0),
    ],
)
def test_invalid_input_is_rejected(build):
    with pytest.raises(NodeError):
        build()
