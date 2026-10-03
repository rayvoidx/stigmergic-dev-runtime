# Publication stays in the private operations layer

Operator direction, 2026-09-30: consume locally rendered storytelling videos,
upload privately during 07:00–19:00 Asia/Seoul laptop availability, and schedule
public release at least 24 hours after upload completion. Output is based on
finished, reviewed assets, with an initial ceiling of five releases/day and
spacing between releases, rather than the older one-long-form/week proposal.

This is an authorized downstream publishing task, not an extension of the
research `Provider`, the condition matrix, or the public worker daemon.
ADRs 0003/0005 and `docs/integration_boundary.md` still govern dependency
direction. Platform credentials, real channel IDs, operational connectors,
actual media and publication records stay outside tracked public files.

The producer/consumer seam is a completed publication manifest identifying
immutable media by hash, reviewed metadata, audience/synthetic-content
decisions, and rights/source/editorial evidence. File existence or a successful
render subprocess alone is not publish approval. A downstream publisher must
verify the final bytes and record append-only upload/schedule receipts.
It must not import private packages into this public kernel.

Known platform constraints, checked against official documentation:

- Scheduling after upload completion requires a metadata update. The
  [videos.update scopes](https://developers.google.com/youtube/v3/docs/videos/update)
  do not include upload-only `youtube.upload`.
- [Unverified API projects](https://developers.google.com/youtube/v3/docs/videos/insert)
  may only upload private videos until the YouTube API compliance audit is satisfied.
- Technical processing success does not establish copyright/Content ID clearance.
  The generic publish gate's `clear` requirement must not be invented by a connector.
- [Publishing time and tags](https://support.google.com/youtube/answer/141805)
  are not established long-term-performance guarantees. Initial release slots and
  a 24-hour hold are operating choices, not research findings or algorithm claims.

The private publisher was checked with deterministic offline transports;
live channel connection, upload and release remained unverified at this handoff.
Public tests and committed example replay remain self-contained. No experimental
hypothesis, committed result, evaluator version or research budget is changed.
