"""Offline tests for the cross-channel overlap heuristic (ADR 0011)."""

import pytest

from stigdev.overlap import (
    COMPONENTS,
    OVERLAP_WEIGHTS,
    REVIEW_THRESHOLD,
    ChannelOverlap,
    OverlapError,
    overlap_score,
    review_queue,
)


def components(**kw) -> dict[str, float]:
    base = {name: 0.0 for name in COMPONENTS}
    base.update(kw)
    return base


def pair(left: str, right: str, **kw) -> ChannelOverlap:
    return ChannelOverlap(left, right, components(**kw))


def test_weights_sum_to_one_and_cover_every_component():
    assert round(sum(OVERLAP_WEIGHTS.values()), 9) == 1.0
    assert COMPONENTS == ("audience", "viewer_job", "script", "asset_fingerprint",
                          "visual_voice", "monetization")


def test_score_spans_the_unit_interval():
    assert overlap_score(components()) == 0.0
    assert overlap_score({name: 1.0 for name in COMPONENTS}) == 1.0


def test_score_is_the_documented_weighted_sum():
    assert overlap_score(components(audience=1.0, script=0.5)) == 0.35


def test_round_trip_and_score_property():
    overlap = pair("synthetic-a", "synthetic-b", audience=0.8, monetization=0.4)
    assert ChannelOverlap.from_dict(overlap.to_dict()) == overlap
    assert overlap.score == 0.24


def test_review_queue_is_worst_first_and_drops_pairs_below_the_threshold():
    high = pair("synthetic-a", "synthetic-b", **{name: 0.9 for name in COMPONENTS})
    mid = pair("synthetic-c", "synthetic-d", **{name: REVIEW_THRESHOLD for name in COMPONENTS})
    low = pair("synthetic-e", "synthetic-f", audience=0.2)
    assert review_queue([low, mid, high]) == [high, mid]
    assert low.needs_review is False and mid.needs_review is True


def test_ties_break_on_channel_id_so_the_queue_is_deterministic():
    a = pair("synthetic-b", "synthetic-z", **{name: 0.8 for name in COMPONENTS})
    b = pair("synthetic-a", "synthetic-y", **{name: 0.8 for name in COMPONENTS})
    assert review_queue([a, b]) == [b, a]


@pytest.mark.parametrize(
    "build",
    [
        lambda: ChannelOverlap("synthetic-a", "synthetic-a", components()),
        lambda: ChannelOverlap("synthetic-a", "synthetic-b", {"audience": 1.0}),
        lambda: ChannelOverlap("../a", "synthetic-b", components()),
        lambda: ChannelOverlap("synthetic-a", "synthetic-b", components(audience=1.5)),
        lambda: ChannelOverlap("synthetic-a", "synthetic-b", components(audience=float("nan"))),
        lambda: overlap_score({"audience": 1.0}),
    ],
)
def test_invalid_input_is_rejected(build):
    with pytest.raises(OverlapError):
        build()
