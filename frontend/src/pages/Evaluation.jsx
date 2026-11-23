import React, { useEffect, useMemo, useState } from "react";
import { getExperimentPredictions, getExperimentRun, listExperimentRuns } from "../api/client.js";
import { PROPOSED_METHOD, formatDate, formatFixed, formatInt, methodLabel, methodShort } from "../lib/format.js";
import RealAdrChecks from "../components/RealAdrChecks.jsx";

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
        <RealAdrChecks />
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
        {run && <RunInfo config={run.config} />}
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
      <RealAdrChecks />
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

// Which model / prompt / date produced the run. Leaves out whatever the run did not record, rather than showing "?".
function RunInfo({ config }) {
  const model = config.model || config.provider;
  const extras = [config.prompt_version ? `prompt ${config.prompt_version}` : null, config.created ? formatDate(config.created) : null].filter(Boolean);
  if (!model && extras.length === 0) return null;
  return (
    <span className="muted">
      {model && (
        <>
          model: <span className="mono">{model}</span>
        </>
      )}
      {extras.length > 0 && `${model ? " · " : ""}${extras.join(" · ")}`}
    </span>
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
            <tr key={m.method} className={m.method === PROPOSED_METHOD ? "highlight" : ""}>
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

// Is one method's difference from each other method distinguishable from noise? Computed on the SAME cases
// (case-level paired bootstrap), so the interval reflects how the methods differ, not how each varies.
// The run holds comparisons for several reference methods (M5, M7, M8, M8+attr); the reader picks one,
// defaulting to the proposed method. One row per comparison, F1 and LLM calls side by side.
// (The false-positive rate is in the table above; it is ~0.001 for every LLM-backed method, so a row for it adds nothing.)
function PairedTable({ rows }) {
  const refs = useMemo(() => [...new Set(rows.map((r) => r.a))], [rows]);
  const [chosen, setChosen] = useState(null);
  if (refs.length === 0) return null;
  const ref = refs.includes(chosen)
    ? chosen
    : [PROPOSED_METHOD, "M5_evidence_guided"].find((m) => refs.includes(m)) || refs[0];
  const short = methodShort(ref);

  const byOther = new Map();
  rows
    .filter((r) => r.a === ref && (r.metric === "f1" || r.metric === "llm_calls"))
    .forEach((r) => byOther.set(r.b, { ...(byOther.get(r.b) || {}), [r.metric]: r }));
  if (byOther.size === 0) return null;

  const otherLabel = (b) => (b.includes("M4_generic_selective_s") ? methodLabel("M4_generic_selective_mean") : methodLabel(b));
  const f1Reading = (r) => {
    if (!r || r.ci_low == null || r.ci_high == null) return "—";
    if (r.ci_low > 0) return `${short} higher`;
    if (r.ci_high < 0) return `${short} lower`;
    return "not distinguishable";
  };
  const callsReading = (r) => {
    if (!r || r.ci_low == null || r.ci_high == null) return "—";
    if (r.ci_high < 0) return `${short} lower`;
    if (r.ci_low > 0) return `${short} higher`;
    return "not distinguishable";
  };
  const pair = (r, d) => (r ? `${formatFixed(r.a_value, d)} vs ${formatFixed(r.b_value, d)}` : "—");
  const diff = (r, d) =>
    r ? (
      <>
        {formatFixed(r.delta, d)}
        <span className="muted"> ({formatFixed(r.ci_low, d)} to {formatFixed(r.ci_high, d)})</span>
      </>
    ) : (
      "—"
    );

  return (
    <div className="panel" data-testid="paired">
      <div className="panel-head">
        <h4 className="section-title">
          {short} versus each other method <span className="section-note">— same cases, 95% paired bootstrap</span>
        </h4>
        {refs.length > 1 && (
          <label className="filters">
            Reference{" "}
            <select value={ref} onChange={(e) => setChosen(e.target.value)} data-testid="paired-ref">
              {refs.map((m) => (
                <option key={m} value={m}>{methodLabel(m)}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="table-wrap scroll-y">
        <table className="findings-table metrics-table">
          <thead>
            <tr>
              <th>Compared with</th>
              <th>F1 ({short} vs other)</th>
              <th>F1 difference (95% CI)</th>
              <th>LLM calls ({short} vs other)</th>
              <th>Calls difference (95% CI)</th>
            </tr>
          </thead>
          <tbody>
            {[...byOther.entries()].map(([b, r]) => (
              <tr key={b} data-testid="paired-row">
                <td>{otherLabel(b)}</td>
                <td className="num">{pair(r.f1, 3)}</td>
                <td className="num">
                  {diff(r.f1, 3)}
                  <div className="reading">{f1Reading(r.f1)}</div>
                </td>
                <td className="num">{pair(r.llm_calls, 0)}</td>
                <td className="num">
                  {diff(r.llm_calls, 0)}
                  <div className="reading">{callsReading(r.llm_calls)}</div>
                </td>
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

// Place each point's label to its right, trying a few vertical offsets, so labels of points that sit almost on
// top of each other (M8 and M8+attr: same cost, F1 0.97 vs 0.99) do not overprint and none leaves the plot.
// A label that is not directly up-right of its point gets a faint leader line. Earlier entries in `pts` get first choice:
// pass the proposed method first.
function placeLabels(pts, x, y, bounds, charW = 7.6) {
  const taken = [];
  const out = new Map();
  pts.forEach((p) => {
    const text = methodShort(p.method);
    const w = text.length * charW;
    const cx = x(p.llm_calls);
    const cy = y(p.f1);
    const options = [-8, 14, -22, 28, -36, 42].map((dy) => ({ lx: cx + 9, dy }));
    const box = (o) => ({ x0: o.lx, x1: o.lx + w, y0: cy + o.dy - 10, y1: cy + o.dy + 3 });
    const inside = (b) => b.x0 >= bounds.left && b.x1 <= bounds.right && b.y0 >= bounds.top && b.y1 <= bounds.bottom;
    const clear = (b) => !taken.some((t) => b.x0 < t.x1 && b.x1 > t.x0 && b.y0 < t.y1 && b.y1 > t.y0);
    const choice = options.find((o) => inside(box(o)) && clear(box(o))) || options.find((o) => inside(box(o))) || options[0];
    taken.push(box(choice));
    out.set(p.method, { x: choice.lx, y: cy + choice.dy, text, leader: choice.dy !== -8 ? { x1: cx + 3, y1: cy + (choice.dy > 0 ? 3 : -3), x2: choice.lx - 2, y2: cy + choice.dy - 3 } : null });
  });
  return out;
}

// F1 against LLM cost: the question the project asks is whether evidence lets us
// keep accuracy while calling the model less.
// The F1 axis is cropped to the data (it says so on the axis): on 0-1 the top methods are a few pixels apart.
function Frontier({ metrics }) {
  const pts = metrics.filter((m) => m.f1 != null && m.llm_calls != null);
  if (pts.length === 0) return null;
  const W = 640, H = 320, L = 56, R = 24, T = 20, B = 46;
  const maxX = Math.max(1, ...pts.map((p) => p.llm_calls)) * 1.1;
  const lowest = Math.min(...pts.map((p) => (p.f1_ci_low != null ? Math.min(p.f1, p.f1_ci_low) : p.f1)));
  const yMin = Math.max(0, Math.floor((lowest - 0.03) * 10) / 10);
  const span = 1 - yMin;
  const step = span > 0.6 ? 0.25 : 0.1;
  const ticks = [];
  for (let t = yMin; t <= 1 + 1e-9; t += step) ticks.push(Math.round(t * 100) / 100);
  const x = (v) => L + (v / maxX) * (W - L - R);
  const y = (v) => T + ((1 - v) / span) * (H - T - B);
  const drawn = [...pts].sort((a, b) => (a.method === PROPOSED_METHOD) - (b.method === PROPOSED_METHOD)); // proposed on top
  const labels = placeLabels(
    [...pts].sort((a, b) => (b.method === PROPOSED_METHOD) - (a.method === PROPOSED_METHOD) || b.f1 - a.f1),
    x,
    y,
    { left: L, right: W - 4, top: 4, bottom: y(yMin) }
  );
  return (
    <div className="panel" data-testid="frontier">
      <h4 className="section-title">Accuracy vs LLM cost</h4>
      <svg viewBox={`0 0 ${W} ${H}`} className="frontier-svg" role="img" aria-label="F1 versus number of LLM calls">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" />
            <text x={L - 8} y={y(t) + 4} textAnchor="end" className="axis-text">{t.toFixed(2)}</text>
          </g>
        ))}
        <line x1={L} x2={W - R} y1={y(yMin)} y2={y(yMin)} className="axis" />
        <line x1={L} x2={L} y1={T} y2={y(yMin)} className="axis" />
        <text x={(L + W - R) / 2} y={H - 8} textAnchor="middle" className="axis-text">LLM calls</text>
        <text x={14} y={(T + H - B) / 2} textAnchor="middle" transform={`rotate(-90 14 ${(T + H - B) / 2})`} className="axis-text">
          {yMin > 0 ? `F1 (axis starts at ${yMin.toFixed(2)})` : "F1"}
        </text>
        {drawn.map((p) => {
          const proposed = p.method === PROPOSED_METHOD;
          const label = labels.get(p.method);
          return (
            <g key={p.method} data-testid={`pt-${methodShort(p.method)}`}>
              {p.f1_ci_low != null && p.f1_ci_high != null && (
                <line x1={x(p.llm_calls)} x2={x(p.llm_calls)} y1={y(p.f1_ci_low)} y2={y(p.f1_ci_high)} className="ci" />
              )}
              <circle cx={x(p.llm_calls)} cy={y(p.f1)} r={proposed ? 7 : 5} className={proposed ? "pt proposed" : "pt"}>
                <title>{`${methodLabel(p.method)}: F1 ${formatFixed(p.f1)}, ${formatInt(p.llm_calls)} LLM calls`}</title>
              </circle>
              {label.leader && <line {...label.leader} className="leader" />}
              <text x={label.x} y={label.y} className="pt-label">{label.text}</text>
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

const PAGE = 25;

// For manual checks: look at what a method decided for each targeted dependency,
// and read the model's explanation. Collapsed until opened (nothing is fetched before then). When the
// proposed method is in the run it starts on that method's mistakes, the rows worth checking by hand.
function Inspector({ runName, methods, scenarios }) {
  const focus = methods.includes(PROPOSED_METHOD);
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState(focus ? PROPOSED_METHOD : "");
  const [scenario, setScenario] = useState("");
  const [wrongOnly, setWrongOnly] = useState(focus);
  const [llmOnly, setLlmOnly] = useState(false);
  const [limit, setLimit] = useState(PAGE);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  // a filter change starts again from the first page
  const filter = (setter) => (value) => {
    setter(value);
    setLimit(PAGE);
  };

  useEffect(() => {
    if (!open) return;
    setError(null);
    getExperimentPredictions(runName, { method, scenario, wrong_only: wrongOnly, llm_only: llmOnly, limit })
      .then(setData)
      .catch((e) => setError(e.message));
  }, [open, runName, method, scenario, wrongOnly, llmOnly, limit]);

  const hasExplanation = data ? data.rows.some((r) => r.explanation || r.policy_reasons) : false;

  return (
    <div className="panel" data-testid="inspector">
      <button type="button" className="collapse-head" aria-expanded={open} onClick={() => setOpen((o) => !o)} data-testid="inspector-toggle">
        <span className="caret">{open ? "▾" : "▸"}</span>
        <span className="section-title">
          Inspect predictions <span className="section-note">— for manual checking</span>
        </span>
      </button>
      {open && (
        <>
          <div className="filters inspector-filters">
            <label>
              Method{" "}
              <select value={method} onChange={(e) => filter(setMethod)(e.target.value)} data-testid="inspector-method">
                <option value="">all</option>
                {methods.map((m) => (
                  <option key={m} value={m}>{methodLabel(m)}</option>
                ))}
              </select>
            </label>
            <label>
              Scenario{" "}
              <select value={scenario} onChange={(e) => filter(setScenario)(e.target.value)}>
                <option value="">all</option>
                {scenarios.map((s) => (
                  <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={wrongOnly} onChange={(e) => filter(setWrongOnly)(e.target.checked)} data-testid="wrong-only" /> wrong only
            </label>
            <label className="check">
              <input type="checkbox" checked={llmOnly} onChange={(e) => filter(setLlmOnly)(e.target.checked)} /> LLM-decided only
            </label>
          </div>
          {error && <div className="error-banner">{error}</div>}
          {data && (
            <>
              <p className="muted">
                showing {data.returned} of {data.total}
              </p>
              {data.rows.length === 0 ? (
                <p className="muted" data-testid="no-pred-rows">
                  {wrongOnly ? "No wrong predictions for these filters." : "No predictions for these filters."}
                </p>
              ) : (
                <div className="table-wrap scroll-y tall">
                  <table className="findings-table inspector-table">
                    <thead>
                      <tr>
                        <th>Method</th>
                        <th>Case</th>
                        <th>Truth</th>
                        <th>Predicted</th>
                        <th>Decided by</th>
                        {hasExplanation && <th>Explanation / policy reason</th>}
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
                            {hasExplanation && (
                              <td className="explain" title={r.explanation || r.policy_reasons || ""}>
                                {r.explanation || r.policy_reasons || "—"}
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {data.returned < data.total && limit < 1000 && (
                <button type="button" className="show-more" onClick={() => setLimit((l) => Math.min(1000, l + PAGE))} data-testid="show-more">
                  Show {Math.min(PAGE, data.total - data.returned)} more
                </button>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
