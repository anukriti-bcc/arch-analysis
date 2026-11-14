# Evidence-Guided Architecture Conformance Analysis

Detects where a codebase has drifted from its intended architecture, and decides *when
an LLM is actually needed* to tell a genuine violation from a justified exception.

```
repository ──► Tree-sitter parse ──► components + dependencies ──► rules ──► findings
                                                                              │
        Git history ──► when was it introduced? ────────────────┐             ▼
        ADRs / rules ──► what was intended? ────────────────────┼──► evidence bundle
        code structure ──► what does it actually do? ───────────┘             │
                                                                              ▼
                                               "Evidence sufficient?" ──yes──► direct verdict
                                                         │ no
                                                         ▼
                                                  LLM semantic review ──► verdict + explanation
```

Final-year Major Project (Research + Development). Research question: can architectural
intent, structural evidence and software-evolution history decide *when* semantic (LLM)
reasoning is necessary, trading detection quality against LLM cost?

## Status

| Area | State |
|---|---|
| Parsing, dependency extraction, rule engine, API, React UI | built, tested |
| Git evolution analysis (introducing commit, age, signals) | built, tested |
| ADR parsing + evidence aggregation | built, tested |
| LLM layer (provider-agnostic, cached, failure-aware) | built, tested **against stubs** |
| Escalation policy ("evidence sufficient?") | built, tested |
| Controlled benchmark (60 repos, 10 scenarios) + experiment runner (M1–M5, ablation) | built, tested |
| **Experiment run with a real language model** | **not yet done** — see `docs/EXPERIMENTS.md` |
| Real-repository case study (sqlfluff, import-linter contracts as intent; engine cross-checked against the reference tools) | done for one repo; see `docs/REAL_REPOS.md` — **no ADR text and no LLM involved** |
| Held-out ADR wording, minimal-prompt sensitivity run, A2 (no-intent) ablation, paired statistics, ADR-density analysis | built, tested; see `docs/EXPERIMENTS.md` and `docs/ANALYSIS_PLAN.md` |

Tests: **378 backend + 89 frontend**. Core product code is at 96% line coverage (frontend 99%); overall backend coverage is 86%
because five one-off real-repository scripts (GitHub crawling, candidate search) are exercised end to end but not line-measured. Unit tests use stub
models, so they need no API key and no network.

## Quick start

```bash
# backend (Python 3.12, git must be installed — the evolution analyzer uses it)
cd backend
pip install -r requirements-dev.txt
uvicorn main:app --reload                       # http://localhost:8000/docs

# frontend
cd frontend
npm install
npm run dev                                     # http://localhost:5173  (proxies /api to :8000)
```

Or `docker compose up --build` (written but **untested** — see `docker-compose.yml`).

Open the UI → **Run analysis** (defaults to the bundled demo repo) → Graph → Findings → open a
violation to see its structural, intent and evolution evidence and the policy's decision.
The **Evaluation** tab shows experiment results from `results/`.

### Enabling the LLM (optional; only needed for semantic review)

```bash
export LLM_BASE_URL=http://localhost:11434/v1     # any OpenAI-compatible endpoint (Ollama, Gemini's
export LLM_MODEL=<model>                          #  compatibility endpoint, OpenRouter, ...)
export LLM_API_KEY=<key-if-needed>
export LLM_CACHE_PATH=../results/llm_cache.sqlite # reuse responses cached by the experiment runner
```
Without these the UI still shows all evidence and the policy's decision; only the "ask the model"
step reports how to configure one.

## Tests

```bash
cd backend  && python -m pytest tests -q --cov=.          # 378 passed, 5 skipped
cd frontend && npm test                                    # 89 passed;  npm run test:coverage for coverage
```
The 5 skipped tests need a third-party repository cloned to `/tmp` (see the test file).
`tests/test_frontend_contract.py` fails if the frontend's JSON fixtures drift from the real API.

## Running the evaluation

See **`docs/EXPERIMENTS.md`** (benchmark generation, planning LLM calls, running with a local model
or on a free GPU notebook: `notebooks/run_on_free_gpu.ipynb`).

## Layout

```
backend/
  analysis/
    parser/        Tree-sitter parsers (Python); one subclass per language
    dependency/    scanning, import resolution, graph
    conformance/   deterministic rule engine
    evolution/     Git analyzer: when did this dependency appear?
    intent/        ADR parsing + relevance (architectural intent)
    evidence/      one EvidenceBundle per finding
    policy/        escalation policy: is the evidence sufficient?
    semantic/      LLM client (retry/cache), prompts, structured-verdict analyzer
  experiments/     benchmark generator (primary + held-out wordings), methods M1–M5 + ablations, metrics, runner
    real_repos/    import-linter contracts as intent: importer, evaluation, violation-lifecycle trace (see docs/REAL_REPOS.md)
  api/             FastAPI routes (analysis, findings, evidence, triage, experiments)
frontend/          React + Vite: Overview / Graph / Findings (evidence panels) / Evaluation
datasets/          sample-ecommerce demo repo; generated benchmark goes in datasets/benchmark/generated
docs/              EXPERIMENTS.md, COMPLIANCE.md, VIVA_DEMO.md, REPORT_OUTLINE.md, SUPERVISOR_DIARY.md, PROGRESS.md
notebooks/         run_on_free_gpu.ipynb (untested)
```

## Deviations from the submitted synopsis (state these openly)

| Synopsis | Actual | Why |
|---|---|---|
| React **TypeScript** | React **JavaScript** (JSX) | mid-viva code was JS; behaviour is covered by 89 tests. Either convert or reword the report. |
| **PostgreSQL** | in-memory run store; results as CSV/JSON | not on the critical path; swapping `storage/memory_store.py` is the extension point |
| scikit-learn for metrics | metrics implemented with pandas/NumPy, **cross-checked against scikit-learn** in `tests/test_metrics.py` | explicit handling of degenerate cases |
| Docker | `docker-compose.yml` written, **never run** | no Docker available where it was written |
| Evaluation on repositories with real ADRs | **generated** benchmark with known ground truth | real-repo ground truth needs expert annotation; see threats to validity in `docs/EXPERIMENTS.md` |

## Known limitations

- Python only; `import` dependencies only (no calls/inheritance).
- Import resolution matches dotted-path suffixes rather than real `sys.path` resolution; ambiguous
  basenames resolve to the shortest path (tested, documented in `module_index.py`).
- File renames are not followed by the evolution analyzer (flagged per finding).
- The benchmark is generated and authored by us; results show behaviour under controlled
  conditions, not accuracy on real repositories.
