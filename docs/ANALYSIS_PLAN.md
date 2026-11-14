# Analysis plan (written before the confirmatory run)

**Purpose.** Fix, in advance, what each claim means and what result would count for or against it, so the
conclusions cannot be shaped by the numbers afterwards. **Commit this file to Git before running the
held-out-wording evaluation; the commit timestamp is the evidence that it came first.** Any later change goes in the
"Deviations" section at the bottom, with a date and a reason, never as a silent edit.

## Honest status of the data (fill in truthfully)

| Question | Answer |
|---|---|
| Date and commit hash at which this plan was committed | |
| Has anyone on the team looked at the primary run's `test`-split results before this was written? | yes / no |
| Has the held-out-wording run (`--wording heldout`) been executed or inspected? | yes / no |
| Were prompts or the policy changed after looking at `test` results? | yes / no (if yes, say what, below) |

**Facts already established (recorded so they are not reconstructed from memory later).**
* The primary run (`results/primary_exploratory/`, model Qwen2.5 7.6B Q4_K_M) was executed and its dev **and test** results were seen before this plan was committed. It is therefore **exploratory**.
* Its response cache contains exactly 514 entries, which equals the 514 distinct calls of that run, and all 514 are still served by today's prompts. So no prompt variant other than the current one was sent through that cache, and no prompt was changed after the results were seen.
* The held-out-wording run and the minimal-prompt run have **not** been executed.
* The `M5` policy and prompts are unchanged since the run. (If the date-facts feature in the Deviations log is added, that changes.)

**How to read the answers.** If the primary run's test results have already been seen, that run is *exploratory*: it
motivated the plan and cannot confirm it. The **held-out-wording run is then the confirmatory run**, because its
wordings were not used in any prompt or policy decision. Say exactly that in the report. If nobody has looked at either,
both are confirmatory. Do not claim more than the truthful answers above support.

## Fixed before the run

* **Model:** one model for every method (name and digest recorded in `run_config.json`).
* **Prompts and policy:** frozen. Prompt variant `full` is the main one; `minimal` is a sensitivity run.
* **Data:** the benchmark with seed 7 (`primary` wording, and `heldout` wording on the same repositories).
* **Primary metric:** F1 for the positive class "genuine violation", on the `test` split.
  Secondary: false-positive rate, precision, recall, LLM calls, tokens, LLM latency, fallbacks.
* **Uncertainty:** 95% case-level bootstrap intervals; method comparisons are *paired* (same resampled cases).
* **Failed calls:** counted, never dropped. A method whose unparseable-or-failed-call rate exceeds 10% is reported as unreliable.

## Hypotheses and what counts as support

"Supported" = the 95% interval lies entirely on the predicted side. "Not supported" = the interval includes the null.
"Contradicted" = the interval lies entirely on the opposite side. All three outcomes are reported.

| # | Claim | Comparison (`test`, paired) | Supported if |
|---|---|---|---|
| H1 | The evidence-guided method keeps detection quality of the full hybrid | M5 vs M3, F1 | lower end of the interval for (M5 − M3) is above **−0.05** (non-inferiority margin) |
| H2 | …while using fewer LLM calls | M5 vs M3, LLM calls | upper end of the interval for (M5 − M3) is **below 0** |
| H3 | Evidence-guided selection beats chance at the same budget | M5 vs M4 (mean of seeds), F1 | lower end of the interval is **above 0** |
| H4 | Evolution evidence helps | M5 vs A1 (no history), F1 | lower end of the interval is **above 0** |
| H5 | Intent evidence helps | M5 vs A2 (no intent), F1 | lower end of the interval is **above 0** |
| H6 | Structural pre-checking helps | M5 vs M2 (LLM-only), F1 and LLM calls | F1 not worse (as H1) **and** fewer calls (as H2) |
| H7 | Structure alone over-reports | M1 vs M5, false-positive rate | M1 is higher, interval above 0 |

