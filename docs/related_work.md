# Related work and claim ledger

Every entry separates (a) **source finding** — what the primary source states,
(b) **our interpretation**, and (c) **hypotheses to test** here. Bibliographic
details and abstract claims below were verified against arXiv abstract pages
and the arXiv export API on 2026-08-30. "Abstract-verified" means exactly
that: full-paper details not present in the abstract are marked UNVERIFIED.
Nothing in this ledger is a result of this repository.

## SwarmWorld (arXiv:2608.26081, abstract-verified)

Pal, Wang, Buehler. "SwarmWorld: Stigmergic technological evolution in
societies of language-model agents." v1 2026-08-26.

**Source findings (quoted or tightly paraphrased from the abstract):**
- Initially homogeneous LLM agents "self-organize without assigned roles or
  recipes"; agents "differentiate into exploration, construction, maintenance,
  and coordination behaviors."
- Agents "write executable controllers evaluated by a deterministic simulator
  under unseen disturbances after the agents are removed."
- "Most reuse beginning through physical observation rather than
  communication" — note the hedges *most* and *beginning*.
- "Shared societies develop broader, more resilient technological portfolios
  than a strong best-of-N isolated-search baseline, although isolated search
  remains competitive for the strongest artifact."
- "Physical stigmergy alone supports capable societies, while interaction
  drives persistent technological ecologies rather than universally superior
  individual inventions."

**Explicitly NOT supported by the abstract (checked):**
- Whether the four behavioral roles are measured emergent clusters or a
  post-hoc taxonomy — method undisclosed at abstract level. UNVERIFIED.
- "Evolution continues after agent deletion" — the abstract only says
  already-written controllers are *evaluated* after agents are removed.
- Any graph-connectivity metric or "functional recovery" claim — neither
  appears in the abstract.

**Our interpretation:** artifact persistence plus environmental observation
carries a large share of coordination value; direct communication adds breadth
more than peak quality. **We test:** RQ1/RQ2 with explicit, logged conditions
and matched budgets in a software-evolution (not simulated-world) setting.

## EvoX Genesis (arXiv:2608.10450, abstract-verified)

Huang, Liang, Zheng, Cheng. "Persistent Recursive Worlds Enable Autonomous
Software Evolution." v3 2026-08-16.

**Source findings:** makes "the software project persistent while allowing
local agents to remain finite-lived"; "only accepted consequences advance the
persistent version history." Reported artifacts: a ~250k-line Rust C compiler
(DeepSeek V4 Flash, 120 h, >1,000 episodes, ~US$44) passing "the complete
c-testsuite and most LLVM and Csmith tests"; a GLM 5.2 world where
"development continued after repeated agent replacement while retaining full
test performance"; a Fortran-to-Rust MESA port with median speedups 1.55–6.87x.

**Note:** the continuation-after-agent-replacement result belongs to *this*
paper, not SwarmWorld. Numbers are author-reported; not independently
reproduced by us.

**Our interpretation:** the closest prior to our thesis; validates
project-persistent/agent-ephemeral at scale. **We test:** RQ4 (worker/provider
replacement) with a fully open, replayable runtime and controlled comparison
arms, which the abstract does not describe.

## Self-Evolving Coding Agents (arXiv:2608.03392, abstract API-verified)

Zhou, Hu, Shang, Zhang. Title is "Self-Evolving Coding Agents" (the word
"survey" is a self-description in the abstract, not the title). v2 2026-08-20.

**Source findings:** taxonomy of *what* evolves (framework, memory, skills and
tools, model-side components, workflow/topology, environment/context), *when*,
and *which code-specific signals* drive it; flags challenges in "feedback
reliability, benchmark overfitting, reversibility, system complexity, safety,
cost, and generalization."

**Our interpretation:** our runtime evolves the *environment/artifact* axis
only, with reversibility (append-only log + recover) and feedback reliability
(deterministic versioned evaluators) as first-class design goals — directly
addressing two flagged challenges. Benchmark-overfitting risk applies to
TrendEvoBench's train/holdout split and is measured, not assumed away.

## SWE-Milestone (arXiv:2603.13428, abstract-verified)

Deng, Chen, Yu, et al. "SWE-Milestone: Evaluating AI Agents on Continuous
Software Evolution." v4 2026-07-21.

**Source findings:** DeepCommit reconstructs "verifiable Milestone DAGs from
noisy commit logs"; across 12 frontier models / 4 frameworks, performance
drops "from >80% on isolated tasks to 38.03% in continuous settings."

**Our interpretation:** continuous evolution is the hard regime and the right
place to measure coordination mechanisms; motivates our retention/regression
metrics. TrendEvoBench is far smaller; we do not claim comparability.

## AlphaEvolve (arXiv:2506.13131 + DeepMind blog 2025-05-14, verified)

Novikov et al. **Source findings (abstract):** an evolutionary pipeline of
LLMs improving code, "continuously receiving feedback from one or more
evaluators"; results include a datacenter scheduling heuristic, hardware
circuit simplification, faster LLM training kernels, and 48-multiplication
4x4 complex matrix multiplication ("first improvement, after 56 years, over
Strassen's algorithm in this setting"). Blog adds ~0.7% average compute
recovery in production and ~75%/20% rediscover/improve rates on ~50 open math
problems (blog numbers are single-source).

**Our interpretation:** strongest evidence that evaluator-gated evolution of
executable artifacts produces real capability; centralized and closed-source.
**We test:** whether the gate + artifact medium works as an *open,
multi-worker coordination substrate* rather than a single managed pipeline.

## Continuous / long-horizon agent evaluation (fetched, abstract-level)

- **LoopsBench** (arXiv:2608.00267): 112 dependency-DAG tasks; best
  configuration reported resolves 25.00%.
- **SlopCodeBench** (arXiv:2603.24755): 36 long-horizon problems; "no agent
  fully solves any problem end-to-end"; agent code reported 2.3x more verbose
  than human baselines.
- **Code as Agent Harness** (arXiv:2605.18747): survey framing code as the
  operational substrate for agent reasoning/verification. (Fetch was partially
  paraphrased; treat details as approximate.)

Search-result-only leads (NOT fetched, unverified): ChainSWE
(arXiv:2607.02606), ContextBench (arXiv:2602.05892), SentinelBench
(arXiv:2606.05342), SWE-bench Live, SWE-rebench(-v2), Terminal-Bench.

**MOSS:** no primary source was fetched and verified in the build session; the
motivating references to MOSS remain UNVERIFIED and must be checked before any
citation.

## Hypotheses this repository exists to test (currently untested)

- H1 (RQ1): artifact_only > single_persistent and > best_of_n on milestone
  success at matched budgets.
- H2 (RQ2): artifact_only retains a large fraction of full_communication's
  performance at lower token cost.
- H3 (RQ3): failure-record inheritance reduces repeated-failure rate without
  reducing distinct-mutation coverage.
- H4 (RQ4): mid-run worker/provider swaps degrade artifact_only runs less than
  single_persistent runs.
- H5 (RQ5, registered 2026-08-31 after exploratory pilots, before any
  confirmatory run): the artifact_only-over-single_persistent advantage
  grows with worker capability; failed-code exposure in the medium hurts.

No experimental evidence for H1–H4 exists in this repository today. The MVP
demonstrates the *mechanisms* (implemented capabilities), not the comparative
claims.
