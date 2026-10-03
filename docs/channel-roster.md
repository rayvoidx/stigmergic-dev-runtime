# Channel roster and account setup

As of 2026-09-29. Design and procedure only — no channel id, handle, OAuth
credential, or analytics figure belongs in this file. Those live in the private
operations layer once each channel exists.

## The roster is three plus one, not one

The private strategy (v3.3 §0, §4.1) is explicit that the portfolio is three
channels doing different jobs, not one channel with variations. A fourth is
allowed only as an isolated experiment.

| # | Channel | Role | `business_role` | Exists today | Cadence |
|---|---|---|---|---|---|
| 1 | **Signal Stories** | Public interpretation layer for the trend agent | `product_funnel` | **No** | 1 long + 2 shorts / week (mandatory floor) |
| 2 | **Archive Stories** | Long-session watch time, cultural IP, cash | `cash_engine` | **No** | 1 long + 2-3 shorts / week |
| 3 | **RAYV** | Music IP and producer brand | `ip_engine` | **Yes** | 1 single / 4-6 weeks + 6-10 derivatives |
| 4 | Commerce Lab | Purchase-intent experiment | `commerce_lab` | No, and not yet | Private pilot only |

Two things follow that are easy to get wrong.

**Signal Stories is mandatory, not optional.** ADR 0008 encodes this as an
`existence_floor` greater than zero, which makes the channel unable to reach
`retire`. It is the organ that turns the private Social Trend agent's findings
into something the public can read, and carries audience questions back. A
portfolio without it is a content farm with a research hobby attached.

**Only two channels may sit in `scale` at once.** `MAX_SCALE_CHANNELS = 2`
(ADR 0010). Three channels existing and two scaling is the intended shape.

## Current state per channel

### 1. Signal Stories — not created, not named

No name has been chosen. The Archive lane got 밤의 사관; this one has not had
the same treatment. Naming it is the first blocker, because the handle and the
brand assets follow from it.

Audience contract (v3.3 §4.1): *"지금 뜨는 기술·문화 현상을 출처와 데이터로 짧고
정확하게 설명"*.

### 2. Archive Stories — not created, named, one episode rendered

- Recommended name: **밤의 사관**, with 야사담 reserved for the unofficial-history
  segment. See `docs/archive-channel-launch.md`.
- Episode 1 is rendered and waiting: 48 minutes, ten tales, at
  `state/render/out/bam_ui_sagwan_ep01.mp4`.
- Every rights question on that file is settled: MIT narration weights, OFL
  font, original script, self-generated visuals and bed.

### 3. RAYV — already exists

`@RAYVSTUDIO`, roughly 2 subscribers and 13 videos at the 2026-09-27 snapshot.
This is the only channel that does not need creating, and the only one with a
diagnosis already written (v3.3 §6.1): it currently mixes two different
audience contracts, original singles and generic two-hour playlists. The
strategy calls for fixing that before adding output, not after.

No account work is needed here. The work is editorial.

### 4. Commerce Lab — deliberately not created

Seven promotion conditions must pass before it becomes a public channel
(`commerce_lab_promotion_gate`, ADR 0009). Creating the channel early would
invite exactly the failure the gate exists to prevent.

## Account creation — what only the operator can do

The same five steps apply to each new channel. None can be automated from
here: they need a Google sign-in, identity confirmation, and acceptance of
terms in the operator's own name.

### Per channel

1. **Create a Brand Account channel, not a personal one.**
   YouTube Studio → 설정 → 채널 추가. A Brand Account can be transferred, can
   hold multiple managers, and keeps the operator's personal Google identity
   off the public channel. Converting a personal channel later is disruptive.

2. **Claim the handle.** `@...` must be unique across YouTube. Check
   availability inside the creation flow; there is no reliable way to check it
   from outside a signed-in session.

3. **Set the audience contract in the About section.** One sentence, the same
   one recorded in this file. It is what the channel may never contradict.

4. **Upload channel art and set upload defaults.**
   - 업로드 기본값 → 아동용 아님, 카테고리, 기본 설명란 문구.
   - 합성 콘텐츠 표시는 업로드마다 체크해야 하며 기본값으로 둘 수 없다.

5. **Record the identity privately.** Channel id, handle, and Brand Account
   owner go to the private operations layer, never to this repository
   (ADR 0003).

### Before any of that, per channel

- **Name and handle decided.** Signal Stories has neither.
- **Trademark check.** kipris.or.kr for the Korean register. A name that
  collides is cheaper to abandon before the handle is claimed.
- **Search the name on YouTube.** A crowded name defeats the point of having a
  distinct audience contract.

### Monetisation, later

YPP application needs the channel to meet thresholds first, plus an AdSense
account and tax information. From 2027-02-01 new entrants need 1,000
subscribers and either 8,000 qualified watch hours in 365 days or 20M
qualified Shorts views in 90 days (`revenue.PolicySnapshot`, ADR 0009). Do not
apply before the thresholds are met.

## Order of work

1. Name Signal Stories. It is the only true blocker, and it blocks a mandatory
   channel.
2. Create both missing channels as Brand Accounts on the same day, so their
   handles are claimed together.
3. Publish Archive episode 1 as unlisted, check it on a phone at low volume,
   then make it public.
4. Fix RAYV's split audience contract before producing anything new for it.
5. Leave Commerce Lab alone until its gate passes.
