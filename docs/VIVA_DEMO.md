# Final viva — demo script and likely questions

Target: ~10 minutes of demo + questions. Everything below uses only what exists; items that depend on
the real-model run are marked **[needs results]**.

## Before the viva (do the day before)

1. Run the full experiment with your fixed model (`docs/EXPERIMENTS.md`). Keep `results/` including `llm_cache.sqlite`.
2. Generate the benchmark: `python -m experiments.benchmark.generate --out ../datasets/benchmark/generated`.
3. Start the backend **with the cache**, so the live demo is instant and does not need the model or network:
   ```bash
   export LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=<same model name as the experiment>  LLM_API_KEY=x
   export LLM_CACHE_PATH=../results/llm_cache.sqlite
   uvicorn main:app
   ```
   Responses cached by the experiment are reused by the web app (same prompt ⇒ same cache key; verified by
   `tests/test_api_evidence.py::test_cache_filled_by_the_experiment_...`). `LLM_BASE_URL`/`LLM_MODEL` must still
   be *set* (the values just have to match the experiment) or the app reports "no LLM configured".
4. **Do a full dry run of the demo on the viva machine.** Do not discover a path or port problem live.

## Demo flow

| # | Show | Say |
|---|------|-----|
| 1 | Slide: the workflow diagram (README) | "A system can work while drifting from its architecture. Structure finds *that* a rule is broken; it can't say whether it's justified. An LLM can reason about that but is slow, costly and inconsistent. We ask: can intent, structure and history tell us *when* the LLM is actually needed?" |
| 2 | UI → Overview → analyze `datasets/benchmark/generated/A01/repo` (rules: `.../A01/repo/architecture/rules.yaml`) → Graph | "Tree-sitter parses the repo, every import is resolved to a file, files are grouped by architectural role. Red edge = forbidden by the rules." |
| 3 | Findings → note the triage cards → open the violation | "Before any model is involved, the system gathers three kinds of evidence. Here there's no relevant decision record and an ordinary commit, so the policy says *evidence sufficient, no LLM needed*." |
| 4 | Analyze **C01**, open its violation | "Now an ADR is relevant: it grandfathers dependencies introduced before a cutoff date. Whether *this* dependency is covered depends on **when it was introduced** — that's the evolution evidence (timeline)." → Run evidence-guided analysis → **justified** |
| 5 | Analyze **D01** (same kind of ADR, dependency introduced *after* the cutoff) | "Same record, opposite answer, and the only difference is the date from Git history." → **violation** |
| 6 | Analyze **J01** | "The ADR here shares no wording with the code. Only the introducing commit cites its id. History is what connects the intent to the dependency." Point at the *selected because: cited by the introducing commit* chip |
| 7 | Analyze **F01** | "The only record permitting it is superseded, so no model is needed." |
| 8 | **Evaluation** tab **[needs results]** | Metrics table → accuracy-vs-cost chart → scenario heat map → inspector with "wrong only" ticked: "Here is where each method fails and why." |
| 9 | Slide: testing | "604 automated tests (511 backend, 93 frontend). Coverage was last measured before the M6/M7 work. Unit tests use stub models so they're deterministic. A contract test fails if frontend fixtures drift from the API. Metrics are cross-checked against scikit-learn, and the import graph and contract violations are cross-checked against the reference tools (grimp and import-linter) on random repositories." |
| 10 | Slide: limitations | See below. Say them before they are asked. |

## Questions the panel is likely to ask — and honest answers

**"How do you know your benchmark isn't just built to make your method win?"**
It partly is — we author the scenarios, so it can only show behaviour under controlled conditions. Mitigations:
labels known by construction and checked with the project's own analyzers (`tests/test_benchmark.py`); several
wording variants per scenario; unrelated noise ADRs; decoy scenarios where the policy wastes a call; a dev/test
split with the policy fixed before test results; per-scenario reporting so you can see where each evidence source
matters; and a stand-alone M4 baseline (random selection, same call budget) to show it isn't just "call the LLM less".
It does not show accuracy on real repositories.

**"Your policy escalates most findings. Where's the saving?"**
On this benchmark 45 of 60 violations escalate: 40 have a relevant *active* ADR by design and 5 more escalate on
history signals ("temporary" commits). Only 15 resolve without the model. Real repositories mostly have no relevant ADR, so the saving there would be larger — but we have not measured
that. We say so in the report.

**"Why not just use an LLM for everything?"** That is baseline M2 (and M3 with structure). The experiment measures its
accuracy, calls, tokens and latency against ours **[needs results]**.

**"How do you handle LLM unreliability?"** Temperature 0; strict JSON output validated; failed or unparseable calls are
recorded as failures (never silently turned into verdicts) and fall back visibly to the structural verdict; "uncertain" is
a first-class answer; every call's tokens and latency are logged; responses are cached so a run is repeatable.

**"Why a small/local model?"** Free API tiers cannot sustain repeated runs and prompt iteration, and a fixed local model
is reproducible. Every method uses the same model, so the comparison is internally fair; absolute scores are model-specific.

**"What about ADRs in real projects?"** The parser handles the three common formats (Nygard, MADR, YAML front matter)
and is tested on each. We did not evaluate on real ADR repositories (no ground truth); that's future work.

**"Does it work on other languages / bigger repos?"** Python only, `import` dependencies only. The parser interface is
language-agnostic (one subclass per language); we have not built another. Renames are not followed by the Git analysis.

## If something breaks live

- No model / no network: the cache serves cached cases; for anything uncached the UI shows the exact setup message.
- Backend not reachable: the UI shows the error; restart `uvicorn` and re-run the analysis (runs live in memory).
- Evolution shows "no Git history": the analysed folder isn't inside a Git repo (e.g. a zip without `.git`). Use the generated benchmark cases.
