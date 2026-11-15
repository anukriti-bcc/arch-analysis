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
When it is frozen (prompt `x2` with grounding = `x4`, unless the adoption rule rejects it and x2 is frozen as is; frozen at commit `04b3e70`, tag `m7-x4-frozen`), it is run **once** on three fresh seeds of the hard tier
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
| 2026-11-14 | **Diagnosis of the L/M regression (seed-7 dev, x2).** Two mechanical flaws in the extraction design, both visible in the model's own output: (1) for L01 and L02 the model reported the **ADR's own header date** as a limit (`introduced_on_or_before 2025-05-11`, the ADR's date), because the prompt showed the 'Date:' line and front matter; (2) for M01 and M03 it wrote that the ADR permits the access for another module and prohibits it for the flagged one, yet answered `covers: yes`, because the schema asked 'does it permit?' and 'does it cover this module?' as separate questions and the flagged module is *named* in the ADR. | Found by reading the extractions of 6 dev cases. |
| 2026-11-14 | **M7 prompt `x2` -> `x3`**: (a) the ADR's own metadata dates (front matter, 'Date:' lines) are stripped from what the model sees; (b) the `covers_this_dependency` field is removed and `decision` becomes one question about THIS module (permits / prohibits / does_not_address / unclear), with an explicit note that being named in an ADR does not mean the access is permitted for that module; (c) the commit-citation rule from x2 is kept. Resolution code and escalation policy unchanged. To be compared against x2 and M5 on the same development seeds 21 and 22 (144 cases) before anything is frozen. | Both fixes are general design corrections, not scenario tuning, but they were chosen after reading 6 dev cases, hence the larger development seeds. |
| 2026-11-14 | **Development seeds 21+22 (144 cases), prompt `x2`, as reported from the run:** M7 F1 0.964 (CI 0.936-0.988) vs M5 0.923 (0.880-0.955); paired M7 minus M5 = +0.041 (95% CI -0.001 to 0.087), calls identical (114). Per scenario: D 12/12 (M5 2/12), J 12/12 (M5 11/12), M 11/12 (M5 10/12), **L 6/12 (M5 11/12)**, all others 100%. 0 fallbacks. | The D result is robust at n=12. The overall F1 interval just touches zero. L is a real regression versus M5. |
| 2026-11-14 | **Prompt `x3` evaluated on the same 144 cases and REJECTED.** Pre-stated rule (F1 >= x2's 0.964; L and M >= 10/12; D and J >= 11/12; fallbacks <= 10%): x3 got F1 0.950, L 7/12, M 12/12, D 12/12, J 7/12 (x2: 12/12), fallbacks 1/114. Paired F1 x3 minus x2 = -0.014 (CI -0.05 to 0.02). Fails the rule on F1, L and J. **x2 remains the incumbent.** | Stripping the ADR's own date and merging 'covers' into the decision fixed M (11 to 12 of 12) but barely moved L (6 to 7 of 12), so the header-date flaw was not the main cause of L; and moving the commit-citation rule out of the scope field cost J five cases. |
| 2026-11-14 | **Iteration cap, fixed before looking at the failing L/J extractions.** At most ONE more prompt version (`x4`) may be tried on the development seeds 21+22. Adopt it only if it beats x2 on those same 144 cases: F1 >= 0.964, D >= 11/12, J >= 11/12, M >= 10/12 and L >= 8/12. Otherwise **freeze x2** and report mixed-decision scenarios (L) as a stated limitation with these numbers. The confirmation seeds 11-13 are run once, on the frozen version. | Prevents open-ended tuning on a development set (forking paths). |
| 2026-11-14 | **Diagnosis from the 144-case development run (extractions read, not guessed).** *x2, scenario L (6 wrong of 12):* in all six the model read the ADR correctly (`permits`, covers yes) and then wrote a limit `introduced_on_or_before <date>` although L's ADRs contain no limit. Checked against the regenerated benchmark: **the six reported dates equal the ADRs' own record dates exactly (6/6)**. *x3, scenario L (5 wrong):* limit hallucination disappeared (dates stripped) but the model answered `prohibits` while its own explanation said the ADR lets the module use the target ('... may use ... directly, prohibiting other modules'): an over-correction from the 'being named does not mean permitted' caution. *x3, scenario J (5 wrong):* four `does_not_address` despite the commit citation, one limit claimed with a null date. | Both x2 and x3 failures are extraction faults, and the x2 one is mechanical. Prompt wording moves results a lot at this model size, which is itself a finding. |
| 2026-11-14 | **x4 = the x2 prompt, unchanged, plus code-side grounding of the extracted limit date** (`ground_limit` in `analysis/semantic/extract.py`). A limit date is accepted only if it is written in the decision text; a date equal to the ADR's own record date and absent from the decision is rejected (limit becomes none); a date absent from the decision is replaced by the decision's single date, or left unresolved if there are none or several. Counts as the ONE further iteration allowed by the cap; the adoption rule is exactly the one fixed above (F1 >= 0.964, D >= 11/12, J >= 11/12, M >= 10/12, L >= 8/12, fallbacks <= 10%). x3 is archived as `experiments/archive/extract_x3_rejected.py`. Checks before any run: grounding accepts the real cut-off date in 48 of 48 C/D cases (hard seeds 7, 21, 22 and primary seed 7); the six real x2 failures resolve as justified (unit tests); 466 tests pass. Because x2's language-model answers are cached, the x4 development run needs few or no new calls. | A code-level correction of a measured failure mode, with no prompt change. **x4's development result is not independent evidence:** the six failing cases informed the check, so L improving on these 144 cases is expected by construction. Only the confirmation seeds 11-13 can show that it generalises. |
| 2026-11-16 | **x4 on the 144 development cases (seeds 21+22), as reported from the run. ADOPTION RULE: ALL SIX LINES PASS.** M7 x4 F1 0.989 (95% CI 0.973-1.000) vs M5 0.923 (0.880-0.955); paired M7 minus M5 = **+0.066 (95% CI 0.030 to 0.110)**; calls 114 vs 114; 114/114 parsed, 0 fallbacks. Targeted accuracy (of 12 unless noted), M5 vs x4: D 2 vs 12; J 11 vs 12; L 11 vs 12; M 10 vs 10; A 20/20, B, C, E 12/12, F, G, H, K 10/10 for both. Grounding actions on M7's extractions: no limit claimed 74, accepted 24, rejected 6 (the record-date copies), replaced or unresolved 0. Run in a fresh session (no cache), so x2/x3 columns were not available; x2's numbers are the ones logged above. | **Caveats.** (1) The development seeds were used for four prompt/resolution iterations, so 0.989 is optimistic. (2) L improving is expected by construction (the grounding was designed from those failures). (3) M is 10/12 under x4 against 11/12 under x2 and 10/12 for M5: one case, and I cannot attribute it from the printed output (M5's numbers reproduced exactly across sessions, so run-to-run model noise is not an obvious explanation). It is the only scenario where M7 is not above M5 and is watched in the confirmation. |
| 2026-11-16 | **M7 FROZEN as prompt x4 (the x2 prompt plus code-side grounding).** Code frozen at Git commit `04b3e70` (no code has changed since; later commits touch only docs and the notebook); tag `m7-x4-frozen`. SHA-256 of the 12 files that determine M7's behaviour (extract, prompts, llm client, escalation policy, aggregator, ADR parser, reader, evolution, pipeline, metrics, runner, combine tool) are in `docs/frozen_m7_x4_sha256.json`; the first confirmation cell recomputes them on the machine that runs the model and refuses to continue on any mismatch. Model: Qwen2.5 7B Instruct Q4_K_M via Ollama, temperature 0, context 4096. Confirmation criteria C1-C5 below are unchanged from when they were written. | The protocol asks for the freeze to be recorded before the confirmation run. Nothing about M7 may change between this row and the pooled verdict. |
| 2026-11-16 | **M7 CONFIRMATION RUN (frozen prompt x4, code commit `04b3e70`), as reported from the run: 216 fresh cases (hard tier, seeds 11, 12, 13), pooled. ALL FIVE PRE-REGISTERED CRITERIA PASS.** C1 scenario D accuracy 100% (M5 11%): PASS. C2 paired F1 M7 minus M5 = +0.079 (95% CI +0.042 to +0.121): PASS. C3 calls 171 vs 171: PASS. C4 non-D accuracy 0.965 vs M5 0.939: PASS. C5 fallbacks 0/171: PASS. Pooled F1: M7 0.975 (0.955-0.990), M5 0.896 (0.852-0.932), M3 0.892 (0.848-0.929), M1 0.800, M6 0.588. Paired: M7 minus M3 = +0.083 (0.045 to 0.126); M5 minus M3 = +0.004 (0.000 to 0.015) with 45 fewer calls (171 vs 216); M7 minus M6 = +0.387 (0.323 to 0.463). Weak spot: scenario M (mixed ADR, target prohibited) 0.61 for M7 (11/18) vs 0.67 for M5 and M3. Details and caveats: `docs/M7_CONFIRMATION.md`. | The verdict is reported as it came out. M7 was not changed between the freeze and this run (freeze check passed on 12 files). |
| 2026-11-16 | **Addition to the held-out-wording run:** M7 (`extract_compute`, frozen x4) is run on the held-out wording alongside the methods already planned. It did not exist when the plan was written, so no hypothesis about it was pre-registered; it is reported as exploratory-but-blind (never developed against that wording). The planned H1-H5 verdicts for M5 and the ablations are unchanged. As for M6, the held-out wording has still not been read or inspected by anyone while writing M6 or M7. | Held-out wording is the one place neither M6 nor M7 was ever tuned against. |

