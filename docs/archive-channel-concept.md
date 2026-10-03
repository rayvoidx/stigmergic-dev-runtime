# Archive channel concept — 밤의 사관

Revised 2026-09-29. Supersedes the sleep-aid framing in
`docs/archive-channel-launch.md`. First upload: 2026-10-01.

## What this channel is

**A channel that actually tells the old stories, from beginning to end.**

Not a sleep aid. Not ambient noise with a voice on top. The promise is that
the listener hears the whole tale, including the parts most people have
forgotten.

Everyone in Korea knows the opening of 해와 달이 된 오누이 — the tiger on the
mountain pass, 떡 하나 주면 안 잡아먹지. Far fewer can say what happens after
the children climb the tree, or why the sister became the moon rather than the
sun. That gap is the channel.

## The audience contract

> 우리가 어릴 때 들었던 옛날이야기를, 처음부터 끝까지 제대로 들려드립니다.

One sentence, and it is falsifiable. An episode that skips the ending,
summarises instead of telling, or pads with commentary has broken it.

## What changed from the earlier framing

The first draft treated this as sleep content and the whole production
followed: slow narration, eighteen-second silences between chapters, a
near-black screen, a title that read 잠들 때까지 틀어 두는 밤.

Every one of those was wrong for a storytelling channel.

| | Sleep framing | Storytelling framing |
|---|---|---|
| Narration pace | slow, 0.88x | natural, 1.0x |
| Chapter gaps | 18 seconds | 4-6 seconds |
| Opening line | "불을 낮추고 편히 누우세요" | the tiger on the mountain pass |
| Visual | near-black, no imagery | illustrated scenes following the story |
| Success metric | session length | completion rate, comments about endings |

The sleep audience is a side effect to welcome, not the target. A long-form
story told well gets listened to at night anyway; a sleep aid told badly gets
skipped by everyone who wanted the story.

## Why long-form

The format matches the promise. A folk tale compressed into sixty seconds
loses the thing worth hearing — the turns, the repetitions, the way the ending
lands. Shorts can carry one striking moment and point at the long version;
they cannot replace it.

Thirty-five minutes and ten tales is the shape episode 1 landed on, and it
reads as generous rather than padded. The illustration changes about every
thirteen seconds, roughly one image per three sentences, which is what keeps a
long episode from feeling like a static screen with audio over it.

## What makes it durable

Three things no folk-tale farm bothers with.

**The endings are complete.** Most channels stop at the famous part. This one
carries 나무꾼과 선녀 past the wife's departure to the rooster on the roof, and
says plainly that the ending differs by region.

**Variants are named, not flattened.** When a tale has three endings, the
narration says so. That is the honest thing and it is also the hook: it gives
the audience something to argue about, which the outro now explicitly invites.

**Record and tradition stay separate.** Nine tales are 전승, handed down with
no known author. 온달과 평강 is 사료 — it sits in 삼국사기 열전, written five
centuries after the events it describes, and the episode says both halves of
that. Stated once per episode, briefly, never lectured.

## Production, fixed

| Element | Tool | Licence |
|---|---|---|
| Script | written in-house from traditional tales | no single author on the originals |
| Narration | CosyVoice-300M-SFT, built-in speaker, 1.0x | Apache-2.0 weights and code |
| Illustration | FLUX.1-schnell 4-bit via mflux, one per three sentences | Apache-2.0 |
| Subtitles | NanumMyeongjo rendered to PNG and composited | SIL OFL 1.1 |
| Bed | generated with ffmpeg | no external asset |

Nothing in that table needs a licence conversation before publishing. The
narration uses a built-in speaker rather than a cloned voice, so no consent
question arises either.

Three production rules were learned by getting them wrong, and each one is now
enforced in code rather than remembered:

- **No camera motion on a still image.** `zoompan` steps its crop window by
  whole pixels, so a slow push reads as shake. Shots are static and the motion
  comes from cutting between them.
- **The picture reel must cover the audio exactly.** A reel one second short
  makes `-stream_loop` rewind, after which subtitles run ahead of the voice for
  the rest of the episode.
- **Never reuse a rendered clip by filename.** The name says nothing about the
  framing, the subtitle timing or the illustration behind it. Stale footage
  shipped three times before the cache was removed.

## Cadence from 2026-10-01

One long-form episode per week, plus two or three Shorts cut from a striking
scene in that week's episode. The Shorts point at the long version; they are
not standalone content.

At the planning costs in ADR 0013 this is roughly 64 GPU hours and 13 reviewer
hours a month, which fits the laptop until the Studio arrives.

## What would tell us this is wrong

- Completion rate below a third across the first three episodes.
- Comments asking the story to get to the point.
- No comments about endings or regional variants, which would mean the
  differentiator is invisible to the audience.

Any of those means the format needs changing, not the channel
(`FormatHypothesis`, ADR 0007).
