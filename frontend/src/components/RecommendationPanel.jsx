import React from "react";

// "Suggested fix" for one violation. Two clearly separated parts:
//   * rule-derived options (from the architecture rules; always available, no model)
//   * AI-tailored steps (only when a model answered); always labelled as a suggestion to review.
export default function RecommendationPanel({ rec, loading, error, onRun }) {
  return (
    <div data-testid="recommendation-panel">
      {!rec && (
        <div className="btn-row" style={{ marginTop: 0 }}>
          <button className="btn-primary" onClick={() => onRun(false)} disabled={loading} data-testid="suggest-fix">
            {loading ? "Thinking…" : "Suggest a fix"}
          </button>
          <span className="semantic-meta">Uses the AI model if one is connected; otherwise shows rule-based options.</span>
        </div>
      )}
      {error && <div className="error-banner" data-testid="recommendation-error">{error}</div>}

      {rec && (
        <div>
          <div className={`verdict-banner ${rec.source === "ai" ? "review" : "sufficient"}`} data-testid="recommendation-banner">
            <div className="verdict-headline">
              {rec.source === "ai" ? "AI-generated suggestion — review before applying" : "Rule-based suggestion (no AI model used)"}
            </div>
            <div className="verdict-sub">{rec.disclaimer}</div>
          </div>

          <p className="semantic-explanation" data-testid="recommendation-summary">{rec.summary}</p>
          {rec.note && <p className="semantic-meta" data-testid="recommendation-note">{rec.note}</p>}
          {(rec.warnings || []).map((w, i) => (
            <div className="error-banner" key={i} data-testid="recommendation-warning">{w}</div>
          ))}

          {rec.ai && (
            <div className="extracted" data-testid="ai-steps">
              <div className="why-label">AI-tailored steps for this code {rec.model ? `(${rec.model})` : ""}</div>
              <ol className="why-list">
                {rec.ai.steps.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
              {rec.ai.risks?.length > 0 && (
                <>
                  <div className="why-label" style={{ marginTop: 10 }}>Watch out for</div>
                  <ul className="why-list">{rec.ai.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
                </>
              )}
            </div>
          )}

          {(rec.options || []).map((o) => (
            <div className="extracted" key={o.id} data-testid={`option-${o.id}`}>
              <div className="semantic-head">
                <span className="semantic-title">{o.title}</span>
                <span className="confidence">effort: {o.effort}</span>
                {o.id === rec.recommended_option && <span className="status-pill justified">recommended</span>}
              </div>
              <p className="semantic-explanation">{o.why}</p>
              <ol className="why-list">{o.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
              {o.adr_draft && <pre className="adr-draft" data-testid="adr-draft">{o.adr_draft}</pre>}
            </div>
          ))}

          <div className="btn-row">
            <button className="btn-secondary" onClick={() => onRun(true)} disabled={loading} data-testid="regenerate-fix">
              {loading ? "Thinking…" : "Regenerate"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
