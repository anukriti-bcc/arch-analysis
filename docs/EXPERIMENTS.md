# Running the evaluation

All commands are run from `backend/`.

## 1. Generate the benchmark (deterministic, ~15 s, no network)

    python -m experiments.benchmark.generate --out ../datasets/benchmark/generated --seed 7

60 small repositories with scripted Git histories, split ~50/50 into `dev` / `test`.
Each has `labels.json` with the ground truth for every governed dependency.
Same seed => identical repositories (identical commit hashes).

## 2. Plan before spending quota

    python -m experiments.run_experiments --dry-run

Counts LLM calls and estimates tokens without calling anything. Measured on the
seed-7 benchmark: ~690 calls *listed*, but only **514 distinct real calls**
because M3, M4 and M5 send identical prompts for the same finding and the
on-disk cache serves repeats (M5 and all M4 seeds add 0 real calls after M3;
A1 adds 34; M2 adds 420).

## 3. Run with a real model (any OpenAI-compatible endpoint)

    # local (Ollama):
    export LLM_BASE_URL=http://localhost:11434/v1
    export LLM_MODEL=qwen2.5:7b-instruct          # whichever model you pulled
    # or a hosted provider's OpenAI-compatible endpoint + key:
    # export LLM_BASE_URL=...  LLM_MODEL=...  LLM_API_KEY=...

    python -m experiments.run_experiments --splits dev,test --max-calls 600 \
        --price-in 0 --price-out 0

* Use ONE model for every method; its name is recorded in `run_config.json`.
* `--max-calls N` stops before exceeding N *real* calls. Finished responses are
  cached in `llm_cache.sqlite` next to the output folder and shared by every phase; re-run the same command to resume.
* Cheap-first ordering if quota is tight: `--methods static,evidence_guided,no_history,full_hybrid,generic_selective`
  (adds M2, the 420-call one, last).
* `--provider mock` runs the pipeline with a keyword stand-in. Its output is
  stamped as a smoke test and MUST NOT be reported as a result.

## 3b. Running a free local model (recommended for this project)

Why: no quota, no cost, fixed weights (reproducible), and prompt iteration is
free. Unit tests never call a model; only these experiment runs do.

    # 1. install Ollama (ollama.com), then pull an instruction-tuned model.
    #    Check ollama.com/library for current names; a 7-8B instruct model is the
    #    smallest I would trust for the date-clause scenarios (C/D).
    ollama pull <model>

    # 2. IMPORTANT: Ollama silently TRUNCATES prompts longer than its context
    #    window, and the default window is small. Our longest prompt is ~1,100
    #    tokens (estimate), so make a copy of the model with a larger window:
    printf 'FROM <model>\nPARAMETER num_ctx 4096\nPARAMETER temperature 0\n' > Modelfile
    ollama create arch-judge -f Modelfile

    # 3. point the runner at it
    export LLM_BASE_URL=http://localhost:11434/v1
    export LLM_MODEL=arch-judge
    export LLM_API_KEY=ollama

When reporting results, record the BASE model name and digest (`ollama show <model>`), not
just "arch-judge". Keep the same model for every method.

Suggested phases (every real response is cached; changing a prompt or bumping
PROMPT_VERSION invalidates only the affected entries):

  A. Pilot  : `--limit-cases 10 --methods evidence_guided,full_hybrid` (one case per scenario). Check `parsed_ok`, `error`, `latency_s`.
  B. Dev    : `--splits dev --methods static,full_hybrid,evidence_guided,no_history`. Iterate the PROMPT on dev only.
  C. Freeze : stop editing prompts and the policy. Run `--splits dev,test` with all methods.
     M2 (LLM on every edge) is ~420 of the ~514 calls; run it last, or `--splits test` only (~196 calls) if time is short.

Rough time (a guess, measure it in the pilot): a 7B model on a laptop CPU may take tens of
seconds per call (hours for the full run); with a GPU, seconds per call.

No usable GPU (e.g. a laptop with 8 GB RAM and integrated graphics cannot run a 7-8B model in reasonable time)?
Use `notebooks/run_on_free_gpu.ipynb` (used for every real-model run in this project, on Kaggle), or run the same commands inside a free Kaggle or Colab notebook
(clone the repo, install Ollama, pull the model) and download `results/`
afterwards. Check current free-GPU quotas and session limits yourself; sessions are time-limited,
which is another reason the cache and `--max-calls` resume behaviour matter.

For manual checks, `predictions.csv` includes the model's `explanation` for every escalated edge.

