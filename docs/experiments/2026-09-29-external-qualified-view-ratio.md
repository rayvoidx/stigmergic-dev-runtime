# Registered external hypothesis: the qualified-view ratio

Registered 2026-09-29. Status: **open** — nothing here has been measured.

## What was claimed

An X thread by `@mung99933` (captured 2026-09-29, posted 2026-09-19) makes
three claims about YouTube Shorts metrics. The thread is behind X's API
paywall — `WebFetch` on the status URL returns `HTTP 402 Payment Required` —
so the only record is a set of screenshots the operator supplied, and the
quotations below are from those screenshots, not from the live post.

| # | Claim (as written) | Grade | Use |
|---|---|---|---|
| 1 | "지금부터 말하는 모든 조회수는 '유효조회수'를 기준으로한다. 대충 명목조회수의 45%정도로 잡으면 된다." | C | registered below |
| 2 | "조회수1000에 뭐 있는거 맞다. 이건 기초테스트다." | C | not registered |
| 3 | "당신들이 보는방식에서의 지표가 의미가 없다" | — | see below |

Grade C under `portfolio.EVIDENCE_GRADES`: the author states the data came
from a channel they created themselves ("내가 직접 새 채널 만들어서 데이터
수집해오느라 늦었다"). No channel is named, no sample size, no per-format,
per-country or per-policy-era breakdown, and no underlying data is published.
Engagement on the post (59 replies, 141 reposts, 476 likes, 811 bookmarks) is
distribution, not evidence.

## Claim 3 is not what it looks like

Read literally, "metrics are meaningless" would contradict the format-stop
rules and `FormatHypothesis` itself. The author's own wording is narrower:
the metrics are meaningless **in the way you are reading them**. That is a
claim about the denominator — retention, click-through and view rate computed
against nominal views are not comparable to the same ratios computed against
qualified views.

This repository already agrees with that, from a different direction.
`portfolio.ProfitSnapshot` refuses a bare `views` metric key and accepts only
`raw_views` / `engaged_views` / `qualified_views`, and `portfolio.view_policy_era`
splits cohorts at 2026-08-24 because the first-frame counting change moved the
denominator (ADR 0009, §13 P0.13). So claim 3 is corroboration for a decision
already made, not new information, and needs no registration.

## What is registered

Claim 1 is the only one with a number attached, so it is the only one worth
measuring.

```python
from stigdev.portfolio import FormatHypothesis

FormatHypothesis(
    hypothesis_id="ext-qualified-view-ratio-2026-09",
    channel_id="<own channel>",
    variable="view_counting_denominator",
    primary_metric="qualified_views_over_raw_views",
    cohort_size=0,
    started_at="2026-09-29T00:00:00+00:00",
    status="open",
    source_url="https://x.com/mung99933/status/2101220953573487043",
    evidence_grade="C",
)
```

`FormatHypothesis` gained `source_url` and `evidence_grade` on 2026-09-29 for
exactly this: an idea taken from outside is registered as something to measure,
never as a fact. The two fields are co-required, so a borrowed number cannot be
recorded without saying where it came from and how good that source is.

## How it would be settled

Measure `qualified_views / raw_views` per own channel, per format, on cohorts
that do not straddle 2026-08-24, and report the distribution rather than a
single ratio. The claim is settled as `supported` only if the ratio is stable
enough across formats and cohorts that a single planning constant would not
mislead; otherwise `rejected` or `inconclusive`, and the ratio stays a measured
per-cohort value.

## What must not happen

- 0.45 must not become a constant in code. The repository's rule is that
  thresholds are read from a `revenue.PolicySnapshot` with an effective date,
  not hardcoded, precisely because these numbers move.
- `capacity.SHORTS_POOL_SHARE` is already `0.45` and means something entirely
  different (the creator's share of the Shorts pool). Two unrelated constants
  with the same value are a collision waiting to be misread; if this ratio is
  ever adopted it needs a name that cannot be confused with that one.
- Until the ratio is measured, no projection, target or capacity figure may be
  scaled by it.
