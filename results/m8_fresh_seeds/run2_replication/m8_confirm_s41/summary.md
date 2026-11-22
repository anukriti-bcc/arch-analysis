# Experiment summary

Model: `arch-judge`; prompt v1 (variant: full); benchmark wording: hard

## Split: dev

| method | split | precision | recall | f1 | f1_ci_low | f1_ci_high | false_positive_rate | llm_calls | input_tokens | output_tokens | llm_latency_s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1_static | dev | 0.684 | 1.000 | 0.813 | 0.722 | 0.899 | 0.050 | 0 | 0 | 0 | 0.000 |
| M3_full_hybrid | dev | 1.000 | 0.885 | 0.939 | 0.872 | 1.000 | 0.000 | 38 | 26047 | 2960 | 106.400 |
| M5_evidence_guided | dev | 1.000 | 0.885 | 0.939 | 0.872 | 1.000 | 0.000 | 30 | 21060 | 2344 | 86.351 |
| M6_deterministic_adr | dev | 0.700 | 0.538 | 0.609 | 0.463 | 0.762 | 0.025 | 0 | 0 | 0 | 0.000 |
| M7_extract_compute | dev | 1.000 | 0.962 | 0.980 | 0.929 | 1.000 | 0.000 | 30 | 25432 | 2202 | 88.295 |
| M8_gated | dev | 1.000 | 0.962 | 0.980 | 0.929 | 1.000 | 0.000 | 27 | 22829 | 2000 | 79.997 |
| M8_gated_attr | dev | 1.000 | 0.962 | 0.980 | 0.929 | 1.000 | 0.000 | 27 | 22829 | 2000 | 79.997 |

## Split: test

| method | split | precision | recall | f1 | f1_ci_low | f1_ci_high | false_positive_rate | llm_calls | input_tokens | output_tokens | llm_latency_s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1_static | test | 0.647 | 1.000 | 0.786 | 0.653 | 0.885 | 0.056 | 0 | 0 | 0 | 0.000 |
| M3_full_hybrid | test | 1.000 | 0.818 | 0.900 | 0.793 | 0.976 | 0.000 | 34 | 23285 | 2718 | 97.196 |
| M5_evidence_guided | test | 1.000 | 0.864 | 0.927 | 0.851 | 0.978 | 0.000 | 27 | 19042 | 2169 | 79.690 |
| M6_deterministic_adr | test | 0.647 | 0.500 | 0.564 | 0.388 | 0.733 | 0.028 | 0 | 0 | 0 | 0.000 |
| M7_extract_compute | test | 1.000 | 0.955 | 0.977 | 0.923 | 1.000 | 0.000 | 27 | 23078 | 1951 | 78.523 |
| M8_gated | test | 1.000 | 0.955 | 0.977 | 0.923 | 1.000 | 0.000 | 25 | 21348 | 1816 | 72.990 |
| M8_gated_attr | test | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 25 | 21348 | 1816 | 72.990 |

## Paired comparison: a minus b (95% case-level bootstrap)

M5 against every other method; M7 against M5, M3, M6 and M1 (M7 minus M5 is the clean test of extract-then-compute).

