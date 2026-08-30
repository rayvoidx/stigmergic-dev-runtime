# Roadmap

Ordered by value. Nothing below is a present capability; see README
"Current limitations" for what exists today.

1. ~~Baseline conditions~~ — done: `single_persistent` and `best_of_n`
   runners implemented (see PROJECT_STATE decision log #12).
2. **Paid provider adapters** — Anthropic/OpenAI behind the existing
   `Provider` protocol (a local Ollama adapter already exists); strict budget
   enforcement (tokens/USD/calls) already present in the run loop; never used
   in tests.
3. **Pilot experiments** — 5 conditions x 5 seeds on a small live model per
   `docs/research_protocol.md`; variance estimates feed the power analysis.
4. **Harder benchmark tiers** — fixture v2+ with larger pools, adversarial
   near-duplicates, evidence-citation metrics; a second task family to reduce
   single-task construct risk.
5. **RQ3/RQ4 harnesses** — failure-memory ablation runner; mid-run
   worker/provider replacement schedule with injected failures.
6. **Multi-artifact projects** — directory-tree canonical state, per-artifact
   lineage.
7. **Stronger sandbox** — containerized execution before accepting artifacts
   from untrusted models or third parties.
8. **Remaining conditions** — `full_communication` (logged message channel)
   and `orchestrator` (logged delegation).
