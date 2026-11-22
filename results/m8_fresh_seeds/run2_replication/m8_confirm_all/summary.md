# Pooled confirmation run

Runs: m8_confirm_s41, m8_confirm_s42, m8_confirm_s43 (216 cases pooled into split `confirm`).

| method | split | precision | recall | f1 | f1_ci_low | f1_ci_high | false_positive_rate | llm_calls |
|---|---|---|---|---|---|---|---|---|
| M1_static | confirm | 0.667 | 1.000 | 0.800 | 0.751 | 0.845 | 0.053 | 0 |
| M3_full_hybrid | confirm | 0.983 | 0.806 | 0.885 | 0.842 | 0.925 | 0.001 | 216 |
| M5_evidence_guided | confirm | 0.984 | 0.840 | 0.906 | 0.867 | 0.939 | 0.001 | 171 |
| M6_deterministic_adr | confirm | 0.676 | 0.521 | 0.588 | 0.510 | 0.655 | 0.026 | 0 |
| M7_extract_compute | confirm | 0.993 | 0.951 | 0.972 | 0.951 | 0.989 | 0.001 | 171 |
| M8_gated | confirm | 0.993 | 0.951 | 0.972 | 0.951 | 0.989 | 0.001 | 156 |
| M8_gated_attr | confirm | 0.993 | 0.993 | 0.993 | 0.982 | 1.000 | 0.001 | 156 |

## Paired comparison: a minus b (95% case-level bootstrap)

| a | b | metric | a_value | b_value | delta | ci_low | ci_high |
|---|---|---|---|---|---|---|---|
| M5_evidence_guided | M1_static | f1 | 0.906 | 0.800 | 0.106 | 0.049 | 0.165 |
| M5_evidence_guided | M1_static | false_positive_rate | 0.001 | 0.053 | -0.051 | -0.061 | -0.042 |
| M5_evidence_guided | M1_static | llm_calls | 171.000 | 0.000 | 171.000 | 159.000 | 183.000 |
| M5_evidence_guided | M3_full_hybrid | f1 | 0.906 | 0.885 | 0.021 | 0.004 | 0.041 |
| M5_evidence_guided | M3_full_hybrid | false_positive_rate | 0.001 | 0.001 | 0.000 | 0.000 | 0.000 |
| M5_evidence_guided | M3_full_hybrid | llm_calls | 171.000 | 216.000 | -45.000 | -57.000 | -33.000 |
| M5_evidence_guided | M6_deterministic_adr | f1 | 0.906 | 0.588 | 0.318 | 0.256 | 0.390 |
| M5_evidence_guided | M6_deterministic_adr | false_positive_rate | 0.001 | 0.026 | -0.025 | -0.033 | -0.017 |
| M5_evidence_guided | M6_deterministic_adr | llm_calls | 171.000 | 0.000 | 171.000 | 159.000 | 183.000 |
| M7_extract_compute | M5_evidence_guided | f1 | 0.972 | 0.906 | 0.065 | 0.031 | 0.105 |
| M7_extract_compute | M5_evidence_guided | false_positive_rate | 0.001 | 0.001 | -0.001 | -0.003 | 0.001 |
| M7_extract_compute | M5_evidence_guided | llm_calls | 171.000 | 171.000 | 0.000 | 0.000 | 0.000 |
| M7_extract_compute | M3_full_hybrid | f1 | 0.972 | 0.885 | 0.086 | 0.046 | 0.132 |
| M7_extract_compute | M3_full_hybrid | false_positive_rate | 0.001 | 0.001 | -0.001 | -0.003 | 0.001 |
| M7_extract_compute | M3_full_hybrid | llm_calls | 171.000 | 216.000 | -45.000 | -57.000 | -33.000 |
| M7_extract_compute | M6_deterministic_adr | f1 | 0.972 | 0.588 | 0.383 | 0.319 | 0.462 |
| M7_extract_compute | M6_deterministic_adr | false_positive_rate | 0.001 | 0.026 | -0.026 | -0.033 | -0.018 |
| M7_extract_compute | M6_deterministic_adr | llm_calls | 171.000 | 0.000 | 171.000 | 159.000 | 183.000 |
| M7_extract_compute | M1_static | f1 | 0.972 | 0.800 | 0.172 | 0.124 | 0.224 |
| M7_extract_compute | M1_static | false_positive_rate | 0.001 | 0.053 | -0.052 | -0.061 | -0.043 |
| M7_extract_compute | M1_static | llm_calls | 171.000 | 0.000 | 171.000 | 159.000 | 183.000 |
| M8_gated | M7_extract_compute | f1 | 0.972 | 0.972 | 0.000 | 0.000 | 0.000 |
| M8_gated | M7_extract_compute | false_positive_rate | 0.001 | 0.001 | 0.000 | 0.000 | 0.000 |
| M8_gated | M7_extract_compute | llm_calls | 156.000 | 171.000 | -15.000 | -22.000 | -8.000 |
| M8_gated | M5_evidence_guided | f1 | 0.972 | 0.906 | 0.065 | 0.031 | 0.105 |
| M8_gated | M5_evidence_guided | false_positive_rate | 0.001 | 0.001 | -0.001 | -0.003 | 0.001 |
| M8_gated | M5_evidence_guided | llm_calls | 156.000 | 171.000 | -15.000 | -22.000 | -8.000 |
| M8_gated | M3_full_hybrid | f1 | 0.972 | 0.885 | 0.086 | 0.046 | 0.132 |
| M8_gated | M3_full_hybrid | false_positive_rate | 0.001 | 0.001 | -0.001 | -0.003 | 0.001 |
| M8_gated | M3_full_hybrid | llm_calls | 156.000 | 216.000 | -60.000 | -73.000 | -47.000 |
| M8_gated | M6_deterministic_adr | f1 | 0.972 | 0.588 | 0.383 | 0.319 | 0.462 |
| M8_gated | M6_deterministic_adr | false_positive_rate | 0.001 | 0.026 | -0.026 | -0.033 | -0.018 |
| M8_gated | M6_deterministic_adr | llm_calls | 156.000 | 0.000 | 156.000 | 143.000 | 169.000 |
| M8_gated | M1_static | f1 | 0.972 | 0.800 | 0.172 | 0.124 | 0.224 |
| M8_gated | M1_static | false_positive_rate | 0.001 | 0.053 | -0.052 | -0.061 | -0.043 |
| M8_gated | M1_static | llm_calls | 156.000 | 0.000 | 156.000 | 143.000 | 169.000 |
| M8_gated_attr | M8_gated | f1 | 0.993 | 0.972 | 0.021 | 0.007 | 0.040 |
| M8_gated_attr | M8_gated | false_positive_rate | 0.001 | 0.001 | 0.000 | 0.000 | 0.000 |
| M8_gated_attr | M8_gated | llm_calls | 156.000 | 156.000 | 0.000 | 0.000 | 0.000 |
| M8_gated_attr | M7_extract_compute | f1 | 0.993 | 0.972 | 0.021 | 0.007 | 0.040 |
| M8_gated_attr | M7_extract_compute | false_positive_rate | 0.001 | 0.001 | 0.000 | 0.000 | 0.000 |
| M8_gated_attr | M7_extract_compute | llm_calls | 156.000 | 171.000 | -15.000 | -22.000 | -8.000 |