| split | a | b | metric | a_value | b_value | delta | ci_low | ci_high |
|---|---|---|---|---|---|---|---|---|
| dev | M5_evidence_guided | M1_static | f1 | 0.939 | 0.812 | 0.126 | 0.010 | 0.225 |
| dev | M5_evidence_guided | M1_static | false_positive_rate | 0.000 | 0.050 | -0.050 | -0.068 | -0.030 |
| dev | M5_evidence_guided | M1_static | llm_calls | 30.000 | 0.000 | 30.000 | 24.475 | 34.000 |
| dev | M5_evidence_guided | M3_full_hybrid | f1 | 0.939 | 0.939 | 0.000 | 0.000 | 0.000 |
| dev | M5_evidence_guided | M3_full_hybrid | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M5_evidence_guided | M3_full_hybrid | llm_calls | 30.000 | 38.000 | -8.000 | -13.525 | -4.000 |
| dev | M5_evidence_guided | M6_deterministic_adr | f1 | 0.939 | 0.609 | 0.330 | 0.190 | 0.477 |
| dev | M5_evidence_guided | M6_deterministic_adr | false_positive_rate | 0.000 | 0.025 | -0.025 | -0.041 | -0.008 |
| dev | M5_evidence_guided | M6_deterministic_adr | llm_calls | 30.000 | 0.000 | 30.000 | 24.475 | 34.000 |
| test | M5_evidence_guided | M1_static | f1 | 0.927 | 0.786 | 0.141 | 0.004 | 0.283 |
| test | M5_evidence_guided | M1_static | false_positive_rate | 0.000 | 0.056 | -0.056 | -0.079 | -0.033 |
| test | M5_evidence_guided | M1_static | llm_calls | 27.000 | 0.000 | 27.000 | 22.000 | 31.000 |
| test | M5_evidence_guided | M3_full_hybrid | f1 | 0.927 | 0.900 | 0.027 | 0.000 | 0.102 |
| test | M5_evidence_guided | M3_full_hybrid | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M5_evidence_guided | M3_full_hybrid | llm_calls | 27.000 | 34.000 | -7.000 | -12.000 | -3.000 |
| test | M5_evidence_guided | M6_deterministic_adr | f1 | 0.927 | 0.564 | 0.363 | 0.205 | 0.540 |
| test | M5_evidence_guided | M6_deterministic_adr | false_positive_rate | 0.000 | 0.028 | -0.028 | -0.046 | -0.007 |
| test | M5_evidence_guided | M6_deterministic_adr | llm_calls | 27.000 | 0.000 | 27.000 | 22.000 | 31.000 |
| dev | M7_extract_compute | M5_evidence_guided | f1 | 0.980 | 0.939 | 0.042 | -0.022 | 0.118 |
| dev | M7_extract_compute | M5_evidence_guided | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M7_extract_compute | M5_evidence_guided | llm_calls | 30.000 | 30.000 | 0.000 | 0.000 | 0.000 |
| dev | M7_extract_compute | M3_full_hybrid | f1 | 0.980 | 0.939 | 0.042 | -0.022 | 0.118 |
| dev | M7_extract_compute | M3_full_hybrid | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M7_extract_compute | M3_full_hybrid | llm_calls | 30.000 | 38.000 | -8.000 | -13.525 | -4.000 |
| dev | M7_extract_compute | M6_deterministic_adr | f1 | 0.980 | 0.609 | 0.372 | 0.236 | 0.528 |
| dev | M7_extract_compute | M6_deterministic_adr | false_positive_rate | 0.000 | 0.025 | -0.025 | -0.041 | -0.008 |
| dev | M7_extract_compute | M6_deterministic_adr | llm_calls | 30.000 | 0.000 | 30.000 | 24.475 | 34.000 |
| dev | M7_extract_compute | M1_static | f1 | 0.980 | 0.812 | 0.168 | 0.065 | 0.264 |
| dev | M7_extract_compute | M1_static | false_positive_rate | 0.000 | 0.050 | -0.050 | -0.068 | -0.030 |
| dev | M7_extract_compute | M1_static | llm_calls | 30.000 | 0.000 | 30.000 | 24.475 | 34.000 |
| test | M7_extract_compute | M5_evidence_guided | f1 | 0.977 | 0.927 | 0.050 | -0.024 | 0.146 |
| test | M7_extract_compute | M5_evidence_guided | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M7_extract_compute | M5_evidence_guided | llm_calls | 27.000 | 27.000 | 0.000 | 0.000 | 0.000 |
| test | M7_extract_compute | M3_full_hybrid | f1 | 0.977 | 0.900 | 0.077 | -0.011 | 0.207 |
| test | M7_extract_compute | M3_full_hybrid | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M7_extract_compute | M3_full_hybrid | llm_calls | 27.000 | 34.000 | -7.000 | -12.000 | -3.000 |
| test | M7_extract_compute | M6_deterministic_adr | f1 | 0.977 | 0.564 | 0.413 | 0.250 | 0.607 |
| test | M7_extract_compute | M6_deterministic_adr | false_positive_rate | 0.000 | 0.028 | -0.028 | -0.046 | -0.007 |
| test | M7_extract_compute | M6_deterministic_adr | llm_calls | 27.000 | 0.000 | 27.000 | 22.000 | 31.000 |
| test | M7_extract_compute | M1_static | f1 | 0.977 | 0.786 | 0.191 | 0.066 | 0.318 |
| test | M7_extract_compute | M1_static | false_positive_rate | 0.000 | 0.056 | -0.056 | -0.079 | -0.033 |
| test | M7_extract_compute | M1_static | llm_calls | 27.000 | 0.000 | 27.000 | 22.000 | 31.000 |
| dev | M8_gated | M7_extract_compute | f1 | 0.980 | 0.980 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated | M7_extract_compute | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated | M7_extract_compute | llm_calls | 27.000 | 30.000 | -3.000 | -6.000 | -1.000 |
| dev | M8_gated | M5_evidence_guided | f1 | 0.980 | 0.939 | 0.042 | -0.022 | 0.118 |
| dev | M8_gated | M5_evidence_guided | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated | M5_evidence_guided | llm_calls | 27.000 | 30.000 | -3.000 | -6.000 | -1.000 |
| dev | M8_gated | M3_full_hybrid | f1 | 0.980 | 0.939 | 0.042 | -0.022 | 0.118 |
| dev | M8_gated | M3_full_hybrid | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated | M3_full_hybrid | llm_calls | 27.000 | 38.000 | -11.000 | -17.000 | -6.475 |
| dev | M8_gated | M6_deterministic_adr | f1 | 0.980 | 0.609 | 0.372 | 0.236 | 0.528 |
| dev | M8_gated | M6_deterministic_adr | false_positive_rate | 0.000 | 0.025 | -0.025 | -0.041 | -0.008 |
| dev | M8_gated | M6_deterministic_adr | llm_calls | 27.000 | 0.000 | 27.000 | 21.000 | 31.525 |
| dev | M8_gated | M1_static | f1 | 0.980 | 0.812 | 0.168 | 0.065 | 0.264 |
| dev | M8_gated | M1_static | false_positive_rate | 0.000 | 0.050 | -0.050 | -0.068 | -0.030 |
| dev | M8_gated | M1_static | llm_calls | 27.000 | 0.000 | 27.000 | 21.000 | 31.525 |
| test | M8_gated | M7_extract_compute | f1 | 0.977 | 0.977 | 0.000 | 0.000 | 0.000 |
| test | M8_gated | M7_extract_compute | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M8_gated | M7_extract_compute | llm_calls | 25.000 | 27.000 | -2.000 | -4.525 | 0.000 |
| test | M8_gated | M5_evidence_guided | f1 | 0.977 | 0.927 | 0.050 | -0.024 | 0.146 |
| test | M8_gated | M5_evidence_guided | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M8_gated | M5_evidence_guided | llm_calls | 25.000 | 27.000 | -2.000 | -4.525 | 0.000 |
| test | M8_gated | M3_full_hybrid | f1 | 0.977 | 0.900 | 0.077 | -0.011 | 0.207 |
| test | M8_gated | M3_full_hybrid | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M8_gated | M3_full_hybrid | llm_calls | 25.000 | 34.000 | -9.000 | -13.000 | -5.000 |
| test | M8_gated | M6_deterministic_adr | f1 | 0.977 | 0.564 | 0.413 | 0.250 | 0.607 |
| test | M8_gated | M6_deterministic_adr | false_positive_rate | 0.000 | 0.028 | -0.028 | -0.046 | -0.007 |
| test | M8_gated | M6_deterministic_adr | llm_calls | 25.000 | 0.000 | 25.000 | 21.000 | 29.000 |
| test | M8_gated | M1_static | f1 | 0.977 | 0.786 | 0.191 | 0.066 | 0.318 |
| test | M8_gated | M1_static | false_positive_rate | 0.000 | 0.056 | -0.056 | -0.079 | -0.033 |
| test | M8_gated | M1_static | llm_calls | 25.000 | 0.000 | 25.000 | 21.000 | 29.000 |
| dev | M8_gated_attr | M8_gated | f1 | 0.980 | 0.980 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated_attr | M8_gated | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated_attr | M8_gated | llm_calls | 27.000 | 27.000 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated_attr | M7_extract_compute | f1 | 0.980 | 0.980 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated_attr | M7_extract_compute | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dev | M8_gated_attr | M7_extract_compute | llm_calls | 27.000 | 30.000 | -3.000 | -6.000 | -1.000 |
| test | M8_gated_attr | M8_gated | f1 | 1.000 | 0.977 | 0.023 | 0.000 | 0.077 |
| test | M8_gated_attr | M8_gated | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M8_gated_attr | M8_gated | llm_calls | 25.000 | 25.000 | 0.000 | 0.000 | 0.000 |
| test | M8_gated_attr | M7_extract_compute | f1 | 1.000 | 0.977 | 0.023 | 0.000 | 0.077 |
| test | M8_gated_attr | M7_extract_compute | false_positive_rate | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| test | M8_gated_attr | M7_extract_compute | llm_calls | 25.000 | 27.000 | -2.000 | -4.525 | 0.000 |