**Robustness criteria (reported whatever the outcome):**

* *Held-out wording.* For each of H1–H5, does the same verdict (supported / not / contradicted) hold on `heldout`?
  Additionally, F1(M5, heldout) ≥ F1(M5, primary) − 0.10.
* *Prompt sensitivity.* If F1(M5) under the `minimal` prompt is more than **0.15 below** the `full` prompt, the report must say that
  performance depends on guidance written with these scenarios in mind.
* *ADR density.* Report calls saved vs M3 at 10%, 25%, 50%, 100%. This is a re-weighting of existing results, not new data.

## Exploratory (no pre-set criterion; label as such)

Per-scenario accuracy; the prediction inspector's failure analysis; the sqlfluff real-repository case study; any
comparison not listed above.

## What we will NOT claim

* Accuracy on real repositories. The benchmark is generated and authored by us.
* That the escalation policy is optimal, or learned: it is a hand-written rule list.
* That agreement with the reference tool on sqlfluff validates the research question; the contracts are shared by construction.
* Anything about languages other than Python, or dependencies other than direct imports.

## Deviations (append only; date and reason for each)

| Date | What changed | Why |
|---|---|---|
| 2026-11 | Primary run executed and inspected before this plan was committed; classified exploratory (see `docs/PRIMARY_RESULTS.md`) | the plan was written after the data existed; the held-out run is the confirmatory one |
| 2026-11-14 | Added baseline **M6 `deterministic_adr`** (`analysis/intent/reader.py`): a code-only reader of the same evidence M5 sees (ADR status, scope strength, Decision-section cues, date clauses compared in code). Added metrics **capture rate / escalation yield / calls over oracle** and a capture-curve helper (`experiments/metrics.py`). | An examiner can ask why an LLM is needed at all; M6 is the strongest no-LLM baseline on the same evidence. The new metrics measure how well a policy chooses *which* findings to escalate, which hit/miss F1 alone cannot show. |
| 2026-11-14 | **Provenance of M6 (read before interpreting it).** M6 was written after the authors had seen sample ADR texts of the *primary* wording, and was debugged against the **dev** split only (one fix: an "introduced after D is NOT covered" sentence was misread as a plain prohibition). It was NOT run on the primary test split or on held-out wording. M6's primary-wording results are therefore optimistic by construction and are **not independent evidence**. M6 is frozen at the commit that contains this row; its held-out-wording run is the fair test. | The reader was designed from general ADR conventions (Nygard/MADR sections, several date formats), not from the held-out phrasing, which was deliberately not read while writing it. |
| 2026-11-14 | Added a **hard wording tier** (`--wording hard`, `experiments/benchmark/hard_wording.py`, `docs/HARD_TIER.md`): same labels and repositories, harder-to-read ADRs, plus two scenarios (L, M) that exist only in this tier. M6 was run once on it, frozen, with no LLM (F1 0.61 dev / 0.56 test; exploratory). | The primary wording is fully readable by code (M6 F1 = 1.0 on dev), so it cannot show where an LLM is needed. **Provenance:** the tier was written knowing M6's lexicon, so M6's failures there are partly by construction; it is an exploratory tier, not a blind test. The held-out wording stays the blind test. |
| 2026-11-14 | Hard-tier LLM run executed and inspected (`results/hard_tier_qwen7b`, M2 in `..._m2`). Finding: every LLM method scored 0 of 6 on scenario D (after-cutoff grandfathering): the model read the ADR and then invented the date comparison. | Exploratory by definition: the hard tier was designed and inspected before this run's analysis. Motivates M7. |
| 2026-11-14 | Added **M7 `extract_compute`** (`analysis/semantic/extract.py`, prompt version `x1`): the LLM extracts decision, scope and date limit from the ADR without being shown any date; code compares the limit with the Git introduction date. Escalation policy is M5's, unchanged; same number of calls. History-only escalations (no active ADR) use M5's review prompt. Not run on any model yet at the time of this entry. | The D failure above. One change at a time, so that M7 minus M5 isolates it. |

