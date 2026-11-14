import React, { useEffect, useMemo, useState } from "react";
import { getExperimentPredictions, getExperimentRun, listExperimentRuns } from "../api/client.js";
import { formatDate, formatFixed, formatInt, methodLabel, methodShort } from "../lib/format.js";

// Shows the outputs of `python -m experiments.run_experiments` so results can be
// inspected (and manually checked) without opening CSV files.
export default function Evaluation() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [run, setRun] = useState(null);
  const [split, setSplit] = useState("test");

  useEffect(() => {
    listExperimentRuns()
      .then((r) => {
        setRuns(r);
        if (r.length > 0) setSelected(r[r.length - 1].name);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setRun(null);
    getExperimentRun(selected)
      .then((r) => {
        setRun(r);
        const splits = [...new Set(r.metrics.map((m) => m.split))];
        setSplit(splits.includes("test") ? "test" : splits[0]);
      })
      .catch((e) => setError(e.message));
  }, [selected]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!runs) return <p className="empty-state">Loading…</p>;
  if (runs.length === 0) {
    return (
      <div>
        <PageHeader />
        <p className="empty-state" data-testid="no-runs">
          No experiment results found yet. Generate the benchmark and run the experiment, then reload:
          <br />
          <span className="mono">python -m experiments.benchmark.generate --out ../datasets/benchmark/generated</span>
          <br />
          <span className="mono">python -m experiments.run_experiments</span>
          <br />
          (see docs/EXPERIMENTS.md). Results are read from the <span className="mono">results/</span> folder.
        </p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader />
      <div className="panel filters">
        <label>
          Run{" "}
          <select value={selected || ""} onChange={(e) => setSelected(e.target.value)} data-testid="run-select">
            {runs.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
                {r.smoke_test ? " (smoke test)" : ""}
              </option>
            ))}
          </select>
        </label>
        {run && (
          <label>
            Split{" "}
            <select value={split} onChange={(e) => setSplit(e.target.value)} data-testid="split-select">
              {[...new Set(run.metrics.map((m) => m.split))].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
        {run && (
          <span className="muted">
            model: <span className="mono">{run.config.model || run.config.provider || "?"}</span>
            {run.config.prompt_version ? ` · prompt ${run.config.prompt_version}` : ""}
            {run.config.created ? ` · ${formatDate(run.config.created)}` : ""}
          </span>
        )}
      </div>

      {!run && <p className="empty-state">Loading run…</p>}
      {run && run.smoke_test && (
        <div className="error-banner" data-testid="smoke-banner">
          <strong>Smoke test — not results.</strong> This run used a keyword stand-in instead of a language model. It only shows
          that the pipeline runs end to end; do not quote these numbers.
        </div>
      )}
      {run && (
        <>
          <MetricsTable metrics={run.metrics.filter((m) => m.split === split)} />
          <Frontier metrics={run.metrics.filter((m) => m.split === split)} />
          <PairedTable rows={(run.paired || []).filter((r) => r.split === split)} />
          <DensityTable rows={(run.density || []).filter((r) => r.split === split)} />
          <Heatmap rows={run.by_scenario} />
          <Inspector runName={selected} methods={[...new Set(run.by_scenario.map((r) => r.method))]} scenarios={[...new Set(run.by_scenario.map((r) => r.scenario))]} />
        </>
      )}
    </div>
  );
}

function PageHeader() {
  return (
    <div className="page-header">
      <h1 className="page-title">Evaluation</h1>
      <p className="page-desc">
        Static rules, LLM-only, full hybrid, generic selective and the evidence-guided approach compared on a controlled
        benchmark. A dependency the benchmark labels <em>justified</em> but a method reports as a violation counts as a false
        positive.
      </p>
    </div>
  );
}

function MetricsTable({ metrics }) {
  const rows = [...metrics].sort((a, b) => String(a.method).localeCompare(String(b.method)));
  return (
    <div className="table-wrap">
      <table className="findings-table metrics-table" data-testid="metrics-table">
        <thead>
          <tr>
            <th>Method</th>
            <th>Precision</th>
            <th>Recall</th>
            <th>F1 (95% CI)</th>
            <th>False-pos. rate</th>
            <th>LLM calls</th>
            <th>Tokens in / out</th>
            <th>LLM time (s)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.method} className={m.method.startsWith("M5") ? "highlight" : ""}>
              <td>{methodLabel(m.method)}</td>
              <td className="num">{formatFixed(m.precision)}</td>
              <td className="num">{formatFixed(m.recall)}</td>
              <td className="num">
                {formatFixed(m.f1)}
                {m.f1_ci_low != null && m.f1_ci_high != null && (
                  <span className="muted"> ({formatFixed(m.f1_ci_low, 2)}–{formatFixed(m.f1_ci_high, 2)})</span>
                )}
                {m.f1_sd != null && <span className="muted"> ± {formatFixed(m.f1_sd, 3)} sd</span>}
              </td>
              <td className="num">{formatFixed(m.false_positive_rate)}</td>
              <td className="num">{formatInt(m.llm_calls)}</td>
              <td className="num">
                {formatInt(m.input_tokens)} / {formatInt(m.output_tokens)}
              </td>
              <td className="num">{formatFixed(m.llm_latency_s, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Is M5's difference from each other method distinguishable from noise? Computed on the SAME cases
// (case-level paired bootstrap), so the interval reflects how the methods differ, not how each varies.
function PairedTable({ rows }) {
  const shown = rows.filter((r) => ["f1", "false_positive_rate", "llm_calls"].includes(r.metric));
  if (shown.length === 0) return null;
  const verdict = (r) => {
    if (r.ci_low == null || r.ci_high == null) return "—";
    if (r.ci_low > 0) return "M5 higher";
    if (r.ci_high < 0) return "M5 lower";
    return "not distinguishable";
  };
  const names = { f1: "F1", false_positive_rate: "false-positive rate", llm_calls: "LLM calls" };
  return (
    <div className="panel" data-testid="paired">
      <h4 className="section-title">
        M5 versus each other method <span className="section-note">— same cases, 95% paired bootstrap</span>
      </h4>
      <div className="table-wrap">
        <table className="findings-table metrics-table">
          <thead>
            <tr>
              <th>Compared with</th>
              <th>Metric</th>
              <th>M5</th>
              <th>Other</th>
              <th>Difference (95% CI)</th>
              <th>Reading</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} data-testid="paired-row">
                <td>{r.b.includes("M4_generic_selective_s") ? methodLabel("M4_generic_selective_mean") : methodLabel(r.b)}</td>
                <td>{names[r.metric]}</td>
                <td className="num">{formatFixed(r.a_value, r.metric === "llm_calls" ? 0 : 3)}</td>
                <td className="num">{formatFixed(r.b_value, r.metric === "llm_calls" ? 0 : 3)}</td>
                <td className="num">
                  {formatFixed(r.delta, r.metric === "llm_calls" ? 0 : 3)}
                  <span className="muted"> ({formatFixed(r.ci_low, r.metric === "llm_calls" ? 0 : 3)} to {formatFixed(r.ci_high, r.metric === "llm_calls" ? 0 : 3)})</span>
                </td>
                <td>{verdict(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Our benchmark is ADR-dense. How much of the call saving survives if fewer dependencies have a
// decision record? A RE-WEIGHTING of the existing results, not new data.
function DensityTable({ rows }) {
  const pick = rows.filter((r) => ["M3_full_hybrid", "M5_evidence_guided"].includes(r.method));
  if (pick.length === 0) return null;
  const densities = [...new Set(pick.map((r) => r.adr_density))].sort((a, b) => a - b);
  const cell = (method, d) => pick.find((r) => r.method === method && r.adr_density === d);
  return (
    <div className="panel" data-testid="density">
      <h4 className="section-title">
        If fewer dependencies had a decision record{" "}
        <span className="section-note">— re-weighted from the same results, not new data</span>
      </h4>
      <div className="table-wrap">
        <table className="findings-table metrics-table">
          <thead>
            <tr>
              <th>Share of dependencies with a record</th>
              {densities.map((d) => (
                <th key={d}>{Math.round(d * 100)}%</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {["M3_full_hybrid", "M5_evidence_guided"].map((m) => (
              <tr key={m}>
                <td>{methodLabel(m)}: LLM calls per case</td>
                {densities.map((d) => (
                  <td key={d} className="num">{formatFixed(cell(m, d)?.llm_calls_per_case, 2)}</td>
                ))}
              </tr>
            ))}
            <tr className="highlight">
              <td>M5 calls saved vs M3</td>
              {densities.map((d) => {
                const v = cell("M5_evidence_guided", d)?.calls_saved_vs_m3;
                return <td key={d} className="num">{v == null ? "—" : `${Math.round(v * 100)}%`}</td>;
              })}
            </tr>
            <tr>
              <td>M5 F1</td>
              {densities.map((d) => (
                <td key={d} className="num">{formatFixed(cell("M5_evidence_guided", d)?.f1)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// F1 against LLM cost: the question the project asks is whether evidence lets us
// keep accuracy while calling the model less.
function Frontier({ metrics }) {
  const pts = metrics.filter((m) => m.f1 != null && m.llm_calls != null);
  if (pts.length === 0) return null;
  const W = 640, H = 320, L = 56, R = 24, T = 20, B = 46;
  const maxX = Math.max(1, ...pts.map((p) => p.llm_calls)) * 1.1;
  const x = (v) => L + (v / maxX) * (W - L - R);
  const y = (v) => T + (1 - v) * (H - T - B);
  return (
    <div className="panel" data-testid="frontier">
      <h4 className="section-title">Accuracy vs LLM cost</h4>
      <svg viewBox={`0 0 ${W} ${H}`} className="frontier-svg" role="img" aria-label="F1 versus number of LLM calls">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" />
            <text x={L - 8} y={y(t) + 4} textAnchor="end" className="axis-text">{t.toFixed(2)}</text>
          </g>
        ))}
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} className="axis" />
        <line x1={L} x2={L} y1={T} y2={y(0)} className="axis" />
        <text x={(L + W - R) / 2} y={H - 8} textAnchor="middle" className="axis-text">LLM calls</text>
        <text x={14} y={(T + H - B) / 2} textAnchor="middle" transform={`rotate(-90 14 ${(T + H - B) / 2})`} className="axis-text">F1</text>
        {pts.map((p) => {
          const proposed = p.method.startsWith("M5");
          return (
            <g key={p.method} data-testid={`pt-${methodShort(p.method)}`}>
              {p.f1_ci_low != null && p.f1_ci_high != null && (
                <line x1={x(p.llm_calls)} x2={x(p.llm_calls)} y1={y(p.f1_ci_low)} y2={y(p.f1_ci_high)} className="ci" />
              )}
              <circle cx={x(p.llm_calls)} cy={y(p.f1)} r={proposed ? 7 : 5} className={proposed ? "pt proposed" : "pt"}>
                <title>{`${methodLabel(p.method)}: F1 ${formatFixed(p.f1)}, ${formatInt(p.llm_calls)} LLM calls`}</title>
              </circle>
              <text x={x(p.llm_calls) + 9} y={y(p.f1) - 8} className="pt-label">{methodShort(p.method)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// Where does each evidence source matter? Accuracy of the decision on the
// targeted dependency, by scenario and method.
function Heatmap({ rows }) {
  const methods = useMemo(() => [...new Set(rows.map((r) => r.method))].sort(), [rows]);
  const scenarios = useMemo(() => [...new Set(rows.map((r) => r.scenario))].sort(), [rows]);
  if (rows.length === 0) return null;
  const cell = (s, m) => rows.find((r) => r.scenario === s && r.method === m);
  return (
    <div className="panel" data-testid="heatmap">
      <h4 className="section-title">Decision accuracy by scenario <span className="section-note">— where each evidence source matters</span></h4>
      <div className="table-wrap">
        <table className="heat-table">
          <thead>
            <tr>
              <th />
              {methods.map((m) => (
                <th key={m} title={methodLabel(m)}>{methodShort(m)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {scenarios.map((s) => (
              <tr key={s}>
                <td className="scenario-name">{s.replace(/_/g, " ")}</td>
                {methods.map((m) => {
                  const c = cell(s, m);
                  const a = c ? c.accuracy : null;
                  return (
                    <td
                      key={m}
                      data-testid={`heat-${s}-${m}`}
                      className="heat-cell"
                      style={a == null ? undefined : { background: `hsla(${Math.round(a * 120)}, 55%, 38%, 0.55)` }}
                      title={c ? `${c.correct}/${c.cases} correct, ${c.llm_calls} LLM calls` : ""}
                    >
                      {a == null ? "—" : `${Math.round(a * 100)}%`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// For manual checks: look at what a method decided for each targeted dependency,
// and read the model's explanation.
function Inspector({ runName, methods, scenarios }) {
  const [method, setMethod] = useState("");
  const [scenario, setScenario] = useState("");
  const [wrongOnly, setWrongOnly] = useState(false);
  const [llmOnly, setLlmOnly] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    getExperimentPredictions(runName, { method, scenario, wrong_only: wrongOnly, llm_only: llmOnly, limit: 200 })
      .then(setData)
      .catch((e) => setError(e.message));
  }, [runName, method, scenario, wrongOnly, llmOnly]);

  return (
    <div className="panel" data-testid="inspector">
      <h4 className="section-title">Inspect predictions <span className="section-note">— for manual checking</span></h4>
      <div className="filters">
        <label>
          Method{" "}
          <select value={method} onChange={(e) => setMethod(e.target.value)} data-testid="inspector-method">
            <option value="">all</option>
            {methods.map((m) => (
              <option key={m} value={m}>{methodLabel(m)}</option>
            ))}
          </select>
        </label>
        <label>
          Scenario{" "}
          <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
            <option value="">all</option>
            {scenarios.map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={wrongOnly} onChange={(e) => setWrongOnly(e.target.checked)} data-testid="wrong-only" /> wrong only
        </label>
        <label className="check">
          <input type="checkbox" checked={llmOnly} onChange={(e) => setLlmOnly(e.target.checked)} /> LLM-decided only
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {data && (
        <>
          <p className="muted">
            showing {data.returned} of {data.total}
          </p>
          <div className="table-wrap">
            <table className="findings-table inspector-table">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Case</th>
                  <th>Truth</th>
                  <th>Predicted</th>
                  <th>Decided by</th>
                  <th>Explanation / policy reason</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => {
                  const wrong = Boolean(r.predicted_violation) !== (r.truth === "violation");
                  return (
                    <tr key={i} className={wrong ? "wrong" : ""} data-testid="pred-row">
                      <td>{methodShort(r.method)}</td>
                      <td className="mono">{r.case_id}</td>
                      <td><span className={`status-pill ${r.truth === "violation" ? "violation" : "justified"}`}>{r.truth}</span></td>
                      <td>{r.predicted_violation ? "violation" : "not a violation"}</td>
                      <td>{r.outcome_source}</td>
                      <td className="explain" title={r.explanation || r.policy_reasons || ""}>
                        {r.explanation || r.policy_reasons || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
