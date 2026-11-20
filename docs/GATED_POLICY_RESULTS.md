# Readability-gated escalation (policy v2, method M8): design and results

Closes the largest gap in `docs/GAPS_STATUS.md` (#1, "the escalation policy is thin") and part of #6 (ADR matching).
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
