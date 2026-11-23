import React, { useEffect, useState } from "react";
import { getRealAdrChecks } from "../api/client.js";

const pct = (v) => `${(Math.max(0, Number(v)) * 100).toFixed(1)}%`;

function countText(c) {
  if (!c) return "—";
  return `${c.k} of ${c.n} (95% CI ${pct(c.ci_low)} to ${pct(c.ci_high)})`;
}

// The benchmark above uses short, always-relevant ADRs. These two checks use real ADR text, and they answer
// different questions, so they are kept apart from the method comparison and each states what it does not show.
export default function RealAdrChecks() {
  const [data, setData] = useState(undefined); // undefined = loading, null = unavailable

  useEffect(() => {
    let alive = true;
    getRealAdrChecks()
      .then((d) => alive && setData(d))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, []);

  if (!data || (!data.false_permission && !data.case_study)) return null;
  const fp = data.false_permission;
  const cs = data.case_study;

  return (
    <div className="panel" data-testid="real-adr-checks">
      <h4 className="section-title">
        Checks on real ADR text <span className="section-note">— separate from the benchmark comparison above</span>
      </h4>
      <p className="muted">
        The benchmark's decision records are short and always relevant. These two checks use real records from open-source projects.
        They test different things and are not comparable with each other or with the table above.
      </p>

      {fp && (
        <div data-testid="false-permission">
          <h5>False-permission probe</h5>
          <div className="stat-grid">
            <div className="stat-card">
              <div className="stat-value forest" data-testid="fp-dangerous">
                {fp.dangerous.k} / {fp.dangerous.n}
              </div>
              <div className="stat-label">unrelated ADRs read as a permission (band {fp.band})</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{fp.misleading ? `${fp.misleading.k} / ${fp.misleading.n}` : "—"}</div>
              <div className="stat-label">misleading attributions</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{fp.selected_by_matcher ? `${fp.selected_by_matcher.k} / ${fp.selected_by_matcher.n}` : "—"}</div>
              <div className="stat-label">selected by the relevance matcher</div>
            </div>
          </div>
          <p>
            On {fp.n_primary} active real ADRs that do not govern dependencies, the model invented a permission {countText(fp.dangerous)}. The rate on
            similar text is unlikely to exceed {pct(fp.dangerous.ci_high)}; this is not a claim that it is zero.
          </p>
          <ul className="muted">
            <li>It measures one failure direction. It says nothing about whether the model correctly reads an ADR that does permit a dependency.</li>
            {fp.routes && fp.routes.structural === fp.n_primary && (
              <li data-testid="fp-routing-note">
                The product's routing sent all {fp.n_primary} cases down the structural path without a model call, so the pipeline-level figure is zero largely by
                construction. The model-level count above is the informative one.
              </li>
            )}
            <li>The dependencies are synthetic and unrelated to each ADR by construction; one 7B model, one pass, temperature 0.</li>
          </ul>
        </div>
      )}

      {cs && (
        <div data-testid="case-study">
          <h5>Seven hand-built cases</h5>
          <p>
            The model's verdict was correct on {cs.m7_correct} of {cs.n}. Always answering "violation" would also be correct on {cs.n_violations} of {cs.n},
            so this gives no evidence that the model beats that baseline.
            {cs.hidden_violations > 0 && (
              <>
                {" "}
                <strong data-testid="cs-hidden">
                  {cs.hidden_violations} real violation{cs.hidden_violations === 1 ? " was" : "s were"} called justified
                </strong>
                , the dangerous direction.
              </>
            )}
          </p>
          <table className="findings-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Truth</th>
                <th>Model</th>
                <th>Correct</th>
              </tr>
            </thead>
            <tbody>
              {cs.cases.map((c) => (
                <tr key={c.case_id} data-testid="cs-row">
                  <td>{c.case_id}</td>
                  <td>{c.expected}</td>
                  <td>{c.m7}</td>
                  <td>{c.m7_correct ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">Seven hand-picked cases are a demonstration, not a rate.</p>
        </div>
      )}
    </div>
  );
}