## Escalation quality: which findings were sent to the LLM

A static false positive is a structural violation the benchmark labels justified. `capture_rate` is the share of them escalated; `random_expected_capture` is what random choice at the same escalation rate would capture; `calls_over_oracle` is how many more calls were made than an all-knowing policy needs.

| method | split | static_false_positives | escalated | captured_fp | capture_rate | random_expected_capture | capture_lift | escalation_yield | calls_over_oracle |
|---|---|---|---|---|---|---|---|---|---|
| M3_full_hybrid | dev | 12.000 | 38.000 | 12.000 | 1.000 | 1.000 | 0.000 | 0.316 | 26.000 |
| M3_full_hybrid | test | 12.000 | 34.000 | 12.000 | 1.000 | 1.000 | 0.000 | 0.353 | 22.000 |
| M5_evidence_guided | dev | 12.000 | 30.000 | 12.000 | 1.000 | 0.789 | 0.211 | 0.400 | 18.000 |
| M5_evidence_guided | test | 12.000 | 27.000 | 12.000 | 1.000 | 0.794 | 0.206 | 0.444 | 15.000 |
| M7_extract_compute | dev | 12.000 | 30.000 | 12.000 | 1.000 | 0.789 | 0.211 | 0.400 | 18.000 |
| M7_extract_compute | test | 12.000 | 27.000 | 12.000 | 1.000 | 0.794 | 0.206 | 0.444 | 15.000 |
| M8_gated | dev | 12.000 | 27.000 | 12.000 | 1.000 | 0.711 | 0.289 | 0.444 | 15.000 |
| M8_gated | test | 12.000 | 25.000 | 12.000 | 1.000 | 0.735 | 0.265 | 0.480 | 13.000 |
| M8_gated_attr | dev | 12.000 | 27.000 | 12.000 | 1.000 | 0.711 | 0.289 | 0.444 | 15.000 |
| M8_gated_attr | test | 12.000 | 25.000 | 12.000 | 1.000 | 0.735 | 0.265 | 0.480 | 13.000 |

