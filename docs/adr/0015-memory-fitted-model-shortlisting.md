# ADR 0015: Memory-fitted model shortlisting from public rankings

Status: proposed (2026-09-29). Implemented offline in `stigdev/modelfit.py`
with the networked half in `scripts/fetch_model_rankings.py`; pending user
review.

## Context

The operator wants model choice to follow public open-model rankings
automatically, bounded by the memory each machine can actually give a job.

Two pieces already existed and neither answered this. ADR 0012's `node.py`
knows what a machine can hold but knows nothing about models. ADR 0010's
`modelradar.py` promotes a model on measured results — quality, peak memory,
p95 latency, human edit minutes — but has no notion of where a candidate came
from. Nothing turned "this model is popular" into "this model fits here".

The tempting version of this feature is the wrong one. Auto-selecting the
top-ranked model and running it would contradict the rule Model Radar exists
to enforce: a model earns its place on what this machine measured, not on what
a leaderboard measured elsewhere on other tasks. A public ranking is a
third-party claim, the same category as an external revenue claim (ADR 0009)
or a borrowed metric hypothesis (ADR 0007 amendment).

## Decision

Add `stigdev/modelfit.py`. It converts a ranking into **candidates to
benchmark** and stops there.

### Records

`ModelCandidate`: `model_id`, `params_b`, `quantization`, `rank`, `source`,
`captured_at`, `license_state`, `evidence_grade`, optional `score`.

The grade is constrained: `LEADERBOARD_GRADES` excludes `A`, so a leaderboard
row cannot claim the grade reserved for a benchmark this repository ran. That
reuses `portfolio.EVIDENCE_GRADES`, the same vocabulary that grades external
revenue and mechanism claims.

### Sizing

`estimated_memory_gb` is `params_b × BYTES_PER_PARAM[quantization] +
RUNTIME_OVERHEAD_GB`. Both tables are planning figures, not measurements, and
both err high on purpose: guessing low on a 16 GB laptop means swapping or a
killed job, while guessing high costs one skipped candidate. The table ignores
architecture, context length and KV-cache growth, and carries a `ponytail:`
note to replace an entry the first time a real `BenchmarkResult.peak_memory_gb`
contradicts it.

### Fitting and shortlisting

`fits` requires the estimate to sit inside **both** the resource class budget
and the node's usable memory, and returns `False` outright for a class the
node can never host. The class budget is the tighter constraint by design: a
job that declares `text_small` and then eats the machine defeats ADR 0012's
admission.

`shortlist` returns candidates that fit, in leaderboard order, and by default
only those whose licence establishes commercial use. An empty shortlist is a
real answer, not an error. Duplicate ranks are refused rather than ordered
arbitrarily.

`to_snapshot` hands a candidate to Model Radar as a `ModelSnapshot`. The rank
does not travel — whatever the leaderboard thought, the promotion gate sees
only measurements. A candidate whose licence is not `commercial_ok` cannot be
converted silently.

### The networked half

`scripts/fetch_model_rankings.py` queries the Hugging Face models API, sorted
by downloads, and prints or writes the shortlist. It lives in `scripts/` for
the same reason `commission_node.py` does: the kernel and its tests never
reach the network.

It reads parameter counts from `safetensors.total` where the repository
reports one and falls back to parsing the model name. Licence state is derived
from the licence tag against a small allowlist of permissive licences;
anything else reports `restricted` or `unknown`, never `commercial_ok`,
because a licence is a rights question and the default must fail closed.

Verified against the live API on 2026-09-29 with `--node mobile-m4 --class
text_small`: 39 candidates considered, shortlist led by `Qwen/Qwen3-0.6B`
(1.86 GB estimated) and `Qwen/Qwen3-8B` (6.3 GB), both Apache-2.0, all inside
the 10 GB class budget.

## Conflicts and limits recorded, not resolved

1. **Downloads are not quality.** The script sorts by downloads because that
   endpoint is stable and unauthenticated. Download count measures popularity
   and age, not fitness for Korean historical narration or any other task
   here. It is a candidate ordering and nothing more.
2. **The memory table is a guess until a benchmark says otherwise.** Every
   number in `BYTES_PER_PARAM` and `RUNTIME_OVERHEAD_GB` is a planning figure.
   The shortlist is only as good as they are.
3. **Parameter counts fall back to name parsing.** A model whose name carries
   no size and whose repository reports no `safetensors.total` is skipped
   rather than guessed at, which quietly drops some good candidates.
4. **The licence allowlist is small and conservative.** Several licences that
   do permit commercial use are absent, so real candidates will be filtered
   out. Widening it is a rights decision, not a code change.
5. **No automatic download, quantisation, or serving.** The shortlist names
   models; pulling and converting them is separate work, and on the laptop it
   is bounded by the same 16 GB that bounds everything else.
6. **A shortlist is not a schedule.** Nothing yet submits benchmark tasks for
   the shortlisted models. Wiring that into the worker loop is the obvious
   next step and is deliberately not done here.

## Failure behavior

Invalid candidates raise `ModelFitError` at construction. `shortlist` refuses
duplicate ranks. `to_snapshot` refuses a non-commercial licence. The script
exits non-zero when the shortlist is empty, so a scheduled run that finds
nothing is visible rather than silent.

## Observability

None added. The script's JSON report carries the node, the class budget, how
many candidates were considered, the first ten skips with reasons, and the
estimate beside each shortlisted model, so a reader can see why a model was
kept or dropped.

## Acceptance tests

`tests/test_modelfit.py` (24 cases): record validation, the grade-A refusal,
the estimate's shape and monotonicity in quantisation, the estimate erring
high, fitting against both the class and the node, a class the node can never
host fitting nothing, rank order preserved among what fits, the licence
filter and its opt-out, capping, empty shortlists, duplicate-rank refusal, and
the handover to `ModelSnapshot` carrying no rank or verdict.

## Deferred

Submitting benchmark tasks for shortlisted models through the worker loop,
measured replacement of the sizing tables, automatic pull and quantisation,
richer leaderboards than the downloads endpoint, and per-task suitability
(a Korean-language narration benchmark rather than a general ranking).
