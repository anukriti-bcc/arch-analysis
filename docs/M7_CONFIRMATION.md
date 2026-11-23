# M7 (extract-then-compute): confirmation results

Frozen method: prompt `x4` (the `x2` extraction prompt plus code-side grounding of the extracted limit date), code commit
`04b3e70`, tag `m7-x4-frozen`, file hashes in `docs/frozen_m7_x4_sha256.json`. Model: Qwen2.5 7B Instruct Q4_K_M (Ollama,
temperature 0, context 4096). Data: **hard tier, benchmark seeds 11, 12, 13 (216 cases), run once, pooled** with
`experiments/combine_runs.py`. These seeds were not used for any development. Numbers below are as reported from the run.

## What M7 is

M5's escalation policy is unchanged. For an escalated finding with an active relevant ADR, the model **extracts facts** (what
the decision says about this module; whether the permission has a date limit, and which calendar date) and **code computes
the verdict** by comparing the limit with the Git introduction date. The prompt never shows the model the introduction date,
the snapshot date or the age. A grounding check in code accepts an extracted limit date only if it is written in the decision
text. Same number of LLM calls as M5.

## Pre-registered criteria (`docs/ANALYSIS_PLAN.md`) - all pass

| | Criterion | Result |
|---|---|---|
| C1 | Scenario D accuracy >= 80% | **100%** (M5: 11%) |
| C2 | Paired F1, M7 minus M5, lower 95% bound > 0 | **+0.079 (95% CI +0.042 to +0.121)** |
| C3 | LLM calls <= 105% of M5 | 171 vs 171 |
| C4 | Non-D accuracy within 0.05 of M5 | 0.965 vs 0.939 |
| C5 | Fallbacks <= 10% of escalations | 0 of 171 |

## Headline (216 cases, pooled)

| Method | F1 (95% CI) | LLM calls |
|---|---|---|
| M1 static | 0.800 (0.751-0.845) | 0 |
| M6 code-only ADR reader | 0.588 (0.510-0.655) | 0 |
| M3 full hybrid | 0.892 (0.848-0.929) | 216 |
| M5 evidence-guided | 0.896 (0.852-0.932) | 171 |
| **M7 extract-then-compute** | **0.975 (0.955-0.990)** | **171** |

Paired F1: M7 - M5 +0.079 (0.042 to 0.121); M7 - M3 +0.083 (0.045 to 0.126); M7 - M1 +0.175 (0.126 to 0.226);
M7 - M6 +0.387 (0.323 to 0.463); M5 - M3 +0.004 (0.000 to 0.015), i.e. M5 matches M3 with 45 fewer calls (21%).

## Accuracy on the targeted dependency, by scenario (pooled over 3 seeds)

| Scenario | M3 | M5 | M6 | **M7** |
|---|---|---|---|---|
| A plain violation (30) | 1.00 | 1.00 | 1.00 | 1.00 |
| B permanent exception (18) | 1.00 | 1.00 | 0.00 | 1.00 |
| C grandfathered, before cut-off (18) | 1.00 | 1.00 | 1.00 | 1.00 |
| **D grandfathered, after cut-off (18)** | 0.11 | 0.11 | 0.00 | **1.00** |
| E negated proposal (18) | 1.00 | 1.00 | 0.00 | 1.00 |
| F superseded (15) | 0.93 | 1.00 | 1.00 | 1.00 |
| G passing mention (15) | 1.00 | 1.00 | 0.00 | 1.00 |
| H temporary commit (15) | 1.00 | 1.00 | 1.00 | 1.00 |
| J cited by commit only (18) | 0.89 | 0.89 | 0.00 | 1.00 |
| K scope mismatch (15) | 0.93 | 0.93 | 1.00 | 1.00 |
| L mixed, target permitted (18) | 0.83 | 0.83 | 1.00 | 1.00 |
| **M mixed, target prohibited (18)** | 0.67 | 0.67 | 0.00 | **0.61** |

## How the method was developed (so the result can be judged)

Prompt iteration used separate development seeds (7 dev split, then 21 and 22; 144 cases). Three prompt/resolution versions were
tried; x3 was rejected under a pre-stated rule and is archived (`experiments/archive/extract_x3_rejected.py`); x4 was adopted
under a pre-stated rule (all six lines passed) and then frozen before this run. The chronology and every decision are in the
deviations log of `docs/ANALYSIS_PLAN.md`.

## Limits

* **Scenario M is a real weakness.** When an ADR permits one module and forbids another, M7 sometimes reads the permission as
  applying to the flagged (forbidden) module: 7 of 18 wrong, in the dangerous direction (a real violation called justified).
  A fix would be a new prompt version and would need fresh seeds to confirm; this confirmation set is spent.
* **Synthetic benchmark, written by the project team.** The seeds differ in entities, dates and wording variants, but they come from
  the same generator templates, so this shows stability across draws, not generalisation to unseen ADR phrasing. The held-out
  wording run is the test of that.
* **One small quantised model.** Not shown for any other model.
* **The date problem is partly "use code for arithmetic".** The finding is a design principle (let the model extract and the code
  compute), not that the model became better at dates.
* **Limits must be calendar dates written in the decision.** Relative limits ("within 30 days of this record") are not handled,
  and grounding discards an extracted date that is not written in the text.