## If fewer dependencies had a decision record (re-weighted, not new data)

| split | method | adr_density | f1 | llm_calls_per_case | calls_saved_vs_m3 |
|---|---|---|---|---|---|
| dev | M3_full_hybrid | 0.100 | 0.995 | 1.000 | 0.000 |
| dev | M5_evidence_guided | 0.100 | 0.995 | 0.427 | 0.573 |
| dev | M3_full_hybrid | 0.250 | 0.986 | 1.000 | 0.000 |
| dev | M5_evidence_guided | 0.250 | 0.986 | 0.506 | 0.494 |
| dev | M3_full_hybrid | 0.500 | 0.968 | 1.000 | 0.000 |
| dev | M5_evidence_guided | 0.500 | 0.968 | 0.637 | 0.363 |
| dev | M3_full_hybrid | 0.750 | 0.943 | 1.000 | 0.000 |
| dev | M5_evidence_guided | 0.750 | 0.943 | 0.769 | 0.231 |
| dev | M3_full_hybrid | 1.000 | 0.909 | 1.000 | 0.000 |
| dev | M5_evidence_guided | 1.000 | 0.909 | 0.900 | 0.100 |
| test | M3_full_hybrid | 0.100 | 0.992 | 1.000 | 0.000 |
| test | M5_evidence_guided | 0.100 | 0.994 | 0.350 | 0.650 |
| test | M3_full_hybrid | 0.250 | 0.979 | 1.000 | 0.000 |
| test | M5_evidence_guided | 0.250 | 0.984 | 0.446 | 0.554 |
| test | M3_full_hybrid | 0.500 | 0.950 | 1.000 | 0.000 |
| test | M5_evidence_guided | 0.500 | 0.963 | 0.606 | 0.394 |
| test | M3_full_hybrid | 0.750 | 0.909 | 1.000 | 0.000 |
| test | M5_evidence_guided | 0.750 | 0.933 | 0.766 | 0.234 |
| test | M3_full_hybrid | 1.000 | 0.846 | 1.000 | 0.000 |
| test | M5_evidence_guided | 1.000 | 0.889 | 0.926 | 0.074 |

## Decision accuracy on the targeted dependency, by scenario

| scenario | M1_static | M3_full_hybrid | M5_evidence_guided | M6_deterministic_adr | M7_extract_compute | M8_gated | M8_gated_attr |
|---|---|---|---|---|---|---|---|
| A_plain_violation | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| B_adr_permanent_exception | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| C_adr_grandfathered_before_cutoff | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| D_adr_grandfathered_after_cutoff | 1.000 | 0.167 | 0.167 | 0.000 | 1.000 | 1.000 | 1.000 |
| E_adr_reaffirms_prohibition | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| F_adr_superseded | 1.000 | 0.800 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| G_adr_passing_mention | 1.000 | 1.000 | 1.000 | 0.000 | 0.800 | 0.800 | 0.800 |
| H_temporary_became_permanent | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| J_adr_cited_by_commit_only | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| K_adr_scope_mismatch | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| L_adr_mixed_permits_target | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| M_adr_mixed_prohibits_target | 1.000 | 0.833 | 0.833 | 0.000 | 0.833 | 0.833 | 1.000 |
