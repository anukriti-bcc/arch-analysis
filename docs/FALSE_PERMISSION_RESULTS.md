# False-permission probe on real ADRs: results

Plan: `docs/FALSE_PERMISSION_PLAN.md` (pre-registered, tag `false-permission-frozen`, 12 frozen files verified before the run).
Run: Kaggle GPU, Qwen2.5 7B Instruct Q4 via Ollama (`arch-judge`), temperature 0, run once on 2026-11-23. Raw output: `results/real_adrs_false_permission/`
(`results.csv`, `summary.json`, `summary.md`, `adjudication_template.csv`).

## Result

**Band (pre-registered, raw M7, unadjudicated): LOW.** 0 of 44 primary ADRs produced a dangerous extraction (Wilson 95% CI 0.0 to 8.0%).

| Quantity | Result |
|---|---|
| Dangerous false permission (permits and covers yes), raw M7 | 0/44 (95% CI 0.0 to 8.0%) |
| Misleading (attributed another way) | 0/44 |
| Any false attribution | 0/44 |
| Parse failures / errors | 0/49 |
| Dangerous after the attribution check | 0/44 (the check had nothing to reject) |
| Selected by the relevance matcher | 1/44 (2.3%) |
| M8 routes: structural / code reader / model | 44 / 0 / 0 |
| Pipeline false-justified (M8 routing + attribution) | 0/44 (0.0 to 8.0%) |
| Inactive control (3 rejected, 2 superseded) | 0/5 dangerous or misleading |

All 49 replies were `does_not_address` with `covers = no`. The adjudication template contains only its header row: there was no dangerous or misleading
row to judge, so adjudicated and unadjudicated counts are the same (0).

## What this supports

On real ADR text that does not govern dependencies, the frozen M7 extraction did not invent a permission in this sample. In plain terms: with 44 ADRs
and no failures, the true rate of this failure on similar text is unlikely to exceed about 8% (95% confidence). This is not a claim that the rate is zero.

## Critical reading

1. **The pipeline figure is not independent evidence.** M8 routed all 44 cases to the structural path without a model call. The relevance matcher
   selected one ADR (govuk-infrastructure 0020, Crossplane, on component types), and even that case went to the structural route. The "0/44 pipeline
   false-justified" is therefore close to true by construction. The informative number is the model-level one (0/44 raw).
2. **No positive control.** Every reply was "does not address". A model that always answered "does not address" would score identically. The probe
   measures one failure direction (false permission) and says nothing about whether the model reads a real permission correctly. That side rests on the
   7-case study, which found one real false permission (C05) and otherwise did not beat the always-violation baseline.
3. **The dependencies are synthetic and unrelated by construction.** Six fixed type pairs, Python-style paths, no Git history. The test is whether an
   unrelated ADR is ignored. Genuinely ambiguous ADRs (soft wording, permissions in odd places) are not covered.
4. **Replies look templated.** Each explanation is a single sentence restating the dependency ("The ADR does not address ..."), 54 to 70 output tokens.
   This is consistent with the model matching on topic words rather than reading closely. It is a plausible reading, not a demonstrated one.
5. **Forced-in ADRs are a stress test, and the stress was mild.** Even with the ADR forced into the prompt, the model declined every time, so the
   routing protection was not needed to get this result.
6. **Sample limits.** 44 ADRs from 9 repositories (the tenth, AlphaYu/adnc, contributed only the excluded empty file); several repositories contribute
   5 to 7 ADRs, so ADRs are not independent. One pass at temperature 0: the model is not bit-for-bit repeatable across sessions, so the interval is a
   sampling interval for these 44 ADRs, not a model-noise interval. One 7B quantised model. Q1 labels are AI-drafted and team-verified.
7. **Pre-registration held.** Thresholds and pair list were fixed before the run. The run printed the band immediately, so the team saw it before
   adjudication; this had no effect because there was nothing to adjudicate.

## Claim this result supports

"On 44 real, active ADRs that do not govern dependencies, the frozen extraction produced no false permission (0/44, 95% CI 0 to 8%), and no
misleading attribution. This bounds one failure direction on one model; it does not show that the model correctly reads ADRs that do permit a
dependency."
