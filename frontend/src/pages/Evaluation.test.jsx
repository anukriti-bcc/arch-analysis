import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Evaluation from "./Evaluation.jsx";
import { mockApi } from "../test/mockApi.js";
import runs from "../__fixtures__/experiment_runs.json";
import run from "../__fixtures__/experiment_run.json";
import preds from "../__fixtures__/experiment_predictions.json";
import realChecks from "../__fixtures__/real_adr_checks.json";

afterEach(() => vi.unstubAllGlobals());

function routes(over = {}) {
  return [
    ["GET", /\/experiments\/runs$/, over.runs ?? runs],
    ["GET", /\/experiments\/runs\/smoke$/, over.run ?? run],
    ["GET", /\/experiments\/runs\/smoke\/predictions/, over.preds ?? preds],
  ];
}

describe("Evaluation page", () => {
  it("shows the real-ADR checks apart from the method comparison, and still works if they are unavailable", async () => {
    mockApi([...routes(), ["GET", /\/experiments\/real-adr-checks$/, realChecks]]);
    const { unmount } = render(<Evaluation />);
    await screen.findByTestId("metrics-table");
    const panel = await screen.findByTestId("real-adr-checks");
    expect(within(panel).getByText(/separate from the benchmark comparison/)).toBeInTheDocument();
    expect(within(screen.getByTestId("metrics-table")).queryByText(/false-permission/i)).not.toBeInTheDocument();
    unmount();
    mockApi(routes());
    render(<Evaluation />);
    await screen.findByTestId("metrics-table");
    expect(screen.queryByTestId("real-adr-checks")).not.toBeInTheDocument();
  });


  it("explains how to produce results when there are none", async () => {
    mockApi([["GET", /runs$/, []]]);
    render(<Evaluation />);
    expect(await screen.findByTestId("no-runs")).toHaveTextContent("run_experiments");
  });

  it("flags a smoke-test run so its numbers are not mistaken for results", async () => {
    mockApi(routes());
    render(<Evaluation />);
    expect(await screen.findByTestId("smoke-banner")).toHaveTextContent("not results");
    expect(screen.getByRole("option", { name: "smoke (smoke test)" })).toBeInTheDocument();
  });

  it("does not show the smoke banner for a real run", async () => {
    mockApi(routes({ run: { ...run, smoke_test: false, config: { ...run.config, provider: "openai-compatible", model: "arch-judge" } }, runs: [{ ...runs[0], smoke_test: false }] }));
    render(<Evaluation />);
    await screen.findByTestId("metrics-table");
    expect(screen.queryByTestId("smoke-banner")).not.toBeInTheDocument();
    expect(screen.getByText("arch-judge")).toBeInTheDocument();
  });

  it("lists every method with its metrics, highlighting the proposed approach", async () => {
    mockApi(routes());
    render(<Evaluation />);
    const table = within(await screen.findByTestId("metrics-table"));
    ["M1 Static rules", "M2 LLM-only", "M3 Full hybrid", "M5 Evidence-guided (v1 policy)", "A1 No evolution evidence"].forEach((t) =>
      expect(table.getByText(t)).toBeInTheDocument()
    );
    expect(table.getByText("M5 Evidence-guided (v1 policy)").closest("tr")).not.toHaveClass("highlight");
    expect(table.getByText(/mean of seeds/)).toBeInTheDocument();
  });

  it("draws one point per method on the accuracy-vs-cost chart", async () => {
    mockApi(routes());
    render(<Evaluation />);
    const chart = await screen.findByTestId("frontier");
    ["M1", "M2", "M3", "M4", "M5", "A1"].forEach((m) => expect(within(chart).getByTestId(`pt-${m}`)).toBeInTheDocument());
  });

  it("shows the scenario heat map with percentages", async () => {
    mockApi(routes());
    render(<Evaluation />);
    const map = await screen.findByTestId("heatmap");
    const cell = within(map).getByTestId("heat-A_plain_violation-M1_static");
    expect(cell).toHaveTextContent("100%");
  });

  it("lists predictions for manual checking and marks wrong ones", async () => {
    mockApi(routes());
    render(<Evaluation />);
    await userEvent.click(await screen.findByTestId("inspector-toggle"));
    const rows = await screen.findAllByTestId("pred-row");
    expect(rows.length).toBe(preds.rows.length);
    const wrongExpected = preds.rows.filter((r) => Boolean(r.predicted_violation) !== (r.truth === "violation")).length;
    expect(rows.filter((r) => r.classList.contains("wrong")).length).toBe(wrongExpected);
  });

  it("re-queries the server when a filter changes", async () => {
    const { calls } = mockApi(routes());
    render(<Evaluation />);
    await userEvent.click(await screen.findByTestId("inspector-toggle"));
    await screen.findAllByTestId("pred-row");
    await userEvent.click(screen.getByTestId("wrong-only"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("wrong_only=true"))).toBe(true));
    await userEvent.selectOptions(screen.getByTestId("inspector-method"), "M5_evidence_guided");
    await waitFor(() => expect(calls.some((c) => c.url.includes("method=M5_evidence_guided"))).toBe(true));
  });

  it("shows server errors", async () => {
    mockApi([["GET", /runs$/, { __status: 500, detail: "results folder unreadable" }]]);
    render(<Evaluation />);
    expect(await screen.findByText("results folder unreadable")).toBeInTheDocument();
  });

  it("tolerates a run with missing metric values", async () => {
    const sparse = { ...run, metrics: run.metrics.map((m) => ({ ...m, f1: null, f1_ci_low: null, f1_ci_high: null, precision: null })) };
    mockApi(routes({ run: sparse }));
    render(<Evaluation />);
    expect(await screen.findByTestId("metrics-table")).toBeInTheDocument();
    expect(screen.queryByTestId("frontier")).not.toBeInTheDocument();
  });
});


