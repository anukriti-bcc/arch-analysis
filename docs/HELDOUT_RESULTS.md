# Held-out wording results (the blind test)

Same repositories as the primary benchmark (seed 7), ADR decision language rewritten. The held-out ADR text was not read by
anyone while M6 (code-only reader) or M7 (extract-then-compute) was written, and neither was developed against it. Run once with
the frozen code (freeze check passed on 12 files). Model: Qwen2.5 7B Instruct Q4_K_M. 60 cases. Files: `results/heldout`.

## Headline (test split, 28 targeted + conformant edges per case set; F1 with 95% CI)

| Method | F1 | LLM calls |
|---|---|---|
| M1 static | 0.809 (0.667-0.902) | 0 |
| M3 full hybrid | 0.857 (0.710-0.970) | 28 |
| M4 random selection (mean of 5) | 0.834 | 21 |
| M5 evidence-guided | 0.889 (0.759-0.976) | 21 |
| **M6 code-only ADR reader** | **0.973 (0.903-1.000)** | **0** |
| **M7 extract-then-compute** | **0.974 (0.903-1.000)** | **21** |

Paired M7 - M6: +0.001 (CI -0.081 to +0.081) on test; +0.022 (CI 0.000 to 0.073) on dev. M7 - M5: +0.085 (CI -0.027 to 0.210) test.
M7: 45 of 45 calls parsed, 0 fallbacks; grounding accepted all 12 extracted limit dates.

## Accuracy on the targeted dependency, by scenario (6 cases each, dev and test pooled)

| Scenario | M1 | M6 | M3 | M5 | M7 |
|---|---|---|---|---|---|
| A plain violation | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| B permanent exception | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| C grandfathered before cut-off | 0.00 | 1.00 | 0.83 | 0.83 | 1.00 |
| D grandfathered after cut-off | 1.00 | 0.67 | 0.33 | 0.33 | 1.00 |
| E reaffirms prohibition | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| F superseded | 1.00 | 1.00 | 0.80 | 1.00 | 1.00 |
| G passing mention | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| H temporary commit | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| J cited by commit only | 0.00 | 1.00 | 1.00 | 1.00 | 0.83 |
| K scope mismatch | 1.00 | 1.00 | 0.60 | 0.60 | 1.00 |

## Pre-registered robustness criteria (`docs/ANALYSIS_PLAN.md`)

| | Primary | Held-out | Replicates? |
|---|---|---|---|
| H1 M5 non-inferior to M3 | supported | supported (+0.032, CI 0.000 to 0.105) | yes |
| H2 M5 uses fewer calls than M3 | supported | supported (-7, CI -11 to -3) | yes |
| H3 M5 beats random selection | supported | supported (+0.055, CI 0.006 to 0.123) | yes |
| H4 history helps (M5 vs A1) | supported (+0.131, CI 0.027 to 0.267) | **not supported** (+0.039, CI -0.052 to 0.156) | **no** |
| H5 intent helps (M5 vs A2) | not run | not supported (+0.080, CI -0.066 to 0.240) | n/a |
| F1(M5, held-out) >= F1(M5, primary) - 0.10 | | 0.889 vs 0.973 = -0.084 | met, narrowly |

## What this means

1. **The LLM's value is conditional on how irregular the ADR text is.** On templated wording (primary) and on a mild paraphrase
   (held-out) a code-only reader written from general ADR conventions matches M7 at no cost. Only on the hard tier, written
   with that reader's lexicon in mind, does it fail (F1 0.588) while M7 holds (0.975). A synthetic benchmark cannot say where
   real ADRs sit on that spectrum.
2. **M7's contribution is robust where it was designed to help.** It beats M5 (the free-form LLM judgement) where dates matter
   (D: 6/6 vs 2/6 here; 18/18 vs 2/18 on the hard tier) and it does so without extra calls.
3. **H4 (history helps) does not replicate on held-out wording.** The case for evolution evidence rests on the hard tier and
   on scenario J.
4. Samples are small (60 cases); intervals are wide; only differences whose intervals exclude 0 are claims.
