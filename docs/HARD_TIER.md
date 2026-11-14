# Hard wording tier

**Why it exists.** In the primary wording a code-only reader (baseline M6) resolves every targeted case: F1 = 1.0 on
dev. A benchmark on which plain code scores 100% cannot show where an LLM is needed. The hard tier keeps the same
repositories, scenarios and ground-truth labels and changes only how the decision records are written, plus two
scenarios that exist only here. Generate it with `--wording hard`.

| Phenomenon (all are ways real ADRs vary) | Scenarios |
|---|---|
| a *rejected alternative* quoted inside a permitting decision | B, F |
| scope given by description, not by file names | B (half the cases) |
| permission worded outside any keyword list ("cleared to", "comfortable with") | J |
| a date cut-off introduced by an unusual phrase ("up to the freeze on ...") | C, D |
| a negated proposal ("was not approved") | E |
| a permission about something else in the same ADR | G |
| one ADR deciding for two modules | L (target permitted), M (target prohibited) |

A, H have no principal ADR and K keeps its primary wording as a control. 72 cases (the primary 60 plus 12).
The primary benchmark is byte-identical with or without this tier (checked by hash and by `tests/test_hard_tier.py`).

## What has been run

Only the code-only baseline M6, once, frozen, on all 72 cases (exploratory; no LLM):

| Scenario | M6 correct | Why |
|---|---|---|
| A, H, K, F | all | no ADR / weak scope / superseded status: code is enough |
| C | 6/6 | permissive cue found; the date phrase is not parsed, so it permits everything |
| D | 0/6 | same reason: the phrase is not parsed, so the after-cutoff dependency is permitted |
| B, J | 0/6 | "rejected" inside a permission reads as a prohibition; no cue word found / scope only by description |
| E | 0/6 | "allow ... was not approved": the permission cue fires, the negation is not understood |
| G | 0/6 | "acceptable" in an unrelated sentence reads as a permission |
| L / M | 6/6 / 0/6 | "must keep going through the layer" has no negation word, so M6 permits both: chance, with a permit bias |

M6 overall on this tier: F1 0.61 (dev), 0.56 (test), against 1.0 on the primary dev split.

## How to read this (important)

* **The tier was written by someone who knew M6's lexicon.** Uniform failure of M6 on B, D, E, G, J, M is therefore
  partly by construction. It shows that a keyword reader is brittle under paraphrase, which is true of any keyword
  reader; it does **not** show that an LLM succeeds. That needs the LLM runs below.
* A stronger code reader (negation scope, per-module attribution, more cue words, quarter and relative dates) would
  solve more of this tier. An arms race of rules versus language is the honest framing; the result to report is
  how the LLM methods do on the same cases, not the size of M6's drop.
* The **held-out wording** remains the blind test. M6 was frozen before it and has not been run on it.

## LLM results (Qwen2.5 7B Q4_K_M, benchmark seed 7; exploratory)

Run on Kaggle; files in `results/hard_tier_qwen7b` (core methods) and `results/hard_tier_qwen7b_m2`. 465 of 465 calls parsed, no errors. Test split, 34 cases:

| Method | F1 | LLM calls |
|---|---|---|
| M1 static | 0.786 | 0 |
| M6 code-only reader | 0.564 | 0 |
| M3 full hybrid | 0.872 | 34 |
| **M5 evidence-guided** | **0.900** | **27** |
| M2 LLM-only | 0.184 | 238 |

Paired (test): M5 minus M6 = +0.336 (95% CI 0.183 to 0.518); M5 minus M3 = +0.028 (0.000 to 0.095) with 7 fewer calls (-12 to -3); M5 minus A1 (no history) = +0.090 (0.020 to 0.190).

Accuracy on the targeted dependency, dev and test pooled:

| Scenario | M6 | M3 | M5 | A1 (no history) |
|---|---|---|---|---|
| A plain | 1.00 | 1.00 | 1.00 | 1.00 |
| B permanent exception | 0.00 | 1.00 | 1.00 | 1.00 |
| C grandfathered, before cut-off | 1.00 | 1.00 | 1.00 | 1.00 |
| **D grandfathered, after cut-off** | 0.00 | **0.00** | **0.00** | **0.00** |
| E negated proposal | 0.00 | 1.00 | 1.00 | 1.00 |
| F superseded | 1.00 | 0.60 | 1.00 | 1.00 |
| G passing mention | 0.00 | 1.00 | 1.00 | 1.00 |
| H temporary commit | 1.00 | 1.00 | 1.00 | 1.00 |
| J cited by commit only | 0.00 | 0.83 | 0.83 | 0.00 |
| K scope mismatch | 1.00 | 1.00 | 1.00 | 1.00 |
| L mixed, target permitted | 1.00 | 0.83 | 0.83 | 0.83 |
| M mixed, target prohibited | 0.00 | 0.83 | 0.83 | 0.67 |

Reading: (1) paraphrased ADRs need a language model (B, E, G, M); (2) history evidence is what links a commit-cited ADR (J); (3) a code status check beats the model on superseded records (F); (4) **the model cannot compare dates**: for D it wrote that the dependency was introduced before the freeze when it was introduced after. M7 (`docs/ANALYSIS_PLAN.md`, confirmation protocol) targets this.

## Still to run (needs the model; roughly 125 new calls for the core methods)

    python -m experiments.benchmark.generate --out ../datasets/benchmark/generated_hard --wording hard
    python -m experiments.run_experiments --benchmark ../datasets/benchmark/generated_hard \
        --methods static,deterministic_adr,full_hybrid,evidence_guided,no_history,no_intent,generic_selective \
        --out ../results/hard --seeds 5

M2 (LLM-only) would add about 500 calls; run it last if time allows (`--methods llm_only --out ../results/hard_m2`).
