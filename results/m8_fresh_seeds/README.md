# Fresh-seed confirmation of M8 and M8+attribution (hard tier, seeds 41, 42, 43; 216 cases)

Run 2026-11-22 on Kaggle (Qwen2.5 7B Q4 via Ollama, same model and prompt version as the M7 confirmation), with the code frozen at tag
`prekaggle-frozen` (the freeze check printed "19 files match" before the run).

**Provenance of these files.** They are the notebook's printed output, saved verbatim: `notebook_output_9d1_per_seed.txt` (test-split table per seed) and
`notebook_output_9d2_pooled_and_verdict.txt` (pooled 216-case table, the P1-P8 verdict, and the per-scenario table). **The raw `predictions.csv` files
for these seeds were not retained**: the Kaggle session was reset before they were downloaded. The verdict script ran on the live predictions, so
the PASS/FAIL lines are as computed (P5 and P8, "replay equals live", compare the live rows with an independent replay and found 0 differences).
Re-running the same cell regenerates the files and would be a replication, not a new test; the first run's printed verdict is the pre-registered one.

## Run 2 (replication, 2026-11-22, same frozen code, same seeds, same model): `run2_replication/`

The cells were re-run in a new Kaggle session and the raw files were downloaded (predictions, metrics, verdict, per-seed folders). **Run 1 (the printouts above) is
the pre-registered run; run 2 is a replication.** Both passed P1-P8. The model is not bit-for-bit reproducible between sessions: headline numbers moved by up to
about 0.005 F1 and individual scenario counts by 1 (table in `docs/GATED_POLICY_RESULTS.md`).