## M7 confirmation protocol (written 2026-11-14, before any M7 result exists)

**Data.** Every case of the hard tier at benchmark seed 7 has been seen, so it cannot confirm anything. M7 may be
iterated on the dev split of seed 7 (prompt version `x1`, then `x2` ... each logged above with a date and a reason).
When it is frozen (prompt version `x2`; record the Git commit here: `________`), it is run **once** on three fresh seeds of the hard tier
(11, 12, 13; 216 cases), pooled with `experiments.combine_runs` into split `confirm`. Model and prompt versions must
match across the runs (the tool refuses to pool otherwise).

**Criteria, fixed now** (all computed on the pooled `confirm` split; outcome reported whatever it is):

* **C1 (the point of M7).** Accuracy on scenario D, pooled over the three seeds, is at least 80% (M5 scored 0%).
* **C2 (net effect).** Paired F1, M7 minus M5: the 95% interval's lower bound is above 0.
* **C3 (no new cost).** M7's LLM calls are at most 5% above M5's.
* **C4 (no regression).** Accuracy on the non-D targeted scenarios, pooled, is within 0.05 of M5's.
* **C5 (extraction is reliable).** Labelled fallbacks (unparseable reply, unclear scope, limit without a date) are at most 10%
  of M7's escalations.

**What would count against M7:** C1 failing means the model cannot extract a date from this wording; C4 failing means
extraction is worse than free-form judgement elsewhere. Both would be reported as findings.

**Known limits, stated in advance.** Dates must be written as calendar dates in the ADR text (a relative limit such as
"within 30 days of this record" is not handled and becomes a labelled fallback or is read as no limit). One model
(Qwen2.5 7B, Q4). The hard tier is authored by us.
| 2026-11-14 | **M7 dev run, prompt `x1`** (hard tier, seed 7, dev split, 38 cases): F1 0.963 vs M5 0.902; calls identical (30); 30/30 parsed, 0 fallbacks. Scenario D 3/3 (M5 0/3): the computed notes compare the extracted freeze date with the Git date correctly. Scenario J fell 0.67 to 0.33 (3 cases): for J01 and J03 the model extracted `covers_this_dependency: no`, judging scope from the ADR's description and ignoring that the introducing commit cites it. M5 also misses J03, so M5 and M7 differ on one case. | Dev inspection, as the protocol allows. |
| 2026-11-14 | **M7 prompt `x1` -> `x2`**: one rule added to the scope field: an ADR cited by the introducing commit counts as covering the dependency, even when it describes the code by purpose rather than by file name; "no" is reserved for a decision that names or describes a different module or expressly excludes this one. EXTRACT_VERSION bumped. Changed after looking at 3 dev cases of one scenario, so dev cannot confirm it. | Fixes the J weakness found above. General evidence rule (a commit citation is evidence of coverage), but it mirrors scenario J, so the fresh seeds are the real test and the minimal-prompt critique applies. |
| 2026-11-14 | **M7 dev run, prompt `x2`** (same 38 dev cases): F1 0.923 (x1: 0.963, M5: 0.902). J recovered (0.33 -> 1.00) but the mixed-decision scenarios fell: L 1.00 -> 0.33, M 1.00 -> 0.33. Net worse than x1 on dev. | Three cases per scenario cannot choose between prompt versions (one case moves a score by 0.33). |
| 2026-11-14 | **Development seeds added: hard tier, seeds 21 and 22 (144 cases).** Prompt iteration for M7 now uses these, not the 38-case seed-7 dev split. Confirmation seeds stay 11, 12, 13 and are not to be run until M7 is frozen. | Larger dev set (12 cases per scenario per two seeds) so that prompt choices are not decided by single cases. These seeds are used for development and can no longer confirm anything. |