describe("Evaluation page — paired comparison and ADR-density sections", () => {
  const withPaired = (paired, density = run.density) => ({ ...run, paired, density });
  const row = (over) => ({ a: "M5_evidence_guided", b: "M3_full_hybrid", split: "test", metric: "f1", a_value: 0.9, b_value: 0.8,
    delta: 0.1, ci_low: 0.02, ci_high: 0.18, n_cases: 28, ...over });

  it("reads each interval: higher, not distinguishable, and fewer calls", async () => {
    mockApi(routes({ run: withPaired([
      row({}),
      row({ metric: "llm_calls", a_value: 12, b_value: 28, delta: -16, ci_low: -22, ci_high: -9 }),
      row({ b: "A1_no_history", delta: 0.01, ci_low: -0.05, ci_high: 0.07 }),
    ]) }));
    render(<Evaluation />);
    const table = within(await screen.findByTestId("paired"));
    const rows = table.getAllByTestId("paired-row");
    expect(rows).toHaveLength(2);                              // one row per comparison, F1 and calls together
    expect(rows[0]).toHaveTextContent("M3 Full hybrid");
    expect(rows[0]).toHaveTextContent("M5 higher");
    expect(rows[0]).toHaveTextContent("M5 lower");             // fewer calls is a negative difference
    expect(rows[0]).toHaveTextContent("-16 (-22 to -9)");      // calls shown as whole numbers
    expect(rows[0]).toHaveTextContent("12 vs 28");
    expect(rows[1]).toHaveTextContent("not distinguishable");
  });

  it("leaves the false-positive-rate rows out", async () => {
    mockApi(routes({ run: withPaired([row({}), row({ metric: "false_positive_rate", delta: 0, ci_low: 0, ci_high: 0 })]) }));
    render(<Evaluation />);
    const table = within(await screen.findByTestId("paired"));
    expect(table.getAllByTestId("paired-row")).toHaveLength(1);
    expect(table.queryByText(/false-positive/i)).not.toBeInTheDocument();
  });

  it("defaults to the proposed method as the reference and lets the reader switch, with the title following", async () => {
    mockApi(routes({ run: withPaired([
      row({ a: "M5_evidence_guided", b: "M1_static" }),
      row({ a: "M7_extract_compute", b: "M1_static", a_value: 0.97 }),
      row({ a: "M8_gated_attr", b: "M7_extract_compute", a_value: 0.993, b_value: 0.972 }),
      row({ a: "M8_gated_attr", b: "M8_gated", a_value: 0.993, b_value: 0.972 }),
    ]) }));
    render(<Evaluation />);
    const panel = within(await screen.findByTestId("paired"));
    expect(panel.getByTestId("paired-ref")).toHaveValue("M8_gated_attr");
    expect(panel.getByText(/M8\+attr versus each other method/)).toBeInTheDocument();
    expect(panel.getAllByTestId("paired-row")).toHaveLength(2);
    expect(panel.getByText("M8 Readability-gated")).toBeInTheDocument();
    await userEvent.selectOptions(panel.getByTestId("paired-ref"), "M5_evidence_guided");
    expect(panel.getAllByTestId("paired-row")).toHaveLength(1);
    expect(panel.getByText(/M5 versus each other method/)).toBeInTheDocument();
  });

  it("scrolls inside its panel instead of lengthening the page", async () => {
    mockApi(routes({ run: withPaired([row({})]) }));
    render(<Evaluation />);
    const panel = await screen.findByTestId("paired");
    expect(panel.querySelector(".table-wrap")).toHaveClass("scroll-y");
  });

  it("labels the averaged randomised baseline as one method", async () => {
    mockApi(routes({ run: withPaired([row({ b: "M4_generic_selective_s0..(x5)" })]) }));
    render(<Evaluation />);
    const paired = within(await screen.findByTestId("paired"));
    expect(paired.getByText(/M4 Generic selective \(mean of seeds\)/)).toBeInTheDocument();
  });

  it("hides both sections when the run has no such files", async () => {
    mockApi(routes({ run: { ...run, paired: [], density: [] } }));
    render(<Evaluation />);
    await screen.findByTestId("metrics-table");
    expect(screen.queryByTestId("paired")).not.toBeInTheDocument();
    expect(screen.queryByTestId("density")).not.toBeInTheDocument();
  });

  it("shows how call savings change with the share of dependencies that have a record", async () => {
    const d = (method, adr_density, calls, saved, f1 = 0.9) => ({ method, split: "test", adr_density, f1, llm_calls_per_case: calls, calls_saved_vs_m3: saved });
    mockApi(routes({ run: withPaired([], [
      d("M3_full_hybrid", 0.1, 1, 0), d("M5_evidence_guided", 0.1, 0.1, 0.9),
      d("M3_full_hybrid", 1, 1, 0), d("M5_evidence_guided", 1, 1, 0),
    ]) }));
    render(<Evaluation />);
    const table = within(await screen.findByTestId("density"));
    expect(table.getByText("10%")).toBeInTheDocument();
    expect(table.getByText("100%")).toBeInTheDocument();
    const saved = table.getByText("M5 calls saved vs M3").closest("tr");
    expect(saved).toHaveTextContent("90%");
    expect(saved).toHaveTextContent("0%");
    expect(table.getByText("M5 Evidence-guided (v1 policy): LLM calls per case").closest("tr")).toHaveTextContent("0.10");
  });

  it("renders from real exported fixtures too", async () => {
    mockApi(routes());
    render(<Evaluation />);
    expect(await screen.findByTestId("paired")).toBeInTheDocument();
    expect(screen.getByTestId("density")).toBeInTheDocument();
  });
});


