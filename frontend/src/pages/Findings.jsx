import React, { useEffect, useState } from "react";
import {
  getAnalysisFindings,
  getFinding,
  getFindingEvidence,
  getTriage,
  requestRecommendation,
  requestSemanticAnalysis,
} from "../api/client.js";
import AdrList from "../components/AdrList.jsx";
import CodeSnippet from "../components/CodeSnippet.jsx";
import DecisionPanel from "../components/DecisionPanel.jsx";
import EvolutionTimeline from "../components/EvolutionTimeline.jsx";
import RecommendationPanel from "../components/RecommendationPanel.jsx";
import { formatDate, plural } from "../lib/format.js";

export default function Findings({ analysisId }) {
  const [findings, setFindings] = useState(null);
  const [triage, setTriage] = useState(null);
  const [triageError, setTriageError] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    setFindings(null);
    setTriage(null);
    setTriageError(null);
    setError(null);
    setSelectedId(null);
    getAnalysisFindings(analysisId)
      .then(setFindings)
      .catch((err) => setError(err.message));
    // Triage is an enhancement: if it fails the findings table still works.
    getTriage(analysisId)
      .then(setTriage)
      .catch((err) => setTriageError(err.message));
  }, [analysisId]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!findings) return <p className="empty-state">Loading findings…</p>;

  if (selectedId) {
    return <FindingDetail analysisId={analysisId} findingId={selectedId} onBack={() => setSelectedId(null)} />;
  }

  const violations = findings.filter((f) => f.status === "violation");
  const conformant = findings.filter((f) => f.status === "conformant");
  const triageById = new Map((triage?.items || []).map((i) => [i.finding_id, i]));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Findings</h1>
        <p className="page-desc">
          One row per governed dependency ({plural(violations.length, "violation")}, {conformant.length} conformant).
          Dependencies with no applicable rule at all are omitted here — the engine doesn't guess at unspecified
          relationships.
        </p>
      </div>

      {triage && (
        <div className="stat-grid" data-testid="triage-summary">
          <StatCard label="violations" value={triage.summary.violations} tone={triage.summary.violations > 0 ? "brick" : "forest"} />
          <StatCard label="resolved from evidence, no LLM" value={triage.summary.resolved_directly} tone="forest" />
          <StatCard label="need semantic review" value={triage.summary.needs_semantic_review} tone="accent" />
        </div>
      )}
      {triageError && (
        <div className="note-banner" data-testid="triage-error">
          Evidence triage unavailable: {triageError}
        </div>
      )}

      <table className="findings-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Source</th>
            <th>Target</th>
            <th>Rule</th>
            <th>Evidence triage</th>
            <th>Introduced</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((f) => {
            const t = triageById.get(f.id);
            return (
              <tr key={f.id} className="clickable" onClick={() => setSelectedId(f.id)} data-testid={`row-${f.id}`}>
                <td>
                  <span className={`status-pill ${f.status}`}>{f.status}</span>
                </td>
                <td>
                  <div className="mono">{f.source.name}</div>
                  <div className="sub">{f.source.component}</div>
                </td>
                <td>
                  <div className="mono">{f.target.name}</div>
                  <div className="sub">{f.target.component}</div>
                </td>
                <td className="mono muted">{f.rule_id}</td>
                <td>
                  {t ? (
                    <span
                      className={`status-pill ${t.escalate ? "review" : "sufficient"}`}
                      title={(t.reasons || []).join("\n")}
                    >
                      {t.escalate ? "needs review" : "sufficient"}
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="muted">{t ? formatDate(t.introduced_at) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StatCard({ label, value, tone }) {
  return (
    <div className="stat-card">
      <div className={`stat-value ${tone || ""}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function FindingDetail({ analysisId, findingId, onBack }) {
  const [finding, setFinding] = useState(null);
  const [evidence, setEvidence] = useState(null); // { evidence, policy }
  const [evidenceError, setEvidenceError] = useState(null);
  const [error, setError] = useState(null);
  const [decision, setDecision] = useState(null);
  const [semantic, setSemantic] = useState(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [rec, setRec] = useState(null);
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState(null);

  useEffect(() => {
    setRec(null);
    setRecError(null);
    setFinding(null);
    setEvidence(null);
    setEvidenceError(null);
    setError(null);
    setDecision(null);
    setSemantic(null);
    setRunError(null);
    getFinding(findingId, analysisId)
      .then((f) => {
        setFinding(f);
        setDecision(f.decision || null);
        setSemantic(f.semantic_analysis || null);
        if (f.status === "violation") {
          getFindingEvidence(findingId, analysisId)
            .then(setEvidence)
            .catch((err) => setEvidenceError(err.message));
        }
      })
      .catch((err) => setError(err.message));
  }, [findingId, analysisId]);

  async function run(force) {
    setRunning(true);
    setRunError(null);
    try {
      const res = await requestSemanticAnalysis(findingId, analysisId, force);
      setDecision(res.decision);
      setSemantic(res.semantic_analysis);
      if (res.evidence) setEvidence((prev) => ({ policy: prev?.policy, evidence: res.evidence }));
    } catch (err) {
      setRunError(err.message);
    } finally {
      setRunning(false);
    }
  }

  async function suggestFix(refresh) {
    setRecLoading(true);
    setRecError(null);
    try {
      setRec(await requestRecommendation(findingId, analysisId, refresh));
    } catch (err) {
      setRecError(err.message);
    } finally {
      setRecLoading(false);
    }
  }

  if (error) return <div className="error-banner">{error}</div>;
  if (!finding) return <p className="empty-state">Loading…</p>;

  const ev = evidence?.evidence;
  const isViolation = finding.status === "violation";

  return (
    <div>
      <button className="back-link" onClick={onBack}>
        ← back to findings
      </button>

      <div className="page-header">
        <h1 className="page-title">
          {finding.id}{" "}
          <span className={`status-pill ${finding.status}`} style={{ marginLeft: 10 }}>
            {finding.status}
          </span>
          {decision && (
            <span className={`status-pill ${decision.final_verdict === "justified" ? "justified" : "violation"}`} style={{ marginLeft: 8 }} data-testid="final-pill">
              final: {decision.final_verdict}
            </span>
          )}
        </h1>
        <p className="page-desc">{finding.expected}</p>
      </div>

      <div className="panel">
        <div className="dep-row">
          <Field label="Source" main={finding.source.name} sub={`${finding.source.component} · ${finding.source.id}`} />
          <Field label="Target" main={finding.target.name} sub={`${finding.target.component} · ${finding.target.id}`} />
          {finding.location && <Field label="Location" main={`${finding.location.file}:${finding.location.line}`} />}
          <Field label="Rule" main={finding.rule_id} />
        </div>
      </div>

      {!isViolation && (
        <p className="empty-state">
          This dependency conforms to its rule, so no further evidence analysis applies. Evidence, history and
          semantic review are only gathered for violations.
        </p>
      )}

      {isViolation && (
        <>
          {evidenceError && <div className="error-banner">{evidenceError}</div>}

          <Section title="Structural evidence" note="what the code actually does">
            <div className="rule-text">
              Rule {ev?.rule?.id || finding.rule_id}
              {ev?.rule?.description ? ` — ${ev.rule.description}` : ""}
            </div>
            {ev ? (
              <CodeSnippet snippet={ev.structural.code_snippet} highlightLine={ev.structural.line} />
            ) : (
              !evidenceError && <div className="empty">Loading…</div>
            )}
          </Section>

          <Section title="Architectural intent" note="decision records that may bear on this dependency">
            {ev ? <AdrList adrs={ev.adrs} /> : !evidenceError && <div className="empty">Loading…</div>}
          </Section>

          <Section title="Evolution evidence" note="when it appeared, and what history says about it">
            {ev ? <EvolutionTimeline evolution={ev.evolution} /> : !evidenceError && <div className="empty">Loading…</div>}
          </Section>

          <Section title="Decision" note="is the evidence sufficient, or is an LLM needed?">
            <DecisionPanel
              policy={evidence?.policy}
              decision={decision}
              semantic={semantic}
              running={running}
              error={runError}
              onRun={run}
            />
          </Section>

          <Section title="Suggested fix" note="how to bring the code back in line (a suggestion, nothing is changed)">
            <RecommendationPanel rec={rec} loading={recLoading} error={recError} onRun={suggestFix} />
          </Section>
        </>
      )}

      <details className="raw-json">
        <summary>Raw finding (JSON)</summary>
        <pre>{JSON.stringify({ ...finding, decision, semantic_analysis: semantic }, null, 2)}</pre>
      </details>
    </div>
  );
}

function Field({ label, main, sub }) {
  return (
    <div>
      <div className="field-label">{label}</div>
      <div className="mono">{main}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function Section({ title, note, children }) {
  return (
    <section className="evidence-section">
      <h4 className="section-title">
        {title}
        {note && <span className="section-note"> — {note}</span>}
      </h4>
      <div className="panel">{children}</div>
    </section>
  );
}
