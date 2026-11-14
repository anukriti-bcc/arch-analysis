# Final report outline — mapped to what exists

Each chapter says where its content comes from, so the report is assembled from the repository rather than
written from memory. **Do not write a results claim until the real-model run exists.**

| # | Chapter | Content | Source in this repo |
|---|---------|---------|---------------------|
| 1 | Introduction & problem | architectural drift; violation vs legitimate evolution; why structure alone and LLM alone are each insufficient | synopsis (problem statement, need) |
| 2 | Literature review & gap | erosion/drift, rule-based conformance, ADRs, LLMs in architecture (Schmid 2025: conformance checking underexplored) | synopsis (6 references) |
| 3 | Research questions & hypotheses | RQ1 detection quality of each method; RQ2 does evolution evidence help; RQ3 can evidence decide *when* to call the LLM; RQ4 cost trade-off. Phrase as "investigates whether" | brief; `docs/EXPERIMENTS.md` |
| 4 | System design | workflow diagram; evidence sources; components | `README.md` diagram; `backend/analysis/**` |
| 5 | Implementation | parser + import resolution; rule engine; Git evolution (replay history with the same parser; why not "latest commit"); ADR parsing; evidence bundle; LLM client (retry, cache, failures-as-data); policy rules I1/I2/H1–H3; API; UI | module docstrings are written to be quoted |
| 6 | Benchmark design | generator, 10 scenarios (table), why generated, how labels are known by construction, validation against the project's own analyzers | `experiments/benchmark/generate.py` docstring; `tests/test_benchmark.py` |
| 7 | Experimental method | methods M1–M5 + A1 (definitions), positive class, false positives, metrics, bootstrap by case, dev/test split, one fixed model, caching | `experiments/pipeline.py` docstring; `experiments/metrics.py` |
| 8 | Results **[needs run]** | `metrics.csv` table (test split); accuracy-vs-cost figure (`frontier.png`); per-scenario table (`metrics_by_scenario.csv`); LLM calls/tokens/latency/failures | `results/*/` |
| 9 | Analysis **[needs run]** | where each evidence source mattered (scenarios C, D, J); M5 vs M4 (does selection beat random at equal budget?); A1 (value of history); wasted escalations on decoys G, H; failure cases from the inspector | Evaluation tab → "wrong only" |
| 10 | Testing | table below | `backend/tests`, `frontend/src/**/*.test.*` |
| 11 | Threats to validity | authored benchmark; scenario mix ADR-dense (policy resolves only 15/60 without the model); model-specific scores; no rename tracking; Python-only | `docs/EXPERIMENTS.md` |
| 12 | Limitations, future work | real-repo case study; inferring intent without ADRs; CI integration; remediation suggestions (synopsis "future scope") | README "Known limitations" |
| 13 | Compliance mapping | filled table | `docs/COMPLIANCE.md` |

## Testing chapter (numbers measured)

| Layer | Tests | What it proves |
|---|---|---|
| Parser, scanner, import resolution (incl. anchored mode) | 53 | dependencies resolve to the right files: relative, absolute, packages, ambiguity, one edge per imported submodule |
| Rule loader, conformance engine | 14 | allowed/forbidden semantics, malformed rules rejected |
| Finding identity | 7 | stable keys survive unrelated edits; ids contiguous; no cross-run overwrite |
| Git evolution | 12 | introducing commit ≠ latest touching commit; re-introduction; renames flagged; subdirectory repos |
| ADR, evidence, policy | 50 | three ADR formats; relevance; each policy rule alone; per-scenario decisions |
| LLM client + analyzer | 34 | retry/backoff, JSON-mode fallback, caching, failures never cached, unparseable output recorded as failure |
| Benchmark + held-out wording + prompt variants + A2 | 69 | labels verified with the project's own analyzers; generation deterministic; held-out repos identical except ADR language; keyword matching defeated by held-out wording |
| Metrics + methods + runner | 48 | hand-computed values; **agrees with scikit-learn**; paired bootstrap; density re-weighting; any method subset runs to completion |
| API | 29 | evidence, triage, semantic flow incl. 503/failure paths; path-traversal blocked; **cache reuse experiment → UI** |
| Frontend contract | 1 | frontend fixtures match the live API shapes |
| import-linter importer | 22 | contract semantics (forbidden / independence / layers / siblings), containment expansion, retrospective pruning |
| **Differential vs reference tools** | 34 | import graph identical to **grimp**; `forbidden` violations identical to **`lint-imports`**; layers/independence consistent — on random repositories; includes a check that the comparison can fail |
| Real-repo pipeline end to end | 5 | on a scripted repo: evaluation (engine vs reference) and the violation-lifecycle trace report exactly the scripted story |
| *Skipped* | *5* | third-party-repository test needs a repo cloned to `/tmp` |
| **Backend total** | **378 passed + 5 skipped** | core code 96% line coverage; 86% overall (five one-off GitHub-crawling and orchestration scripts are tested end to end, not line-measured) |
| Frontend (components, pages, full journey) | 89 | every component and page, against fixtures exported from the real API; 99% line coverage |
| **Grand total** | **467 passing** | |

Additional verification worth stating: tests were **mutation-checked** (deliberately introduced bugs in the
timeline and the scoped finding lookup were caught); the full stack was exercised end-to-end over real HTTP (backend +
Vite proxy); `tests/test_frontend_contract.py` fails if fixtures drift from the API. State what was *not* tested:
Docker files, the GPU notebook, any real LLM, and the browser rendering itself (components are tested in jsdom, not in
a real browser).