## Escalation quality

| method | static_false_positives | escalated | captured_fp | capture_rate | random_expected_capture | capture_lift | escalation_yield | calls_over_oracle |
|---|---|---|---|---|---|---|---|---|
| M3_full_hybrid | 72.000 | 216.000 | 72.000 | 1.000 | 1.000 | 0.000 | 0.333 | 144.000 |
| M5_evidence_guided | 72.000 | 171.000 | 72.000 | 1.000 | 0.792 | 0.208 | 0.421 | 99.000 |
| M7_extract_compute | 72.000 | 171.000 | 72.000 | 1.000 | 0.792 | 0.208 | 0.421 | 99.000 |
| M8_gated | 72.000 | 156.000 | 72.000 | 1.000 | 0.722 | 0.278 | 0.462 | 84.000 |
| M8_gated_attr | 72.000 | 156.000 | 72.000 | 1.000 | 0.722 | 0.278 | 0.462 | 84.000 |

## Decision accuracy on the targeted dependency, by scenario

| scenario | M1_static | M3_full_hybrid | M5_evidence_guided | M6_deterministic_adr | M7_extract_compute | M8_gated | M8_gated_attr |
|---|---|---|---|---|---|---|---|
| A_plain_violation | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| B_adr_permanent_exception | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| C_adr_grandfathered_before_cutoff | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| D_adr_grandfathered_after_cutoff | 1.000 | 0.167 | 0.167 | 0.000 | 1.000 | 1.000 | 1.000 |
| E_adr_reaffirms_prohibition | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |
| F_adr_superseded | 1.000 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| G_adr_passing_mention | 1.000 | 1.000 | 1.000 | 0.000 | 0.933 | 0.933 | 0.933 |
| H_temporary_became_permanent | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| J_adr_cited_by_commit_only | 0.000 | 1.000 | 1.000 | 0.000 | 0.944 | 0.944 | 0.944 |
| K_adr_scope_mismatch | 1.000 | 0.933 | 0.933 | 1.000 | 1.000 | 1.000 | 1.000 |
| L_adr_mixed_permits_target | 0.000 | 0.889 | 0.889 | 1.000 | 1.000 | 1.000 | 1.000 |
| M_adr_mixed_prohibits_target | 1.000 | 0.611 | 0.611 | 0.000 | 0.667 | 0.667 | 1.000 |
