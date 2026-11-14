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
