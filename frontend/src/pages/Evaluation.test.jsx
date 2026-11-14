import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Evaluation from "./Evaluation.jsx";
import { mockApi } from "../test/mockApi.js";
import runs from "../__fixtures__/experiment_runs.json";
import run from "../__fixtures__/experiment_run.json";
import preds from "../__fixtures__/experiment_predictions.json";

afterEach(() => vi.unstubAllGlobals());

function routes(over = {}) {
  return [
    ["GET", /\/experiments\/runs$/, over.runs ?? runs],
    ["GET", /\/experiments\/runs\/smoke$/, over.run ?? run],
    ["GET", /\/experiments\/runs\/smoke\/predictions/, over.preds ?? preds],
  ];
}

describe("Evaluation page", () => {
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
    ["M1 Static rules", "M2 LLM-only", "M3 Full hybrid", "M5 Evidence-guided (proposed)", "A1 No evolution evidence"].forEach((t) =>
      expect(table.getByText(t)).toBeInTheDocument()
    );
    expect(table.getByText("M5 Evidence-guided (proposed)").closest("tr")).toHaveClass("highlight");
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
    const rows = await screen.findAllByTestId("pred-row");
    expect(rows.length).toBe(preds.rows.length);
    const wrongExpected = preds.rows.filter((r) => Boolean(r.predicted_violation) !== (r.truth === "violation")).length;
    expect(rows.filter((r) => r.classList.contains("wrong")).length).toBe(wrongExpected);
  });

  it("re-queries the server when a filter changes", async () => {
    const { calls } = mockApi(routes());
    render(<Evaluation />);
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

  it("reads a clearly positive interval as M5 higher and an interval spanning zero as not distinguishable", async () => {
    mockApi(routes({ run: withPaired([
      row({}),
      row({ b: "A1_no_history", delta: 0.01, ci_low: -0.05, ci_high: 0.07 }),
      row({ b: "M3_full_hybrid", metric: "llm_calls", a_value: 12, b_value: 28, delta: -16, ci_low: -22, ci_high: -9 }),
    ]) }));
    render(<Evaluation />);
    const table = within(await screen.findByTestId("paired"));
    const rows = table.getAllByTestId("paired-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("M5 higher");
    expect(rows[1]).toHaveTextContent("not distinguishable");
    expect(rows[2]).toHaveTextContent("M5 lower");           // fewer calls is a negative difference
    expect(rows[2]).toHaveTextContent("LLM calls");
    expect(rows[2]).toHaveTextContent("-16 (-22 to -9)");   // calls shown as whole numbers
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
    expect(table.getByText("M5 Evidence-guided (proposed): LLM calls per case").closest("tr")).toHaveTextContent("0.10");
  });

  it("renders from real exported fixtures too", async () => {
    mockApi(routes());
    render(<Evaluation />);
    expect(await screen.findByTestId("paired")).toBeInTheDocument();
    expect(screen.getByTestId("density")).toBeInTheDocument();
  });
});
