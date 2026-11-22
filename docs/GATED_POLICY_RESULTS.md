# Readability-gated escalation (policy v2, method M8): design and results

Closes the largest gap in `docs/GAPS_STATUS.md` (#1, "the escalation policy is thin") and part of #6 (ADR matching). **Confirmed on fresh seeds 41-43 (section at the end): all pre-registered criteria P1-P8 passed.**
Frozen at tag `m8-gated-frozen` (file hashes: `docs/frozen_m8_gated_sha256.json`). Model answers are those already recorded for
M7 (Qwen2.5 7B Q4); M8 only changes WHICH findings are escalated (`experiments/replay_policy.py`, checked against a live run in
`tests/test_gated_policy.py`). Replayed rows: `results/m8_replay/`.

## Why v1 was thin, and why "ask the reader" does not fix it

v1 (M5/M7) escalates every finding with an active relevant ADR: 171 calls on the 216 confirmation cases against 72 that an oracle
needs. The obvious repair, "escalate only when the code reader (M6) is unsure", fails: on the hard tier M6 returned a clear
verdict for 198 of 216 findings and only 56% of those were right. It is **confidently wrong**, not just unsure (negation,
"rejected ... acceptable", a cut-off written as "up to the freeze on <date>", a decision about several modules).

## The policy

Each structural violation is routed cheapest-first (`analysis/policy/gated.py`):

| Route | When | Verdict | Cost |
|---|---|---|---|
| `direct_structural` | no active ADR is about this dependency (none / all inactive / only shares type words), and history is quiet | violation | none |
| `direct_code` | an active ADR names or describes both ends AND its code reading passes every readability gate | code's reading | none |
| `escalate` | otherwise: reading unclear or a gate fails, or history signals ambiguity | M7: model extracts, code computes | 1 call |

Readability gates (`analysis/intent/readability.py`), each failing safe: `G_clear`, `G_section`, `G_polarity` (prohibiting and
permitting cues together), `G_negation` (a "permits" reading containing a negation), `G_anchor` (the stance sentence names both
ends), `G_temporal` (a date not explained by a recognised cut-off clause, or temporal wording without one), `G_conditions`,
`G_subject` (decision also names other modules), `G_single` (competing active ADRs). A new scope test `scope_of` also accepts an
ADR that *describes* both ends ("the analytics service reads from the database connection module"); the v1 matcher needed file
names, which the first version of this policy wrongly relied on (it lost 4 of 6 justified scenario-B cases before the fix).

## Results (all with the same recorded model answers; "silent error" = a verdict made without the model that is wrong)

| Data | Status of the data | M7 F1 / calls | **M8 F1 / calls** | Silent errors |
|---|---|---|---|---|
| Hard tier, seeds 11-13 (216 cases) | not used to design the gates (M6's per-scenario accuracy had been seen) | 0.975 / 171 | **0.975 / 156** (paired calls -15, 95% CI -22 to -8; F1 difference exactly 0) | 0 of 60 |
| Held-out wording, test split | blind: ADR text not read | 0.974 / 21 | **0.974 / 17** | 0 of 25 (dev+test) |
| Held-out wording, dev split | blind | 1.000 / 24 | **1.000 / 18** | |
| Hard tier, seeds 21+22 (144 cases) | **development** (gates designed here) | 0.989 / 114 | 0.989 / 104 | 0 |
| Primary wording, test split (resolver = M5) | **development** (exploratory) | M5 0.973 / 21 | 1.000 / 5 | 0 |

On the confirmation seeds M8 also improves the policy-quality metrics: calls over the oracle 99 -> 84, escalation yield 0.42 ->
0.46, capture of static false positives 1.00 (nothing the model was needed for was skipped). M8 minus M5 is +0.079 F1
(0.042 to 0.121) with 15 fewer calls; M8 minus M3 is +0.083 with 60 fewer calls.

## What this does and does not show (state these in the report)

* **The saving depends on how regular the ADR text is, and on adversarial text it is small** (9% on the hard tier, which was
  written to defeat lexical reading). The safety property (no silent errors on any data) held everywhere; the saving is the
  part that varies.
* **The gates are too conservative on paraphrased wording.** On the blind held-out wording `direct_code` was never used, although
  the code-only reader M6 scores F1 0.973 there with zero calls; M8 spends 17 calls to reach the same F1. Aggregate gate counts on
  the 30 escalated held-out findings: `G_temporal` 17, `G_negation` 12, `G_conditions` 6, `G_clear` 6, `G_anchor` 6. Temporal and
  negation wording are the false-alarm sources. The frozen code was NOT changed after seeing this; a v2.1 that relaxes them would
  be a new method needing fresh seeds. Primary wording (24 of 30 gate passes) is not evidence otherwise: the gates were tuned on it.
* **Risk ranking does not help.** `apply_budget` (keep the k riskiest escalations) was tested on the 104 escalations of the dev seeds:
  ordering by failed gates, or by presence of a permitting cue, is not reliably better than random (e.g. F1 0.969 vs 0.937 at 80
  calls but 0.901 vs 0.881 at 50 and worse than random at 20 and 90). The budget knob is built and defaults off; no claim is made for it.
* The gates were designed after reading the code reader's errors on the hard dev seeds (21, 22) and on primary seed 7, and three
  rounds of changes were made there (logged in `ANALYSIS_PLAN.md`). Only the confirmation seeds and the held-out wording are
  independent of that, and the latter is a single 60-case draw.
* Still one model, a generated benchmark, and (gap #9) no run on real ADR text.

## Scored top-k escalation (hand-weighted or learned): tested, and why it is not the method

Proposal: score each finding from evidence metadata (ADR match strength, status, date relation, commit signals, reintroduction,
age), escalate the top k, sweep k, compare with random. Tested offline on all 480 structural violations of the five hard-tier
seeds plus primary and held-out wording (`experiments/scorer_features.py`, `experiments/scorer_study.py`, output in
`results/scorer_study/`). Target: "the static flag is a false positive" (ground truth justified); the candidate set is the 375
findings the v1 policy escalates, 156 of them justified. Every scorer is judged on **pooled leave-one-scenario-out** predictions
(a scorer never sees the scenario it scores), so a scorer that decodes the generator is exposed.

| Scorer | AUC | Calls to capture 95% of false positives |
|---|---|---|
| Oracle | 1.00 | 156 |
| Random | 0.50 | about 356 |
| Hand-weighted metadata score, fixed in advance | 0.73 | 323 |
| Logistic regression, all features | 0.60 | 324 |
| Logistic regression, metadata only | 0.49 | 323 |
| Gradient boosting (depth 2), all features | 0.32 | 368 |

* A learned scorer trained on dev and tested on seeds 11-13 looks excellent (AUC 0.96, held-out wording 1.00) and collapses to
  0.32-0.60 when it must score a scenario it never saw. That is the generator-decoding failure, measured.
* Metadata alone is at chance (0.49) inside the candidate set: whether an ADR actually permits a dependency is in its text, not in
  its status, date or the commit message. The one signal that carries it is reading the text, which is what the gates and the
  model do. So a metadata top-k can save at most about 9% of calls at 95% capture (hand-weighted 323 vs random 356), while M8's
  routing saves about 9% on the hard tier with no silent errors and a safety property a ranking cannot give (a ranking has no
  notion of "decide without the model").
* Consequence for the project: the contribution is the readability gate, and "metadata cannot say when a model is needed" is a
  finding in its own right. scikit-learn is used here for a genuine experiment rather than decoration.
* Ties: many findings share a score (all strong-ADR cases), so top-k is arbitrary among them; the capture figures above average
  over random tie-breaks.
* Not adopted from the proposals: passing computed date/status/scope facts to the model (M7 already does: scenario D is 18 of 18;
  "3 of 6" was M5 before M7), and keeping the M6 baseline (already in every table).

## Mixed decisions: the stance-attribution check (`M8_gated_attr`)

M7 and M8 got 11 of 18 on scenario M. All 7 errors had the same shape: the model reported "permits, covers this module" for a
decision that permits one module and requires the flagged one to keep to the rule. `analysis/semantic/attribution.py` checks this
in code: when the decision names other modules, a permission must be stated in a clause about this module.

| Seeds 11-13 (216 cases) | F1 | Scenario M correct | Calls |
|---|---|---|---|
| M8 (frozen) | 0.975 | 11 / 18 | 156 |
| M8 + attribution check | **1.000** | **18 / 18** | 156 |

Seven readings were rejected, none for a justified dependency. On dev seeds 21+22 it fixed both errors (F1 0.989 -> 1.000). The
held-out wording has no mixed decisions, so there it changes nothing (F1 0.988 both) and is not evidence for the fix. A decision
that only says "it may" in a following sentence, or permits in words outside the cue list, would be read as a violation; that is
the safe direction and the main limit. The generator uses one template for mixed decisions, so this shows the check works on that
shape; the fresh-seed run (P6 to P8) and the real-ADR run (B) are the tests of generality.

## Fresh-seed confirmation (seeds 41, 42, 43; 216 cases; run once with the frozen code)

Criteria were written in `ANALYSIS_PLAN.md` before the run. Output saved in `results/m8_fresh_seeds/` (printed notebook output; raw predictions not retained, see its README).

| Method | F1 (95% CI) | Calls |
|---|---|---|
| M1 static | 0.800 (0.751 to 0.845) | 0 |
| M6 deterministic ADR reader | 0.588 (0.510 to 0.655) | 0 |
| M3 full hybrid | 0.894 (0.851 to 0.930) | 216 |
| M5 evidence-guided (v1 policy) | 0.914 (0.877 to 0.946) | 171 |
| M7 extract-then-compute (v1 policy) | 0.968 (0.946 to 0.987) | 171 |
| **M8 gated routing** | **0.972 (0.951 to 0.989)** | **156** |
| **M8 + attribution check** | **0.990 (0.976 to 1.000)** | **156** |

| Criterion | Result |
|---|---|
| P1 no regression, M8 minus M7 F1, lower bound above -0.02 | PASS, +0.004 (95% CI +0.000 to +0.011) |
| P2 saving, M8 minus M7 calls, upper bound below 0 | PASS, -15 (CI -22 to -8): 156 vs 171 |
| P3 safety, at most 2 wrong verdicts made without the model | PASS, 0 wrong of 60 |
| P4 capture of static false positives at least 95% | PASS, 1.000 (72 of 72) |
| P5 replay equals live for M8 | PASS, 0 differences |
| P6 scenario M at least 16 of 18 with the attribution check | PASS, 18 of 18 (M8 and M7: 13 of 18) |
| P7 no harm: no scenario loses more than 1 case, no justified case rejected | PASS, none lost, 0 rejected |
| P8 replay equals live for the attribution check | PASS, 0 differences |

What the data supports:
* The gated routing keeps M7's accuracy while making 15 fewer calls (8.8%), and its extra decisions made without the model were all correct. M8 was
  marginally better than M7 (+0.004): in scenario K (ADR about a different module) the description-aware scope test skips a call on which the model had been wrong.
* The attribution check fixes the mixed-decision weakness: scenario M 13 of 18 to 18 of 18, with no scenario made worse. Overall 213 of 216 correct; the
  3 remaining errors are in scenario G (1 of 15, passing mention) and J (2 of 18, ADR cited only by the commit).
* M7/M8 against M3 and M5: F1 0.97 against 0.89 and 0.91, with 60 and 15 fewer calls respectively. Intervals are unpaired here; the scenario table shows why:
  M3 and M5 misread grandfathering after a cut-off (scenario D: 4 of 18) where the extract-then-compute split gets 18 of 18.
* The deterministic reader alone (M6) is confidently wrong on this tier (F1 0.588), the motivation for gates instead of "escalate when unsure".

Limits that remain: the benchmark is generated, the hard tier shares a generator family with the seeds the gates were developed on (21, 22), only one 7B model was
used, the saving on adversarial text is modest, the gates were too conservative on the blind held-out paraphrase (see above), and none of this has been run on real
ADR text beyond the 7-case study.

