# Primary run — exploratory results

**Status: EXPLORATORY.** Primary ADR wording, `full` system prompt, one model, produced before `docs/ANALYSIS_PLAN.md` was committed and
inspected by the team (and the assistant) before it was written. It motivates the plan; it cannot confirm it. The confirmatory evidence is the
held-out-wording run (not yet executed). Files: `results/primary_exploratory/`.

**Model:** Qwen2.5 7.6B instruct, Q4_K_M, context 4096, temperature 0 (`model_info.txt`), via an OpenAI-compatible Ollama endpoint on a Kaggle GPU.
**Benchmark:** seed 7, 60 cases (dev 32, test 28). Test split: 196 governed dependencies, of which 28 are the targeted ones (19 genuine violations, 9 justified).

## Integrity of the run (checked)
* 784 model calls recorded, **all parsed, 0 errors, 0 fallbacks**; token counts were reported by the server (not estimated); ~2–3 s per call; longest prompt 1,054 tokens, well inside the 4,096 window (no silent truncation).
* The response cache holds exactly **514 entries = the 514 distinct calls of this run**, so no other prompt variant was ever sent through it (no prompt tuning happened in this cache).
* Every cached response is served by today's code and prompts (100% cache hits for M2, M3, M4, M5, A1), so the whole primary run is reproducible for free.

## Test split (F1 is for the class "genuine violation"; intervals are 95% case-level bootstrap)

| Method | Precision | Recall | F1 (95% CI) | False-positive rate | LLM calls |
|---|---|---|---|---|---|
| M1 Static rules | 0.679 | 1.000 | 0.809 (0.667–0.902) | 0.051 | 0 |
| M2 LLM-only | 0.121 | 0.368 | 0.182 (0.082–0.273) | 0.288 | 196 |
| M3 Full hybrid | 1.000 | 0.842 | 0.914 (0.800–1.000) | 0.000 | 28 |
| M4 Generic selective (mean of 5 seeds) | 0.879 | 0.895 | 0.886 (0.758–0.968) | 0.014 | 21 |
| **M5 Evidence-guided** | 1.000 | 0.947 | **0.973 (0.905–1.000)** | 0.000 | **21** |
| A1 M5 without evolution evidence | 0.842 | 0.842 | 0.842 (0.700–0.947) | 0.017 | 16 |

## Paired comparisons, M5 minus other (same cases; 5,000 resamples)

| vs | F1 difference | 95% CI | Reading |
|---|---|---|---|
| M3 full hybrid | +0.059 | 0.000 to 0.161 | **not distinguishable** (interval touches 0); M5 is *at least as good*, not shown *better* |
| M3, LLM calls | −7 | −12 to −3 | M5 uses clearly fewer calls |
| M4 random selection, same budget | +0.087 | 0.026 to 0.173 | M5 better |
| A1 no evolution evidence | +0.131 | 0.029 to 0.262 | M5 better, but it makes 5 more calls than A1 (interval 1 to 9): history buys accuracy at some cost |
| M1 static | +0.164 | 0.033 to 0.302 | M5 better; M1 false-positive rate 0.051 vs 0 |
| M2 LLM-only | +0.791 | 0.687 to 0.896 | M5 far better, with 175 fewer calls |

The dev split shows the same directions (M5 vs M3: +0.050, 0.000 to 0.128; calls −8, −13 to −3).

## Where methods succeed and fail (accuracy on the targeted dependency, test+dev read together)

| Scenario | What decides it | M5 | Note |
|---|---|---|---|
| A plain violation | structure | all correct | M2 only 40–60% |
| B permanent exception | active ADR text | correct | M4 (random) misses some: selection matters |
| C grandfathered, before cutoff | ADR + **intro date** | correct | |
| **D grandfathered, after cutoff** | ADR + **intro date** | **3 of 6 correct** | A1 (no history): 0 of 6. History is necessary but the 7B model still gets half wrong |
| E ADR reaffirms prohibition | ADR text | correct | |
| **F superseded ADR** | ADR **status** | correct (resolved by rule I2, no LLM) | **M3's model said "justified" in 4 of 5 cases**, ignoring the status line |
| G passing mention, H "temporary" commit, K wrong module | ADR scope / history | correct | |
| **J ADR cited only by the commit** | **history links the record** | correct | A1: 0 of 6 |

## What the data supports, and what it does not
* **Supported (exploratory):** M5 keeps M3's detection quality (non-inferior within 0.05) while using clearly fewer calls; it beats random selection at the same budget; evolution evidence matters (D, J); static rules over-report justified exceptions; the unaided LLM baseline over-reports badly.
* **Not supported:** that M5 is *better than* M3 — the interval touches zero. Say "at least as good".
* **The mechanism behind M5's higher score is mostly not LLM reasoning.** M3 and M5 differ almost entirely on scenario F: a deterministic status check (policy rule I2) beats a model that ignores the status line. This is a finding about routing **structured facts to code and semantic facts to the model**, and should be presented as such, not as "evidence makes the LLM smarter".
* **Model errors are systematic, not random.** (1) The model ignores structured status; (2) it cannot reliably compare dates ("introduced before the deadline" when it was not).
* **M2's failure is specific:** in 99 of 120 cases it flags a legitimate `repository -> database` import as a violation, citing rules about services or controllers. It is a fair baseline but model-specific; do not generalise it to stronger models.

## Caveats that must appear next to these numbers
* 28 test cases (19 violations): intervals are wide; one case moves an F1 by ~0.03.
* The scenarios, the ADR wording and the system-prompt guidance were written by us. The held-out-wording and minimal-prompt runs exist to test exactly that and have not been run.
* One small quantised model. Absolute scores are model-specific; the comparison between methods is fair because they share it.
* Density re-weighting (not new data): if only 10% of dependencies had a record, M5 would save ~65% of M3's calls (observed mix: 25%; at 100%: 10%).
