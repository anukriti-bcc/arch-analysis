# False-permission probe on real ADRs: pre-registered plan

Written 2026-11-23, **before any model output exists for this experiment**. Addresses the largest open gap (the
language model has never been measured on real ADR text beyond 7 hand-built cases). Code: `backend/experiments/real_adrs/false_permission.py`;
tests: `backend/tests/test_false_permission.py`; freeze record: `docs/frozen_false_permission_sha256.json`.

## The question

In the pipeline a flagged dependency is a violation by default. An ADR can change that only by convincing the extractor that it *permits* the
dependency. The dangerous failure is therefore the model reading an ADR that is **unrelated** to the dependency as a permission, which hides a
real violation (it happened in the 7-case study: C05, "modular monolith" read as permitting a cross-module reference). The benchmark cannot show
this, because its ADRs are short and always relevant.

> **On real ADR text that does not govern dependencies, how often does the frozen M7 extraction invent a permission, and how often would the
> product as configured (M8 routing + attribution check) call a real violation "justified"?**

## Population (and a correction to the first proposal)

Source: the team-verified labels (`results/real_adrs/annotation_sheet_verified.csv`), Q1 = "no" (the ADR does not govern dependencies).
The first proposal said 47. The sheet has **50** such ADRs, and the pipeline's own rules shrink that:

| Stratum | n | Why |
|---|---|---|
| **primary** | **44** | active ADRs (not rejected or superseded) that have text |
| inactive control | 5 | 3 rejected, 2 superseded: policy rule I2 means the pipeline never sends these to the model. Reported apart, never in the primary rate |
| excluded | 1 | R006 (adnc ADR-004) is an empty file (0 bytes): nothing to read |

All 50 texts were fetched at their pinned commits and match the SHA-256 in the manifest.

## Design

* **Pairing.** Each ADR gets one flagged dependency from six fixed type pairs (`PAIRS` in the module: controller to repository, service to database
  module, service to database driver, UI to database, domain to infrastructure, core to HTTP library), assigned after a seeded shuffle (seed 20261123)
  with a rotating counter, so the primary stratum has 8/8/7/7/7/7 per pair. Every dependency is unrelated to every ADR by construction, so the
  **correct verdict is always "violation"** and any "justified" is an error.
* **Model path.** The unchanged M7 extraction (prompt `x4`, `LLMExtractAnalyzer`, grounding, `resolve_extraction`), Qwen2.5 7B Q4 via Ollama,
  temperature 0, the same settings as the earlier runs. The ADR is forced in. The "Selected because" line shows the relevance matcher's real reasons
  where it would have selected the ADR, and nothing otherwise. No Git history is supplied (`evolution = None`).
* **Second reading.** The same extraction after the stance-attribution check the product applies by default. No extra call.
* **Routing.** M8 applied the way the product would: only ADRs the matcher selects reach the policy. For an escalated case the model's answer is the
  forced-in answer already on record (same bundle, same prompt). A code reader that says "permits" without any model (`direct_code`) is also a false
  permission and is counted in the pipeline rate.
* **Calls.** 49 model calls (44 primary + 5 control). One pass per ADR; the model is not bit-for-bit repeatable across sessions
  (`ANALYSIS_PLAN.md`, run-2 replication), so the CIs below are sampling intervals for the 44 ADRs, not model-noise intervals.

## Outcome classes (one extraction)

| Class | Definition | Consequence |
|---|---|---|
| **dangerous** | `decision = permits` and `covers = yes` | verdict can flip to "justified" |
| misleading | attributed another way: `prohibits` with `covers` yes/unclear, or `permits` with `covers` unclear | verdict stays "violation"; the explanation would cite an irrelevant ADR |
| correct | `does_not_address`, or `covers = no` | none |
| failure | no usable reply | never a verdict; the structural verdict stands |

## Pre-registered primary metric and reading

**Primary metric:** the number of `dangerous` extractions among the 44 primary ADRs, raw M7, **unadjudicated**, reported with a Wilson 95% interval.