## 3c. The full run plan (cheapest order, with measured call counts)

Measured on the seed-7 benchmark (distinct model calls after caching; M3, M4 and M5 send identical prompts for the same finding):

| Run | New calls | Notes |
|---|---|---|
| Primary wording, `full` prompt, **without** M2 | 99 | M3 60 + A1 34 + A2 5; M4 seeds and M5 add 0 |
| + M2 (LLM on every edge) | +420 | the expensive one; run it **once**, on the primary setup |
| Primary wording, `minimal` prompt, without M2 | 99 | sensitivity to prompt guidance |
| **Held-out wording**, `full` prompt, without M2 | 99 | confirmatory robustness run |
| **Total** | **717** | 297 without the single M2 run |

    # primary (exploratory/main)
    python -m experiments.run_experiments --splits dev,test --methods static,full_hybrid,evidence_guided,no_history,no_intent,generic_selective --out ../results/primary
    python -m experiments.run_experiments --splits dev,test --methods llm_only --out ../results/primary_m2

    # prompt-sensitivity: same data, guidance removed from the system prompts
    python -m experiments.run_experiments --prompt-variant minimal --methods static,full_hybrid,evidence_guided,no_history,no_intent,generic_selective --out ../results/minimal

    # held-out wording: same repositories, ADR decision language rewritten (commit docs/ANALYSIS_PLAN.md FIRST)
    python -m experiments.benchmark.generate --out ../datasets/benchmark/generated_heldout --wording heldout
    python -m experiments.run_experiments --benchmark ../datasets/benchmark/generated_heldout --methods static,full_hybrid,evidence_guided,no_history,no_intent,generic_selective --out ../results/heldout

All runs write to `results/` next to one shared `llm_cache.sqlite`, so nothing is ever paid for twice. The system prompt is part of the cache key, so the
`minimal` run can never be served `full`-prompt answers.

Each run also writes `paired_comparisons.csv` (M5 minus every other method, 95% paired bootstrap) and `density_sweep.csv`
(how call savings change if fewer dependencies have a decision record). The **Evaluation** tab shows both.
`docs/ANALYSIS_PLAN.md` fixes in advance what counts as support for each claim.

## Why held-out wording and a minimal prompt exist

The scenarios and the ADR wording were written together, and the full system prompt mentions things such as grandfathering clauses and
"temporary" commits that mirror them. A reader can fairly ask whether a method learned our phrasing or our hints.
* `--wording hard` generates a harder-to-read tier (and two extra scenarios) so code-only readers and LLM methods can be told apart; see `docs/HARD_TIER.md`.
* `--wording heldout` regenerates the **same repositories** (identical code, histories, dates and labels, verified in `tests/test_heldout_variants_ablation.py`) with the decision
  language rewritten and every primary key phrase avoided. A keyword matcher fails on it (also tested); a model that reads should not.
* `--prompt-variant minimal` removes all scenario-specific guidance from the system prompts, leaving the task and the output format.

## 4. Outputs (`results/run/`)

`metrics.csv` (headline, per split, with F1 bootstrap CI), `metrics_by_scenario.csv`,
`predictions.csv` (every edge, every method, with tokens/latency/policy reasons),
`summary.md`, `frontier.png` (F1 vs LLM calls), `run_config.json`.

## Methods
M1 static | M2 LLM-only (every edge, no structural pre-check) | M3 full hybrid (LLM on
every structural violation) | M4 generic selective (random subset, same budget as M5)
| M5 evidence-guided | A1 = M5 without evolution evidence.

## Threats to validity
1. The benchmark is generated and its scenario mix and ADR wording are authored
   by us. Results show behaviour under controlled conditions, not accuracy on
   real repositories. Several wording variants, noise ADRs, a dev/test split and
   per-scenario reporting are included to make this visible.
2. The policy's thresholds were fixed before looking at test-split results; do
   not tune on `test`.
3. The benchmark is ADR-dense: 45 of its 60 targeted dependencies have a relevant decision record (40 of them
   active), and 5 more escalate on history signals alone. The policy therefore resolves only 15 of 60 without the
   model (measured), which limits how many calls any ADR-aware policy can save here. Real repositories mostly have
   no relevant ADR, so savings there could be larger, but that has not been measured. Report the call savings with
   this caveat (or add a re-weighted analysis).
4. Small local models may be weaker than hosted ones; because every method uses
   the same model the comparison is internally fair, but absolute F1 is
   model-specific.
5. File renames are not tracked by the evolution analyzer (flagged per finding
   as `rename_history_detected`).
