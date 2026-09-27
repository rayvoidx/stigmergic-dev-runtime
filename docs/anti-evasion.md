# Anti-evasion stance

This repository implements portfolio governance for operators who run more than
one channel. That capability is easy to point at platform evasion, so the line
is drawn here explicitly, in the code as well as in prose.

## What multi-channel operation is for

Running several channels is legitimate when each one serves a different
audience with a different promise. The kernel encodes that as an
`AudienceContract` per channel and a `FormatFingerprint` that makes reuse
visible. A format family may be reused; scripts, sources, assets, voices, and
viewer promises may not.

The thing worth copying from any successful multi-channel operator is the
operating structure — a shared research, rights, and production pipeline behind
genuinely distinct channels — not the channel count. `discover a format family,
prove it, create distinct audience contracts, scale only the profitable ones`
is a different activity from `find one winner and clone it twenty-six times`,
and only the first is supported here.

## What this repository will not help you do

These are refused as designs, not merely discouraged:

- **Hiding who owns a channel.** Burner phones, extra SIMs, and family members'
  names do not appear in any contract here, and no field exists to record them.
  One account can already manage many channels; separate identities are not a
  technical requirement for multi-channel operation, so their only function is
  to obscure ownership.
- **Surviving enforcement by re-registering.** A terminated or restricted
  channel's content must not reappear on a new channel. Ownership obfuscation
  does not reduce that risk — it makes ownership, tax, and security opaque while
  leaving the enforcement exposure intact.
- **Near-duplicate publishing.** The same script, scene, voice track, or
  thumbnail lightly varied across channels. `FormatFingerprint.shared_assets`
  and `shared_scripts` exist to detect exactly this, and an exact match is a
  hard publish failure rather than a warning.
- **Manufactured engagement.** Trading views, comments, or subscriptions
  between channels the same operator controls.
- **Treating generation as originality.** That an image or voice track was
  produced by a model says nothing about whether the work is original. The
  originality evidence required here is source provenance, narrative
  independence, visual independence, and a recorded human contribution.
- **Flooding.** Launching many similar channels at once on the strength of one
  success. The lifecycle allows at most two channels in `scale`, and promotion
  needs evidence from at least three cohorts.

## How the code enforces it

| Rule | Where |
|---|---|
| One independent audience contract per channel | `lifecycle.AudienceContract`, `lifecycle.scale_gate` |
| Exact cross-channel asset or script reuse is detectable | `lifecycle.FormatFingerprint` |
| Overlapping channels are queued for human review | `overlap.review_queue` |
| At most two channels in `scale`; caps on active and pilot counts | `lifecycle.advance_lifecycle`, `portfolio.PortfolioPolicy` |
| An open incident suspends publishing regardless of lifecycle state | `lifecycle.ChannelSlot.may_publish` |
| Incidents halt a scoped blast radius, up to revoking credentials | `incident.halted_channels`, `incident.action_allowed` |
| Unverified external revenue claims cannot enter a forecast | `revenue.classify_claim`, `revenue.modeled_amount` |
| Estimates, payouts, and balances are never summed | `payout.total_across` |

## On the limits of these checks

The overlap score is an internal review heuristic with weights chosen by the
operator. It is not a platform threshold, and it never blocks on its own —
blocking belongs to the rights gate, exact fingerprint matches, and human
review. None of this substitutes for reading the platform's own policies, which
change; `revenue.PolicySnapshot` exists so that a rule's effective date is
recorded rather than assumed.
