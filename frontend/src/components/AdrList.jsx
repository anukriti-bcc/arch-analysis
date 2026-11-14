import React from "react";
import { formatDate, isActiveAdrStatus, MATCH_REASON_LABELS } from "../lib/format.js";

// Architectural-intent evidence: the decision records that may bear on this
// dependency, and WHY each was selected. Whether a record actually authorises
// the dependency is the semantic question the LLM (or policy) answers.
export default function AdrList({ adrs }) {
  if (!adrs || adrs.length === 0) {
    return (
      <div className="empty" data-testid="adr-empty">
        No decision record was found that is relevant to this dependency.
      </div>
    );
  }
  return (
    <div data-testid="adr-list">
      {adrs.map((adr) => {
        const active = isActiveAdrStatus(adr.status);
        return (
          <div className="adr-card" key={adr.id} data-testid={`adr-${adr.id}`}>
            <div className="adr-head">
              <span className="mono adr-id">{adr.id}</span>
              <span className="adr-title">{adr.title}</span>
              <span className={`status-pill ${active ? "active" : "inactive"}`}>
                {active ? adr.status : `inactive · ${adr.status}`}
              </span>
            </div>
            <div className="adr-meta">
              {adr.date && <span>{formatDate(adr.date)}</span>}
              <span className="mono">{adr.path}</span>
            </div>
            <div className="chip-row">
              <span className="chip-row-label">selected because it</span>
              {(adr.match_reasons || []).map((r) => (
                <span key={r} className={`chip ${r === "commit_reference" ? "adr" : ""}`}>
                  {MATCH_REASON_LABELS[r] || r}
                </span>
              ))}
            </div>
            {adr.text && (
              <details className="adr-text">
                <summary>Read the record</summary>
                <pre>{adr.text}</pre>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
