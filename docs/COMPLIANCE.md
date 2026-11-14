# Project compliance mapping (Guidelines §8)

Filled from the actual repository. "Status" is deliberately explicit: a claim is only as good as
its evidence, and some evidence (the real-model experiment) does not exist yet.

| Requirement | How our project satisfies it | Evidence / module / experiment | Status |
|---|---|---|---|
| **Project type** | Research + Development. Development: a working analysis platform (parser → conformance engine → Git/ADR evidence → LLM layer → API → web UI). Research: an evaluated, evidence-guided policy for *when* to call an LLM, compared against four baselines and an ablation. | Dev: `backend/analysis/**`, `backend/api/**`, `frontend/src/**`. Research: `backend/experiments/**`, `docs/EXPERIMENTS.md`. The research result informs the built system: the same policy (`analysis/policy/escalation.py`) drives `POST /findings/{id}/semantic-analysis`. | Dev: done. Research: harness done; **real-model results pending** |
| **Framework compliance** | No Keras, TensorFlow or MATLAB anywhere. Stack: Python, FastAPI, Tree-sitter, NetworkX, pandas/NumPy/matplotlib, React/Vite; LLMs are reached over plain HTTP (OpenAI-compatible API). | `backend/requirements*.txt`, `frontend/package.json` | Done |
| **WP classification** | **WP3 (primary)**: no established method combines intent, structure, history and semantic reasoning for conformance analysis; a model had to be formulated and evaluated. Also **WP7**: many interacting components (parser, resolver, rule engine, Git miner, ADR reader, evidence aggregator, policy, LLM client, UI). **WP1**: rests on software-architecture and static-analysis fundamentals. **WP4**: LLM-based conformance checking is an emerging, little-studied area (Schmid et al. 2025, cited in the synopsis). | `docs/REPORT_OUTLINE.md` §problem; literature review in the synopsis | Argued; unchanged from synopsis |
| **EA1** Diverse resources | Combines Git histories, decision records, rule files, source code, an LLM and analysis tooling. | `analysis/evolution/`, `analysis/intent/`, `analysis/parser/`, `analysis/semantic/` | Done |
| **EA2** Conflicting issues, trade-offs | *Not claimed in the synopsis; defensible but secondary.* The central trade-off is detection quality vs LLM cost/latency vs reproducibility (non-deterministic models, cost, privacy of sending code to an API). Made explicit and measured: calls, tokens, latency, fallbacks. | `experiments/metrics.py::efficiency`, `docs/EXPERIMENTS.md` (threats to validity) | Harness done; numbers pending |
| **EA3** Creative / research-based | A new decision procedure (escalation policy) and a controlled benchmark in which each scenario places the deciding evidence in a known source (structure, ADR, or history). | `analysis/policy/escalation.py`, `experiments/benchmark/generate.py` | Done |
| **EA4** Consequences and uncertainty | Architectural drift is hard to predict; distinguishing violation from legitimate evolution is uncertain. Uncertainty handled explicitly: model failures are recorded (never turned into verdicts), "uncertain" verdicts fall back visibly, temperature 0 + response cache for repeatability, bootstrap confidence intervals, dev/test split, stated threats to validity. | `analysis/semantic/llm_client.py`, `experiments/pipeline.py` (outcome sources), `experiments/metrics.py` | Done |
| **EA5** Beyond previous experience | Applies established principles (rule-based conformance, repository mining, LLM reasoning) to a combination not covered by prior conformance work, and evaluates it experimentally. | whole pipeline; `docs/EXPERIMENTS.md` | Done (claim rests on the pending experiment) |
| **Supervisor diary** | A meeting diary must be kept for every supervisor meeting. | `docs/SUPERVISOR_DIARY.md` — **template only; entries must be real** | **Team to maintain** |

## Checklist from Guidelines §6

- [x] Research + Development project
- [x] Substantial development component (≈5,600 lines of backend Python and ≈1,700 lines of frontend JS/JSX, plus ≈4,100 lines of tests; 467 automated tests)
- [x] No Keras / TensorFlow / MATLAB
- [x] Maps to WP3 (+ WP1, WP4, WP7)
- [x] Genuine engineering complexity (not CRUD)
- [x] Meaningful technical decisions and trade-offs (policy rules, evidence sources, cost vs accuracy)
- [x] Demonstrates EA1, EA3, EA4, EA5 (EA2 arguable)
- [x] Evaluated objectively — **harness complete; real-model run pending**
- [ ] Supervisor meeting diary maintained — **to be confirmed by the team**
