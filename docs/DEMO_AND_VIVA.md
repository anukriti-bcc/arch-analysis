# Running the demo locally, and explaining what the AI does

## 1. Local setup (Windows PowerShell, local Ollama)

Ollama must be running with the model pulled (`ollama pull qwen2.5:3b-instruct`; check with `ollama list`). In the window that starts the backend:

```powershell
cd backend
$env:LLM_BASE_URL = "http://localhost:11434/v1"
$env:LLM_MODEL    = "qwen2.5:3b-instruct"
uvicorn main:app --reload          # http://localhost:8000/docs
```
Frontend, in a second window: `cd frontend; npm run dev` (http://localhost:5173). The two `$env:` lines only apply to the window they were typed in and are lost
when it closes. No API key is needed for Ollama. To prove the model is reachable before the demo: `curl http://localhost:11434/api/tags`.

**Honesty about the model:** every measured result in the report (F1 0.97, 156 vs 171 calls, scenario tables) was produced with **Qwen2.5 7B (Q4) on Kaggle**.
The local demo model is the **3B** version, which was **not evaluated**. Do not quote benchmark numbers for the 3B demo; say the demo model is smaller and that the
results were measured on the 7B. A 3B model is more likely to give an unusable reply; the app handles that (it falls back to rule-based output and says so).
If the laptop can run the 7B comfortably (`ollama pull qwen2.5:7b-instruct`, set `LLM_MODEL` to it), the demo then matches the evaluated model.
A slow model is not a failure: the first call can take 10 to 60 seconds on a CPU.

## 2. What to show

1. Analyse the sample repository, open a **violation** finding, and read its three evidence sections (code, ADR, history).
2. **Decision** section: the policy says whether the evidence is sufficient. Press *Run evidence-guided analysis* on one that needs review: the model **extracts** what the ADR
   says (decision, scope, date limit) and **code computes** the verdict.
3. **Suggested fix** section: press *Suggest a fix*. With the model connected you see an *AI-generated suggestion* banner, the AI's tailored steps, and the rule-derived options
   underneath (route through the sanctioned layer, or document an exception with a ready ADR draft). With the model stopped you still get the rule-derived options, labelled
   *Rule-based suggestion (no AI model used)*: the demo cannot fail because of the model.

## 3. "What is the AI actually doing?" (a short, honest answer for the viva)

> Detecting a forbidden import is ordinary static analysis, and the project does that with code. The AI is used where code cannot do the job: **reading the architects'
> own words**. An Architecture Decision Record is free text, written differently every time ("we accept this for now", "grandfathered until the freeze", "the proposal to allow
> it was not approved"). A language model reads that text and extracts structured facts (what was decided, does it cover this dependency, is there a date limit). **Code then
> computes the verdict** by comparing those facts with the dependency's Git history, so the model is never trusted to do date arithmetic or to decide alone. We measured this:
> a code-only reader scored F1 0.59 on difficult ADR wording, an LLM that answers directly 0.89, and the extract-then-compute design 0.97 on 216 fresh cases. Because model calls cost time,
> a gate decides **when** a call is needed (it made 15 fewer calls on the same cases with no loss of accuracy, and no wrong verdict was made without the model). The AI also
> **explains** each finding in plain language and, as an extra, **suggests how to fix** the drift, always labelled as a suggestion.

Say plainly, if asked: the benchmark is generated, the model is small, real ADRs are harder (our 7-case real-ADR check got 5 of 7, no better than always answering "violation"), and the
fix suggestions are **not evaluated**: they are a convenience feature, validated only for form (the reply must parse, name an offered option, and any file it mentions must exist).

## 4. The suggested-fix feature (what it is and is not)

* Endpoint `POST /findings/{id}/recommendation?analysis_id=...` (`use_llm=false` for rule-only, `refresh=true` to regenerate). Code: `analysis/semantic/remediation.py`.
* **Rule-derived (no model):** finds the sanctioned route between the two component types in the architecture rules (for example service to repository to database), standard
  steps for it, an ADR draft for documenting an exception (its wording is recognised as a permission by the project's own ADR reader, tested), and a "review the rule" option when
  the same rule is broken 3 or more times.
* **AI-tailored steps (model):** the model picks one of the offered options and writes concrete steps for this code. The reply is validated; a reply that is not usable is ignored; any file
  the model names that is not in the analysed repository is shown as a warning.
* Nothing is ever changed in the code, the model's advice is **not measured** (no accuracy claim), and a finding already resolved as justified gets no fix suggestion.
