# M8 / M8+attribution fresh-seed verdict (criteria fixed in docs/ANALYSIS_PLAN.md before the run)

```
PASS  P1 no regression (M8 - M7 paired F1, lower bound > -0.02)  delta +0.000 (95% CI +0.000 to +0.000); F1 M7 0.972, M8 0.972, M8+attr 0.993
PASS  P2 saving (M8 - M7 paired calls, upper bound < 0)  delta -15.0 (95% CI -22.0 to -8.0); calls M7 171, M8 156
PASS  P3 safety (at most 2 wrong verdicts made without the model)  0 wrong of 60 verdicts made without the model
PASS  P4 capture (M8 escalates >= 95% of static false positives)  capture 1.000 (72 of 72)
PASS  P5 replay = live for M8  0 predictions differ across 3 runs
PASS  P6 attribution fix (scenario M correct >= 16 of 18)  M8+attr 18 of 18; M8 12; M7 12
PASS  P7 no harm (no scenario loses > 1 case; no justified case rejected)  scenarios losing >1: none; justified cases rejected: 0
PASS  P8 replay = live for the attribution check  0 predictions differ
```

## Correct per scenario (targeted+conformant violations)

```
method                             M1_static  M3_full_hybrid  M5_evidence_guided  M6_deterministic_adr  M7_extract_compute  M8_gated  M8_gated_attr
scenario                                                                                                                                           
A_plain_violation                         30              30                  30                    30                  30        30             30
B_adr_permanent_exception                  0              18                  18                     0                  18        18             18
C_adr_grandfathered_before_cutoff          0              18                  18                    18                  18        18             18
D_adr_grandfathered_after_cutoff          18               3                   3                     0                  18        18             18
E_adr_reaffirms_prohibition               18              18                  18                     0                  18        18             18
F_adr_superseded                          15              10                  15                    15                  15        15             15
G_adr_passing_mention                     15              15                  15                     0                  14        14             14
H_temporary_became_permanent              15              15                  15                    15                  15        15             15
J_adr_cited_by_commit_only                 0              18                  18                     0                  17        17             17
K_adr_scope_mismatch                      15              14                  14                    15                  15        15             15
L_adr_mixed_permits_target                 0              16                  16                    18                  18        18             18
M_adr_mixed_prohibits_target              18              11                  11                     0                  12        12             18
```
