# Launching the Archive Stories channel

Design and setup notes, 2026-09-29. No real channel id, handle, or analytics
belongs in this file — it holds the plan, and the private operations layer
holds the identity once the channel exists.

## What I cannot do, and what is left to the operator

Creating the channel needs a Google sign-in, identity confirmation, and
acceptance of YouTube's terms. Those are the operator's to give, so the
account creation itself is not automatable from here and should not be. The
name check is in the same category: whether a handle is free, and whether a
name collides with an existing mark, can only be settled by trying it on the
account and searching.

Everything below is the half that can be prepared in advance.

## Name candidates

The placeholder was "이야기 보따리". It is descriptive but crowded — sleep-story
and folk-tale channels using some variant of 이야기/보따리 already exist in
volume, which is the opposite of what a channel whose whole differentiator is
*sourcing* wants.

The operator's edge is a history background and a promise no folk-tale farm
makes: saying which part is record, which part is transmitted tradition, and
which part is the narrator's own. A name should carry that.

| Name | Reading | Why it fits | Risk |
|---|---|---|---|
| **밤의 사관** | "night historian" | 사관 is the court official who recorded events as they happened. Pairs the sleep-listening format with the sourcing promise in two words, and no folk-tale farm would pick it. | Slightly formal; needs warm artwork to avoid feeling academic |
| **야사담** | 野史談, "unofficial-history tales" | Names the exact distinction the channel sells: 정사 (official record) versus 야사 (unofficial). Compact, searchable, unusual as a handle. | 야사 also colloquially suggests salacious gossip; the channel art has to set the register |
| **등잔 밑** | "under the oil lamp" | From 등잔 밑이 어둡다. Evokes lamp-lit night storytelling and, read a second way, the overlooked detail a historian goes looking for. | The proverb's usual meaning is "you miss what is closest"; charming but indirect |
| **사초** | 史草, "the historian's draft" | The raw notes kept before official history was compiled — literally the sources behind the story. Perfect fit for a channel that shows its evidence. | Obscure outside people who know the term; weak search discovery |

Recommendation: **밤의 사관** as the channel name with **야사담** kept for the
unofficial-history segment inside it. That gives a name that survives the
channel growing past sleep content, and reserves a second identity without
splitting the audience early.

Before committing to any of them: search YouTube and the handle field, and
check the Korean trademark register. Neither can be done from this repository.

## The audience contract

One sentence the channel must never contradict, per the v3 §4.1 table:

> Stories you can fall asleep to, told by someone who tells you which parts are
> recorded, which are handed down, and which are his own.

That contract is what makes the scene-level labelling (`사료` / `전승` /
`창작`) a feature rather than an interruption.

## The plan to register once the channel exists

`business_role` is `cash_engine`: this lane carries long-session watch time
and the audio back-catalogue. It is not `product_funnel` — that is Signal
Stories, which feeds the Social Trend product.

```python
from stigdev.portfolio import ChannelPlan

ChannelPlan(
    channel_id="<handle once created>",
    business_role="cash_engine",
    stage="hypothesis",
    audience_contract="history_for_sleep_with_sourcing",
    weekly_publish_cap={"long": 1, "short": 3},
    owned_ip_ratio_min=0.90,
    human_review_required=True,
)
```

It enters at `hypothesis` and moves on evidence, not enthusiasm: ten finished
pieces before the private pilot, a rights and quality pass before anything is
public, and the seven §5.4 conditions before any increase in output. The
channel cannot reach `scale` while another two channels already hold those
slots.

Note the cadence against ADR 0013. One long piece and three Shorts a week is
roughly 4 long and 13 Shorts a month, which at the shipped planning costs is
about 64 GPU hours and 13 reviewer hours a month. That fits the laptop's
monthly envelope alone, but it is already most of a 15 h/week reviewer budget
once a second channel exists — so this lane starting is a reason to measure
review time early, not to assume it.

## What the laptop can produce for it before the Studio arrives

From ADR 0014: the M4 admits `text_small` (10 GB) and `render_cpu` (12 GB)
only. Script drafting, source gathering, labelling and CPU-side assembly run
locally today. Local image generation, vision and video do not — they are
impossible on 16 GB usable, not slow, and they wait for the Studio.

So the honest first-month plan is audio-led: narration over still artwork and
simple motion, which is what the format wants anyway. The visual layer gets
richer when the second machine lands, and nothing published before then has to
be re-made, because the sourcing and the narration are the assets.
