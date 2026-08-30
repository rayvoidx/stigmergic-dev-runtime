# Lab note: first 3-condition comparison (2026-08-30)

**Status: mechanism demonstration, not evidence.** One seed per arm, one toy
benchmark, one small local model. Nothing here supports or refutes H1–H4 (see
`docs/research_protocol.md` for what would). Recorded because the runs are
fully archived and replayable, and because they exposed real qualitative
behavior of the conditions.

## Setup

- Conditions: `artifact_only`, `single_persistent`, `best_of_n` (n=3), all
  matched at 6 episodes / seed 42 (live) and 8 episodes / seed 42 (offline).
- Live provider: Ollama `gemma3:12b`, temperature 0, num_ctx 8192, 100% Metal
  GPU offload on an Apple M4 Pro. Cost $0 (local). Configs:
  `configs/providers/ollama-gemma3-12b*.json`.
- Evaluator `trendevobench.select` v1, policy `strict-improve/v1`, fixtures
  v1. Every run and every best_of_n worker sub-run replays with 0 divergences.
- Archives: `examples/live_run_gemma3_12b/` (artifact_only),
  `examples/live_run_gemma3_12b_single/`, `examples/live_run_gemma3_12b_bestof3/`.

## Offline (deterministic reference worker, 8 episodes)

| condition | proposed | promoted | train | holdout |
|---|---|---|---|---|
| artifact_only | 8 | 3 | 0.86 | 0.86 |
| single_persistent | 8 | 3 | 0.86 | 0.86 |
| best_of_n (4x2) | 8 | 3 (best worker 2) | 0.84 | 0.74 |

artifact_only == single_persistent is **by construction** with one sequential
worker (same information, different source); see the protocol note. best_of_n
loses depth to the budget split: no worker can stack more than 2 improvements.

## Live (gemma3:12b, 6 episodes, seed 42)

| condition | proposed | promoted | train | holdout | tokens | wall |
|---|---|---|---|---|---|---|
| artifact_only | 6 | 1 | 0.55 -> 0.66 | 0.63 | 6,616 | 92 s |
| single_persistent | 6 | 0 | 0.55 | 0.52 | 10,158 | 153 s |
| best_of_n (3x2) | 6 | 3 (one per worker) | 0.55 -> 0.66 | 0.63 | 5,853 | 81 s |

Qualitative observations (single anecdotes, worth testing properly):

1. **Redundant discovery under isolation.** All three best_of_n workers
   independently found essentially the same recency improvement (each
   promoted once to 0.66). The isolation cost is visible as duplicated work,
   not as failure.
2. **The persistent worker got stuck in self-repair.** Its first proposal
   crashed (`NameError: GENES` — it imitated the seed's structure wrongly);
   its remaining five proposals were micro-edits scoring exactly 0.55 (ties).
   It never attempted the recency idea the artifact_only worker found in
   episode 0, and burned ~54% more tokens on its growing private history.
   The gate rejected all six, so canonical state stayed the valid seed — the
   runtime's integrity guarantee did its job.
3. **Gate integrity held in every arm**: no crash or tie ever contaminated
   canonical state; every archived run replays bit-consistent on evidence.

Do not generalize (1)-(2): different prompts across conditions mean the model
saw different inputs, and n=1. The pre-registered comparisons need the pilot
and paper tiers in the protocol.

## RQ4 addendum: worker replacement at episode 3 (same day)

Same setup, `replace_at_episode: 3` (worker replaced; persistent private
memory wiped, store untouched). Archives: `examples/live_run_rq4_single/`,
`examples/live_run_rq4_artifact/`; both replay with 0 divergences.

| run | promoted | repeated failures | train | holdout | tokens |
|---|---|---|---|---|---|
| artifact_only, no replacement | 1 | 0 | 0.66 | 0.63 | 6,616 |
| artifact_only, replaced @3 | 1 | 0 | 0.66 | 0.63 | 6,616 |
| single_persistent, no replacement | 0 | 0 | 0.55 | 0.52 | 10,158 |
| single_persistent, replaced @3 | 0 | **2** | 0.55 | 0.52 | 8,901 |

- Under artifact_only the replacement is **behaviorally invisible**: with
  temperature 0 and a fixed seed the replaced run reproduced the baseline
  token-for-token (identical outcomes and token counts), because every
  episode's input comes from the store, which survived.
- Under single_persistent the successor repeated its predecessor's recorded
  failures exactly: at ep3 it re-crashed with the same
  `NameError: GENES` artifact its predecessor produced at ep0, and at ep5 it
  re-proposed ep1's failed `keyword_boost_threshold` (both counted by the
  objective repeated-failure metric, which always checks the store).
- Offline deterministic versions of both effects, plus a provider-swap
  degradation (memoryless replacement provider caps the run at 0.84 vs 0.86),
  are locked in as regression tests (`tests/test_rq4_replacement.py`).

Same caveat as above: n=1 per cell, mechanism demonstration only.
