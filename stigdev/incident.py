"""Policy incidents and the K0-K4 kill switch (ADR 0011, v3.3 §5.16.5, v2.1 §14.6).

An incident names a scope and a severity; the kill level derived from it says
which external actions stop. Stopping is scoped deliberately — the point is to
halt the blast radius, not the whole operation, until the evidence says the
radius is wider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any, Iterable

from .lifecycle import INCIDENT_STATES
from .workspace import valid_identifier

KILL_LEVELS = ("K0", "K1", "K2", "K3", "K4")
KILL_SCOPE: dict[str, str] = {
    "K0": "video",
    "K1": "channel",
    "K2": "format_family",
    "K3": "portfolio",
    "K4": "credential",
}
SCOPES = tuple(KILL_SCOPE.values())
# Actions the Action Gateway can be asked to perform on the outside world.
EXTERNAL_ACTIONS = ("publish", "schedule", "update", "delete", "upload", "read")
SEVERITIES = ("low", "medium", "high", "critical")
SEVERITY_KILL: dict[str, str] = {
    "low": "K0",
    "medium": "K1",
    "high": "K2",
    "critical": "K3",
}


class IncidentError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IncidentError(message)


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise IncidentError(f"invalid timestamp {value!r}") from exc
    _require(parsed.tzinfo is not None, f"timestamp {value!r} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class PortfolioGraph:
    """The links an incident travels along (v2.1 §14.6)."""

    channel_family: dict[str, str] = field(default_factory=dict)  # channel_id -> family_id
    video_channel: dict[str, str] = field(default_factory=dict)  # video_id -> channel_id

    def __post_init__(self) -> None:
        for mapping, what in ((self.channel_family, "channel_family"), (self.video_channel, "video_channel")):
            for key, value in mapping.items():
                _require(valid_identifier(key) and valid_identifier(value), f"invalid {what} entry {key!r}")

    def channels(self) -> frozenset[str]:
        return frozenset(self.channel_family) | frozenset(self.video_channel.values())

    def channels_in_family(self, family_id: str) -> frozenset[str]:
        return frozenset(c for c, f in self.channel_family.items() if f == family_id)


@dataclass(frozen=True)
class PolicyIncident:
    """v2.1 §5.2 `policy_incidents`. `state` follows the lifecycle incident overlay."""

    incident_id: str
    scope: str
    subject_id: str
    severity: str
    detected_at: str
    state: str = "watch"
    kill_level: str | None = None
    evidence_artifact_id: str | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.incident_id), "invalid incident_id")
        _require(self.scope in SCOPES, f"unknown scope {self.scope!r}")
        _require(valid_identifier(self.subject_id), "invalid subject_id")
        _require(self.severity in SEVERITIES, f"unknown severity {self.severity!r}")
        _timestamp(self.detected_at)
        _require(self.state in INCIDENT_STATES, f"unknown state {self.state!r}")
        _require(self.state != "clear", "an open incident is not `clear`; resolve it to close it")
        if self.kill_level is not None:
            _require(self.kill_level in KILL_LEVELS, f"unknown kill_level {self.kill_level!r}")
            _require(
                KILL_LEVELS.index(self.kill_level) >= KILL_LEVELS.index(SEVERITY_KILL[self.severity]),
                f"kill_level {self.kill_level} is below the floor for severity {self.severity}",
            )
        if self.evidence_artifact_id is not None:
            _require(valid_identifier(self.evidence_artifact_id), "invalid evidence_artifact_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PolicyIncident":
        return PolicyIncident(**raw)

    @property
    def effective_kill_level(self) -> str:
        """The declared level, or the floor implied by severity when none was declared."""
        return self.kill_level or SEVERITY_KILL[self.severity]


def escalate(incident: PolicyIncident, kill_level: str) -> PolicyIncident:
    """Raise the kill level; it never falls while the incident is open."""
    _require(kill_level in KILL_LEVELS, f"unknown kill_level {kill_level!r}")
    _require(
        KILL_LEVELS.index(kill_level) >= KILL_LEVELS.index(incident.effective_kill_level),
        "kill level cannot fall while the incident is open; resolve it instead",
    )
    state = "frozen" if kill_level in ("K3", "K4") else "quarantined"
    return replace(incident, kill_level=kill_level, state=state)


def halted_channels(incident: PolicyIncident, graph: PortfolioGraph) -> frozenset[str]:
    """Channels whose external actions stop at this incident's kill level."""
    level = incident.effective_kill_level
    if level in ("K3", "K4"):
        return graph.channels()
    if level == "K2":
        family = (
            incident.subject_id
            if incident.scope == "format_family"
            else graph.channel_family.get(incident.subject_id, "")
        )
        return graph.channels_in_family(family)
    channel = (
        graph.video_channel.get(incident.subject_id, "")
        if incident.scope == "video"
        else incident.subject_id
    )
    return frozenset({channel}) & graph.channels() if channel else frozenset()


def action_allowed(
    action: str,
    *,
    channel_id: str,
    incidents: Iterable[PolicyIncident],
    graph: PortfolioGraph,
) -> bool:
    """Fail closed: any open incident covering this channel stops every write."""
    _require(action in EXTERNAL_ACTIONS, f"unknown action {action!r}")
    _require(valid_identifier(channel_id), "invalid channel_id")
    for incident in incidents:
        level = incident.effective_kill_level
        if level == "K4":
            return False  # credentials revoked: nothing automated runs, reads included
        if channel_id in halted_channels(incident, graph):
            return action == "read"
    return True
