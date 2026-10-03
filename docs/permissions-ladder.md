# Permissions ladder: channel creation to full automation

2026-09-29. Every step the operator must take in person, in order, with what
each one unlocks. Nothing here can be done from this repository: each rung
needs a Google sign-in and an acceptance of terms in the operator's own name.

Credentials never enter this repository (ADR 0003). They belong in the private
operations layer or the OS keychain.

2026-09-30 publication update: [publication boundary](publication_boundary.md)
supersedes the old publication cadence. The upload/scheduling authorization
and quota notes below are corrected against current official API documentation;
other historical planning sections are not revalidated by this update.

## Rung 0 — before anything

| # | Item | Why | Cost |
|---|---|---|---|
| 0.1 | A Google account dedicated to the business | Keeps the channel off a personal identity and allows handing over access later | free |
| 0.2 | Two-factor on that account | Required before later rungs; a channel lost to a takeover is unrecoverable | free |
| 0.3 | Name decided per channel | The handle is claimed once and is awkward to change | free |

## Rung 1 — the channel exists

| # | Item | Where | Unlocks |
|---|---|---|---|
| 1.1 | **Brand Account channel** (not personal) | YouTube → 설정 → 채널 추가 | Transferable ownership, multiple managers |
| 1.2 | **Handle** `@...` | same flow | Public identity, search |
| 1.3 | Channel art, About, audience contract | Studio → 맞춤설정 | Trust signals |
| 1.4 | Upload defaults | Studio → 설정 → 업로드 기본값 | Fewer per-upload mistakes |

**Manual upload works from here.** Everything below removes the manual step.

## Rung 2 — verification

| # | Item | Requirement | Unlocks |
|---|---|---|---|
| 2.1 | Phone verification | SMS | Videos over 15 minutes, custom thumbnails |
| 2.2 | Custom thumbnail | 2.1 done | The 1280x720 file this pipeline renders |

Episode 1 is 48 minutes, so **2.1 is mandatory before it can be uploaded at
all**. Do this first.

## Rung 3 — automated upload (the automation goal)

| # | Item | Where | Notes |
|---|---|---|---|
| 3.1 | Google Cloud project | console.cloud.google.com | Free tier is enough |
| 3.2 | **YouTube Data API v3 enabled** | Cloud console → API 라이브러리 | The upload endpoint |
| 3.3 | OAuth consent screen | Cloud console → OAuth 동의 화면 | External; publish it, or stay in testing with the operator as a test user |
| 3.4 | OAuth client (Desktop app) | Cloud console → 사용자 인증 정보 | Produces `client_secret.json` |
| 3.5 | First interactive consent | one browser round trip | Produces a refresh token the worker reuses |

**Check actual project quotas.** The current
[`videos.insert` reference](https://developers.google.com/youtube/v3/docs/videos/insert)
describes a separate Video Uploads quota bucket and 100 calls/day. The old
1,600-unit/six-upload estimate is stale. Project-specific quota and channel
upload limits remain authoritative, and retries must be bounded.

The pipeline must explicitly request **private** uploads rather than rely on
the platform's default visibility.

Unverified API projects can be restricted to private uploads regardless of
requested visibility. Public scheduling requires the YouTube API compliance
audit/permission for that project; OAuth consent-screen verification alone
does not remove this restriction. Uploaders must set private explicitly.

## Rung 4 — monetisation

| # | Item | Requirement |
|---|---|---|
| 4.1 | YPP application | 1,000 subscribers plus 8,000 qualified watch hours in 365 days, or 20M qualified Shorts views in 90 days, for new entrants from 2027-02-01 |
| 4.2 | AdSense account | Bank and tax details |
| 4.3 | Tax information | Korean resident forms |

Do not apply before the thresholds are met.

## Rung 5 — optional, only if the loop demands it

| # | Item | Unlocks |
|---|---|---|
| 5.1 | YouTube Analytics API | Retention and traffic data flowing back into the adaptation loop |
| 5.2 | Content ID allowlist via distributor | Stops RAYV music claiming the operator's own videos |
| 5.3 | Distributor account | RAYV releases, ISRC, Official Artist Channel |

## The one scope choice that matters

An upload-only workflow may request `youtube.upload`. A workflow that computes
`publishAt` after upload completion also needs `videos.update`, which requires
one of its [documented scopes](https://developers.google.com/youtube/v3/docs/videos/update),
such as `youtube.force-ssl`; upload-only is insufficient. This is a broader
video-management grant and the operator must review it. Request no unrelated
scopes, keep tokens private, verify the target channel, and expose no delete
operation in the publisher.

## Order

1. Rung 0 and 1 for Signal Stories and Archive Stories on the same day.
2. **Rung 2.1 immediately** — episode 1 cannot be uploaded without it.
3. Upload episode 1 by hand, unlisted, and watch it on a phone at low volume.
4. Rung 3 only after two or three manual uploads have gone smoothly.
   Automating a process nobody has run by hand automates the mistakes too.
5. Rung 4 when the thresholds arrive on their own.