| Band | Count of 44 | Wilson 95% CI at the band's edge | What it would support |
|---|---|---|---|
| **LOW** | 0 to 2 | 0 = 0.0 to 8.0%; 2 = 1.3 to 15.1% | The policy on real text: an unrelated ADR rarely produces a permission. Report as "no more than about 15% at 95% confidence", not "safe" |
| **MODERATE** | 3 to 4 | 3 = 2.3 to 18.2%; 4 = 3.6 to 21.2% | Inconclusive. Every flagged case is read and reported individually |
| **HIGH** | 5 or more | 5 = 5.0 to 24.0% | A negative finding, reported as such: the extractor cannot be trusted to ignore unrelated ADRs. Grounding of the extraction in quoted text becomes the stated next step; the product claim stands only with the attribution check and routing results beside it |

These cut-offs are my proposal and are fixed by this document, not by the results: they were set so that 44 ADRs can distinguish "rare" from "common"
(0 of 44 rules out more than 8%; 5 of 44 puts the lower bound above 5%). Either extreme is publishable.

## Secondary quantities (descriptive, no thresholds)

* misleading rate, any-false-attribution rate, parse failures, and the share whose verdict actually flips to "justified" (raw);
* dangerous rate after the attribution check, and how many readings it rejected;
* the matcher's selection rate, and M8's route counts (structural, code reader, model);
* **pipeline false-justified rate** (M8 routing + attribution) with CI, split into code-reader and model paths. This is the figure closest to what a user
  of the product would experience, because most unrelated ADRs are never selected;
* counts by matcher selection, pair, repository and ADR status (small cells: read as direction, not size);
* the 5-ADR inactive control (does the model ignore a non-active record, as its prompt says?).

## Adjudication (done by the team, before reading the band)

The pairs are unrelated by construction, but some Q1 = "no" ADRs are topically close to a pair (for example an ADR that chooses a database library,
paired with a service-to-database dependency). After the run the script writes `adjudication_template.csv` (every dangerous and misleading row, with the
model's one-sentence reason and the ADR name). Each team member judges, from the ADR text, whether the ADR **has nothing to do** with that dependency
(`false_permission`) or whether a reasonable reader could take it as relevant (`defensible`). The headline stays the unadjudicated count; the adjudicated
count is reported beside it, never instead of it.

## What this does not tell us

* Whether the model reads the roughly 10 ADRs that *do* govern dependencies correctly. That needs hand-built cases (extending the 7-case study) and is
  the next step. This probe measures one failure direction only (false permission), on text where the answer is known to be "not addressed".
* Whether results hold for other dependency types: six synthetic pairs, Python paths, no Git history.
* Anything about other models: one 7B quantised model.
* Sample limits: 44 ADRs from 10 repositories, several repositories contributing 6 to 8 each, so ADRs from one project are not independent; per-repository
  counts are in `summary.json`. Labels are AI-drafted and team-verified, not independent annotation.
* A forced-in ADR is a stress test: the matcher would not select most of them. Model-level and pipeline-level rates are therefore reported separately.

## Protocol

1. Team confirms or changes the thresholds above **before** the freeze is committed.
2. `python -m experiments.real_adrs.false_permission build` (writes `datasets/real_adrs_false_permission/cases.csv`, no ADR text) then `freeze`.
   Commit and tag (`git tag false-permission-frozen`).
3. Run in the notebook (cell 9f, Internet on): `run` first verifies the SHA-256 of 12 files and refuses to continue on any difference, then fetches each
   ADR at its pinned commit (checked against its hash) and makes 49 calls.
4. Team fills `adjudication_template.csv`, then `score --results ... --adjudication ...`.
5. Results and a critical reading go in `docs/FALSE_PERMISSION_RESULTS.md`, whichever band results. Nothing in the frozen files may change between steps 2 and 4.

## Disclosure of what was done before the freeze

* The first proposal (another session) said 47 ADRs; the count was re-derived from the sheet and manifest (above).
* A plumbing check ran all 49 cases through the code with a stub model on the real texts, to confirm that every pinned text downloads and matches its hash and
  that nothing raises. Only error counts were looked at; the routing and class distributions were not printed or used.
* Thresholds, pair list, seed and outcome classes were fixed before that check.
* If a plumbing defect is found after the freeze, the fix is committed with a dated row in `ANALYSIS_PLAN.md` and the record is regenerated; no definition may
  change after any model output has been seen.
