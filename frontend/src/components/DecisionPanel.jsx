import React from "react";
import { formatInt } from "../lib/format.js";

// The "Evidence sufficient?" decision of the workflow, made visible:
//   * before running: what the policy WOULD do with the evidence (no LLM involved)
//   * after running: the final verdict, WHY it was reached, and whether an LLM was needed.
export default function DecisionPanel({ policy, decision, semantic, running, error, onRun }) {
  const shown = decision || (policy ? { ...policy, llm_called: false, final_verdict: policy.direct_verdict, preview: true } : null);
  if (!shown) return <div className="empty">No decision yet.</div>;

  let headline, tone;
  if (decision) {
    tone = decision.final_verdict === "justified" ? "conformant" : "violation";
    headline = decision.final_verdict === "justified" ? "Justified by documented intent" : "Confirmed violation";
  } else if (policy.escalate) {
    tone = "review";
    headline = "Evidence is not sufficient on its own — semantic review recommended";
  } else {
    tone = "sufficient";
    headline = "Evidence is sufficient — no LLM needed";
  }

  let how = null;
  if (decision) {
    if (!decision.llm_called) how = "Resolved from the evidence alone. No LLM call was made.";
    else if (decision.outcome_source === "fallback")
      how = "The LLM was called but gave no usable verdict, so the structural verdict was kept.";
    else how = decision.forced ? "LLM review was forced although the policy considered the evidence sufficient." : "Resolved by LLM semantic review.";
  }

  return (
    <div data-testid="decision-panel">
      <div className={`verdict-banner ${tone}`} data-testid="verdict-banner">
        <div className="verdict-headline">{headline}</div>
        {how && <div className="verdict-sub" data-testid="decision-how">{how}</div>}
      </div>

      <div className="why">
        <div className="why-label">{decision ? "Why" : "Policy reasoning"}</div>
        <ul className="why-list" data-testid="policy-reasons">
          {(shown.reasons || []).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </div>

      <div className="btn-row">
        <button className="btn-primary" onClick={() => onRun(false)} disabled={running}>
          {running ? "Analyzing…" : decision ? "Run again" : "Run evidence-guided analysis"}
        </button>
        <button
          className="btn-secondary"
          onClick={() => onRun(true)}
          disabled={running}
          title="Call the model even if the policy says the evidence is sufficient"
        >
          Force LLM review
        </button>
      </div>

      {error && (
        <div className="error-banner" data-testid="decision-error">
          {error}
        </div>
      )}

      {semantic && <SemanticResult semantic={semantic} />}
    </div>
  );
}

function SemanticResult({ semantic }) {
  const ok = semantic.parsed_ok;
  return (
    <div className="semantic" data-testid="semantic-result">
      <div className="semantic-head">
        <span className="semantic-title">LLM verdict</span>
        {ok ? (
          <span className={`status-pill ${semantic.verdict === "justified" ? "justified" : semantic.verdict === "violation" ? "violation" : "review"}`}>
            {semantic.verdict}
          </span>
        ) : (
          <span className="status-pill violation">no usable output</span>
        )}
        {ok && semantic.confidence !== null && (
          <span className="confidence" title="the model's self-reported confidence">
            confidence {Math.round(semantic.confidence * 100)}%
          </span>
        )}
      </div>
      {ok ? (
        <p className="semantic-explanation" data-testid="semantic-explanation">{semantic.explanation}</p>
      ) : (
        <p className="semantic-explanation">{semantic.error || "The model's reply could not be parsed."}</p>
      )}
      {ok && (semantic.evidence_used || []).length > 0 && (
        <div className="chip-row">
          <span className="chip-row-label">evidence the model cited</span>
          {semantic.evidence_used.map((e, i) => (
            <span key={i} className="chip">{e}</span>
          ))}
        </div>
      )}
      <div className="semantic-meta" data-testid="semantic-meta">
        {semantic.model} · {formatInt(semantic.tokens_used?.input)} tokens in / {formatInt(semantic.tokens_used?.output)} out ·{" "}
        {Number(semantic.latency_s || 0).toFixed(1)} s{semantic.cached ? " · cached" : ""}
        {semantic.tokens_estimated ? " · token counts estimated" : ""}
      </div>
    </div>
  );
}
