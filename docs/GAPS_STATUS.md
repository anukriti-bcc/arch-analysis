# Status of the 14 gaps from the project assessment

The assessment (`project_assessment_gaps.md`) was written against the repository as it stood before M6, M7, the hard tier, the
held-out run and the confirmation seeds. This file records, gap by gap, what has changed and what has not. Dated: 2026-11-16.

**Summary: 3 fixed, 4 partly fixed, 6 not fixed (one of those, #6, is measured but not fixed), 1 deliberately excluded (the supervisor diary, which must be real).**

| # | Gap | Status | What changed / what remains |
|---|---|---|---|
| 1 | The evidence-guided policy is thin | **Partly fixed** | The *resolution* step was replaced (M7: the model extracts, code computes) and fixed the measured date failure (scenario D 2/18 -> 18/18). The *escalation* policy itself is unchanged: on the 216 confirmation cases M5 and M7 each make 171 calls against 72 that an oracle would need, and it still escalates every case with an active relevant ADR. Capture-rate and oracle-gap metrics now measure this (`experiments/metrics.py`). A scored policy with a call budget was not built. |
| 2 | No deterministic ADR baseline | **Fixed** | M6 (`analysis/intent/reader.py`), written from general ADR conventions, frozen, and run blind on the held-out wording: F1 0.973 with zero LLM calls. It answers "why an LLM at all?" honestly: on templated and mildly paraphrased wording the LLM adds nothing over it; on irregular wording (hard tier) it fails (0.588) while M7 holds (0.975). |
| 3 | Benchmark written alongside the policy; confirmatory runs not run | **Partly fixed** | Held-out wording run executed once, blind (`docs/HELDOUT_RESULTS.md`): H1-H3 replicate, **H4 (history helps) does not**, F1 criterion met narrowly. Fresh-seed confirmation of M7 (216 cases) done. Still synthetic and written by the team; the minimal-prompt sensitivity run has **not** been run; A2 was not run on the primary benchmark. |
| 4 | Low statistical power | **Fixed for the headline claim** | M7 minus M5 on 216 pooled fresh cases: +0.079 (95% CI +0.042 to +0.121). Intervals remain wide for the held-out comparisons (60 cases) and the primary test split (28). |
| 5 | M2 is easy to beat; only one model | **Not fixed** | M2 was re-run on the hard tier (F1 0.18, same pattern). No second model and no stronger LLM-only prompt. |
| 6 | ADR matching will over-fire on real repositories | **Measured, not fixed** | Now tested on 202 real ADRs (`docs/REAL_ADRS.md`): the type-words rule selects 0.5-6% of real ADRs per type pair, so over-firing is small in absolute terms; but it needs exact words and never matches plurals ('services', 'databases'), so it under-selects. The matcher is unchanged. `match_strength` exists in the M6 reader but the M5/M7 escalation still uses the old rule. |
| 7 | Code comments are never used as evidence | **Not fixed** | |
| 8 | Evolution is shallow | **Not fixed** | Per-dependency only; renames flagged not tracked; history truncated at 1000 commits. |
| 9 | Real-repository evidence does not test the research question | **Not fixed; partly informed** | Still sqlfluff only for conformance, with no ADR text and no LLM. What changed: a real-ADR corpus now shows that dependency-governing ADRs are rare (3-10% in a hand-read sample of 60) and that M6 could not read the six found. No language model has been run on real ADRs yet. |
| 10 | Narrow dependency scope | **Not fixed** | Direct Python imports; allowed/forbidden rules only. |
| 11 | Stack deviations from the synopsis | **Partly fixed** | **PostgreSQL: done** (`storage/postgres_store.py`, tested against a real PostgreSQL 16 server, including identical API behaviour to the memory store and persistence across restarts). **Docker: configured** (db + backend + frontend, healthchecks, volume) with a smoke script, but the containers have **not been run by the author**; static wiring tests and a process-level run of the same script pass. **Still open: TypeScript** (frontend is JavaScript). scikit-learn is used in the real-ADR agreement tool and the metrics cross-check tests, not in the main pipeline. |
| 12 | Supervisor diary empty | **Excluded** | Must be real entries by the team. |
| 13 | Pre-registration claim not provable | **Partly fixed** | The repository now has a Git history (first commit `642b2b1`, 2026-11-14, containing the plan), the plan's status table is filled in truthfully, M7's freeze is recorded with file hashes and a tag, and the order plan -> freeze -> confirmation -> held-out is visible in commits. Work before 2026-11-14 is not provable from Git, the primary run is exploratory by the plan's own account, and commit metadata comes from the machine that made the commits. |
| 14 | Docs stale | **Fixed** (except diary and report outline, left by request) | README, COMPLIANCE, PROGRESS, EXPERIMENTS, VIVA_DEMO counts and the notebook text updated. |

## Findings since the assessment that were not on its list

* **M7 is weak on mixed ADRs** that permit one module and forbid another (scenario M: 11 of 18). The errors are in the dangerous direction (a real
  violation called justified). A fix needs a new prompt version and fresh seeds.
* **The LLM's value is conditional on how irregular ADR text is** (see the table in `docs/HELDOUT_RESULTS.md`). Real ADR corpora are the missing evidence.
* **Prompt wording is fragile at this model size.** Three extraction prompt versions moved individual scenarios by up to 5 of 12 cases; the final fix was
  a code-side check rather than more prompt text (`docs/ANALYSIS_PLAN.md`, deviations log).
* **The product now matches the research:** the API/UI resolve escalated findings with extract-then-compute and show the extracted facts and the computed verdict.
* **Real ADRs rarely govern dependencies, and the ones that do are plain or irregular prose** (`docs/REAL_ADRS.md`). This bounds how often ADR-based
  conformance checking applies and shows that the held-out result (M6 matches M7) does not carry over to real dependency rules (n = 6, single rater).
* **The frozen M6 reader has a defect on MADR-format ADRs** (it reads "Decision Drivers" as the decision). Documented, not changed.
