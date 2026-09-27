"""Offline tests for policy incidents and the K0-K4 kill switch (ADR 0011)."""

import pytest

from stigdev.incident import (
    KILL_LEVELS,
    KILL_SCOPE,
    IncidentError,
    PolicyIncident,
    PortfolioGraph,
    action_allowed,
    escalate,
    halted_channels,
)

NOW = "2026-09-20T00:00:00+00:00"
GRAPH = PortfolioGraph(
    channel_family={"synthetic-a": "archive-tales", "synthetic-b": "archive-tales",
                    "synthetic-c": "signal-explainers"},
    video_channel={"synthetic-vid-1": "synthetic-a"},
)


def incident(**kw) -> PolicyIncident:
    base = dict(incident_id="synthetic-incident-01", scope="channel", subject_id="synthetic-a",
                severity="medium", detected_at=NOW)
    base.update(kw)
    return PolicyIncident(**base)


def test_kill_levels_and_scopes_are_the_documented_ladder():
    assert KILL_LEVELS == ("K0", "K1", "K2", "K3", "K4")
    assert KILL_SCOPE == {"K0": "video", "K1": "channel", "K2": "format_family",
                          "K3": "portfolio", "K4": "credential"}


def test_round_trip_through_dict():
    i = incident(kill_level="K2", severity="high")
    assert PolicyIncident.from_dict(i.to_dict()) == i


def test_severity_sets_a_kill_floor_that_cannot_be_undercut():
    assert incident(severity="low").effective_kill_level == "K0"
    assert incident(severity="critical").effective_kill_level == "K3"
    with pytest.raises(IncidentError, match="below the floor"):
        incident(severity="critical", kill_level="K1")


def test_k0_halts_only_the_video_owning_channel():
    i = incident(scope="video", subject_id="synthetic-vid-1", severity="low")
    assert halted_channels(i, GRAPH) == frozenset({"synthetic-a"})


def test_k2_halts_the_whole_format_family():
    i = incident(scope="format_family", subject_id="archive-tales", severity="high")
    assert halted_channels(i, GRAPH) == frozenset({"synthetic-a", "synthetic-b"})


def test_k2_from_a_channel_incident_still_reaches_its_family():
    i = incident(scope="channel", subject_id="synthetic-b", severity="high")
    assert halted_channels(i, GRAPH) == frozenset({"synthetic-a", "synthetic-b"})


def test_k3_takes_the_entire_portfolio_read_only():
    i = incident(scope="portfolio", subject_id="synthetic-portfolio", severity="critical")
    assert halted_channels(i, GRAPH) == GRAPH.channels()
    for channel in GRAPH.channels():
        assert action_allowed("read", channel_id=channel, incidents=[i], graph=GRAPH)
        for action in ("publish", "schedule", "update", "delete", "upload"):
            assert not action_allowed(action, channel_id=channel, incidents=[i], graph=GRAPH)


def test_k4_stops_reads_too_because_the_credential_is_gone():
    i = escalate(incident(severity="critical", scope="credential", subject_id="synthetic-oauth"), "K4")
    assert i.state == "frozen"
    assert not action_allowed("read", channel_id="synthetic-a", incidents=[i], graph=GRAPH)


def test_unaffected_channels_keep_publishing():
    i = incident(scope="channel", subject_id="synthetic-a", severity="medium")
    assert not action_allowed("publish", channel_id="synthetic-a", incidents=[i], graph=GRAPH)
    assert action_allowed("publish", channel_id="synthetic-c", incidents=[i], graph=GRAPH)
    assert action_allowed("publish", channel_id="synthetic-c", incidents=[], graph=GRAPH)


def test_escalation_is_one_way_while_the_incident_is_open():
    raised = escalate(incident(severity="medium"), "K3")
    assert raised.kill_level == "K3" and raised.state == "frozen"
    with pytest.raises(IncidentError, match="cannot fall"):
        escalate(raised, "K1")
    assert escalate(incident(severity="low"), "K1").state == "quarantined"


@pytest.mark.parametrize(
    "build",
    [
        lambda: incident(scope="galaxy"),
        lambda: incident(severity="apocalyptic"),
        lambda: incident(state="clear"),
        lambda: incident(kill_level="K9"),
        lambda: incident(detected_at="2026-09-20T00:00:00"),
        lambda: incident(subject_id="../escape"),
        lambda: PortfolioGraph(channel_family={"../a": "f"}),
        lambda: action_allowed("detonate", channel_id="synthetic-a", incidents=[], graph=GRAPH),
    ],
)
def test_invalid_input_is_rejected(build):
    with pytest.raises(IncidentError):
        build()