describe("Evaluation page — M8 variants, run info and inspector", () => {
  const m = (method, f1, calls, lo, hi) => ({ method, split: "confirm", precision: 0.99, recall: 0.9, f1, f1_ci_low: lo, f1_ci_high: hi,
    false_positive_rate: 0.001, llm_calls: calls, input_tokens: 1, output_tokens: 1, llm_latency_s: 1 });
  const pooled = {
    ...run, smoke_test: false, config: {}, paired: [], density: [],
    metrics: [m("M1_static", 0.8, 0, 0.75, 0.84), m("M7_extract_compute", 0.972, 171, 0.95, 0.99),
      m("M8_gated", 0.972, 156, 0.95, 0.99), m("M8_gated_attr", 0.993, 156, 0.98, 1)],
    by_scenario: ["M1_static", "M8_gated", "M8_gated_attr"].map((method) => ({ scenario: "A_plain_violation", method, accuracy: 1, correct: 1, cases: 1, llm_calls: 0 })),
  };
  const poolRoutes = () => [
    ["GET", /\/experiments\/runs$/, [{ ...runs[0], smoke_test: false }]],
    ["GET", /\/experiments\/runs\/smoke$/, pooled],
    ["GET", /\/experiments\/runs\/smoke\/predictions/, preds],
  ];

  it("tells M8 and M8+attr apart in the chart and the heat map, and does not overprint their labels", async () => {
    mockApi(poolRoutes());
    render(<Evaluation />);
    const chart = within(await screen.findByTestId("frontier"));
    expect(chart.getByTestId("pt-M8")).toBeInTheDocument();
    expect(chart.getByTestId("pt-M8+attr")).toBeInTheDocument();
    const ys = ["M8", "M8+attr"].map((k) => Number(within(chart.getByTestId(`pt-${k}`)).getByText(k).getAttribute("y")));
    expect(Math.abs(ys[0] - ys[1])).toBeGreaterThanOrEqual(12);
    const heads = within(screen.getByTestId("heatmap")).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["", "M1", "M8", "M8+attr"]);
  });

  it("does not print 'model: ?' when the run recorded no model", async () => {
    mockApi(poolRoutes());
    render(<Evaluation />);
    await screen.findByTestId("metrics-table");
    expect(screen.queryByText(/model:/)).not.toBeInTheDocument();
    expect(screen.queryByText("?")).not.toBeInTheDocument();
  });

  it("keeps the inspector closed, and fetches nothing, until it is opened", async () => {
    const { calls } = mockApi(poolRoutes());
    render(<Evaluation />);
    await screen.findByTestId("metrics-table");
    expect(screen.queryByTestId("pred-row")).not.toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/predictions"))).toBe(false);
  });

  it("opens on the proposed method's mistakes, and offers more rows a page at a time", async () => {
    const { calls } = mockApi(poolRoutes().map((r) => (r[1].test("/experiments/runs/smoke/predictions") ? [r[0], r[1], (url) => ({ ...preds, total: 80, returned: url.includes("limit=50") ? 50 : 25 })] : r)));
    render(<Evaluation />);
    await userEvent.click(await screen.findByTestId("inspector-toggle"));
    await screen.findAllByTestId("pred-row");
    const first = calls.find((c) => c.url.includes("/predictions")).url;
    expect(first).toContain("method=M8_gated_attr");
    expect(first).toContain("wrong_only=true");
    expect(first).toContain("limit=25");
    await userEvent.click(screen.getByTestId("show-more"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("limit=50"))).toBe(true));
  });

  it("says so, instead of showing an empty table, when no wrong predictions match", async () => {
    mockApi(poolRoutes().map((r) => (r[1].test("/experiments/runs/smoke/predictions") ? [r[0], r[1], { total: 0, returned: 0, rows: [] }] : r)));
    render(<Evaluation />);
    await userEvent.click(await screen.findByTestId("inspector-toggle"));
    expect(await screen.findByTestId("no-pred-rows")).toHaveTextContent("No wrong predictions");
  });

  it("drops the explanation column when no row has an explanation", async () => {
    const bare = { ...preds, rows: preds.rows.map((r) => ({ ...r, explanation: null, policy_reasons: null })) };
    mockApi(routes({ preds: bare }));
    render(<Evaluation />);
    await userEvent.click(await screen.findByTestId("inspector-toggle"));
    await screen.findAllByTestId("pred-row");
    expect(screen.queryByText(/Explanation \/ policy reason/)).not.toBeInTheDocument();
  });
});
