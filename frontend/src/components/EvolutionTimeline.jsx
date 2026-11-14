import React from "react";
import { layoutTimeline, EVENT_META } from "../lib/timeline.js";
import { formatDate, plural, shortSha } from "../lib/format.js";

// Evolution evidence: WHEN did this dependency come into existence, and what
// does the surrounding history say about it? Backed by GET /findings/{id}/evidence.
export default function EvolutionTimeline({ evolution }) {
  if (!evolution) {
    return <div className="empty">History evidence not loaded.</div>;
  }
  if (!evolution.available) {
    return (
      <div className="empty" data-testid="evolution-unavailable">
        No Git history available ({evolution.reason || "unknown reason"}). Structural and intent evidence are
        still shown; history can only be used when the analysed folder is inside a Git repository.
      </div>
    );
  }
  const intro = evolution.introducing_commit;
  if (!intro) {
    return (
      <div className="empty" data-testid="evolution-absent">
        This dependency is not present in committed history at HEAD (it may exist only as an uncommitted
        change), so there is no introducing commit to show.
      </div>
    );
  }

  const nodes = layoutTimeline(evolution.timeline, evolution.snapshot_date);
  const sig = evolution.message_signals || {};
  const chips = [
    ...(sig.temporary_language || []).map((w) => ({ text: `“${w}”`, kind: "temporary", title: "temporary-language in the introducing commit message" })),
    ...(sig.migration_language || []).map((w) => ({ text: `“${w}”`, kind: "migration", title: "migration-language in the introducing commit message" })),
    ...(sig.adr_references || []).map((id) => ({ text: id, kind: "adr", title: "decision record cited by the introducing commit" })),
    ...(sig.issue_references || []).map((id) => ({ text: id, kind: "issue", title: "issue cited by the introducing commit" })),
  ];

  return (
    <div data-testid="evolution">
      <div className="timeline" data-testid="timeline">
        <div className="timeline-track">
          <div className="timeline-line" />
          {nodes.map((n, i) => (
            <div key={`${n.kind}-${n.date}-${i}`} className={`timeline-node ${n.row}`} style={{ left: `${n.x}%` }}>
              <span className={`timeline-dot ${EVENT_META[n.kind]?.tone || "neutral"}`} />
              <span className="timeline-label">
                <strong>{EVENT_META[n.kind]?.label || n.kind}</strong>
                <br />
                {formatDate(n.date)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="fact-grid">
        <Fact label="Introduced" value={formatDate(evolution.introduced_at)} />
        <Fact label="Age at snapshot" value={plural(evolution.age_days, "day")} />
        <Fact
          label="Commits since"
          value={`${evolution.commits_since_introduction} (${evolution.relevant_commits_since_introduction} touching these files)`}
        />
        <Fact label="Born with the file" value={evolution.introduced_with_file_creation ? "yes" : "no"} />
        <Fact label="Reintroduced" value={evolution.reintroduced ? "yes" : "no"} />
      </div>

      <div className="commit-card">
        <div className="commit-head">
          <span className="mono">{shortSha(intro.sha || intro.short)}</span>
          <span>{intro.author}</span>
          <span>{formatDate(intro.date)}</span>
        </div>
        <div className="commit-message" data-testid="commit-message">{intro.message || intro.subject}</div>
      </div>

      {chips.length > 0 && (
        <div className="chip-row" data-testid="signals">
          <span className="chip-row-label">signals in the commit message</span>
          {chips.map((c, i) => (
            <span key={i} className={`chip ${c.kind}`} title={c.title}>{c.text}</span>
          ))}
        </div>
      )}

      {evolution.rename_history_detected && (
        <div className="note-banner" data-testid="rename-warning">
          A file involved appears to have been renamed. History before the rename is not followed, so the
          introduction date shown may be the rename rather than the original change.
        </div>
      )}
      {evolution.history_truncated && (
        <div className="note-banner">Only the most recent commits were examined; the introducing commit may be older.</div>
      )}
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div className="fact">
      <div className="fact-label">{label}</div>
      <div className="fact-value">{value}</div>
    </div>
  );
}
