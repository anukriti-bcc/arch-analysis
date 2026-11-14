# Real-repository case study: sqlfluff (import-linter contracts as architectural intent)

## Why this source of intent
The ADR-Study-Dataset (921 repos) gave almost no Python repos with machine-checkable structural rules
(158 with >=10 formal ADRs -> 7 Python-heavy -> ~0 whose ADRs state module-dependency constraints; keyword
screen, ADR bodies not manually read). Python projects that enforce layering with import-linter keep explicit,
machine-readable contracts in config and a Git history around them. 1,635 of the 2,294 listed dependents of
import-linter were collected; of the 222 with >=10 stars, 171 define contracts and 110 have layers/forbidden
contracts plus history (see caveat 6).

## Pipeline
1. `import_linter_importer.py`  contracts -> `rules.yaml` (path-prefix components, containment expanded) +
   `tolerated.json` (the team's `ignore_imports`, each with the maintainers' own comment as the reason).
2. `evaluate_repo.py`  worktree per commit -> scan -> findings -> tag tolerated -> run the reference tool
   (`lint-imports`) on the same tree with the same contracts -> compare direct violating imports.
3. `trace_violations.py`  GitEvolutionAnalyzer: introducing / removing commit of each violation.

## Results (sqlfluff, 7,292 commits, contracts adopted 2023-08-29)
Retrospective = today's contracts pruned to the modules that existed at that commit, applied to older code.

| commit | date | rules used | engine violations (untolerated) | reference tool | agreement |
|---|---|---|---|---|---|
| early_2 / early_3 | 2021 | retrospective | 0 | 0 broken | 0/0 |
| early_4 | 2021-10-18 | retrospective | 1 | 1 broken | 1/1 |
| early_5 | 2022-05-10 | retrospective | 1 | 1 broken | 1/1 |
| pre_adoption | 2023-08-29 | retrospective | 5 (+2 tolerated) | 3 contracts broken; 7 `a -> b` pairs printed, 5 of them direct violations | 5/5 |
| adoption .. HEAD | 2023-08 .. 2026-11 | team's own contracts at that commit | 0 | 0 broken | 0/0 |

Violation lifetimes found by the evolution analyzer (all five removed; none present at HEAD):
- core/rules/base -> core/linter: introduced 2021-10-04 by "Issue 1471: Inline --noqa not always honoured..." (a bug-fix,
  not an architectural change); removed 2023-10-25 by "Unpick dependencies between modules in sqlfluff.core (#5348)".
- core/parser/segments/base -> core/rules: introduced 2022-07-22 ("Rationalise Rule Imports"); removed 2023-10-25 (#5348).
- core/parser/segments/fix -> core/rules: introduced 2023-08-18; removed 2023-10-25 (#5348).
- core/linter/linting_result -> cli: introduced 2022-07-16 ("Consistent return codes"); removed 2023-08-29 ("Import rationalisation").
- core/parser/segments/file -> dialects/dialect_ansi: introduced 2023-08-18; removed 2023-08-29.
The removing commits are the ones in which the maintainers adopted / extended the contracts.

## Bugs found by this exercise (all fixed and tested)
1. **Suffix matching resolved stdlib imports to project files.** `import logging` resolved to `utils/testing/logging.py`:
   21 false violations at HEAD where the reference tool reports 0. Fix: opt-in anchored resolution
   (`import_resolution: anchored` in the rules file); the history analyzer takes the same flag. Default behaviour unchanged.
2. **Anchored mode kept only one target per `from pkg import a, b` statement** ("first resolvable name wins"). Fixed
   (`resolve_import_all`): one dependency per imported submodule, plus the package itself when an attribute is imported,
   as grimp (the graph builder import-linter uses) counts them. This was a systematic undercount, not a corner case:
   see the differential tests below. The scanner and the Git analyzer use the same function, so "when was it
   introduced" answers about the same dependencies the scanner reports.
3. **`containers`-based `layers` contracts were silently dropped when pruned for old commits** (layer names are relative,
   but presence was tested on the bare name). Fixed; a layer present in only some containers is kept as optional `(name)`.

## Verification against the reference implementations (differential tests)
`backend/tests/test_differential_import_linter.py` builds random repositories using seven import styles and compares with
grimp and `lint-imports` (skipped if import-linter is not installed):
- import graph vs grimp: identical on every repository (40 of 40 in the exploratory run; 12 in the committed tests);
  with the old first-name-wins behaviour 39 of 40 repositories mismatched, so the comparison is able to fail;
- `forbidden` contracts with indirect imports allowed: engine violations equal the reference's exactly (25 of 25 repositories,
  63 violations in the exploratory run);
- `layers` and `independence`: every direct violation the engine reports is reported by the reference, and the contract is broken
  in the reference whenever the engine finds one (25 of 25; 138 violations).
These show faithfulness of import resolution and contract translation on *generated* code with the *same* contracts; they do not
show anything about the research question.

## Re-run on a fresh clone (2026-11-12, 7,318 commits) with the fixed scanner
The engine's results were identical on all 12 evaluated commits, and the violation lifecycle trace gave the same introducing and
removing commits. So the numbers above are reproducible and were not affected by bug 2 on sqlfluff.

## Limitations and caveats (read before claiming anything)
1. Direct imports only. import-linter also reports indirect chains, which this engine does not check. At pre_adoption the reference
   printed 7 pairs: 5 are the engine's direct violations (all found) and the other 2 (`api.info -> core.linter`,
   `core.linter -> core.linter.linting_result`) are edges that no generated rule forbids, so they cannot be direct violations. That
   is consistent with them being intermediate hops of an indirect chain (the saved record does not keep the chain text, so this is
   inferred, not read off the output). Two of sqlfluff's four documented exceptions (`formatter -> linter`,
   `plugin.hookspecs -> rules.base`) also only matter for indirect chains, so the engine never sees them.
2. Agreement is one-directional: every direct engine violation was confirmed by the reference; the reference additionally reports indirect chains, which the engine does not.
3. One repository, five violations. This shows the pipeline works and is faithful on this repo; it is not a statistical result.
4. Ground truth is the reference tool plus the maintainers' commits. The ADR-driven escalation rule is NOT exercised here (no ADR text).
   Nothing here involves an LLM.
5. The reference tool shares the rules, so near-perfect agreement on "is the rule broken" is expected by construction.
   The open question on real repos is whether history/semantics help judge which violations matter; that is not yet measured.
6. Candidate-search caveat: first_contract_date in contracts.csv was computed per config file; for configs moved between files
   (setup.cfg -> pyproject.toml) it dates the move, not the adoption (sqlfluff: 2023-11-06 vs real 2023-08-29). find_contracts.py is
   fixed (repo-wide search) but the 110/18 counts were NOT re-run. early_1 (2020-05-04) had 20% module coverage; the reference tool did not run there.
