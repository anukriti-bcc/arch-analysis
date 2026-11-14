import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";
import { mockApi } from "./test/mockApi.js";

afterEach(() => vi.unstubAllGlobals());

describe("App navigation", () => {
  it("keeps analysis-dependent views disabled until an analysis exists, but not Evaluation", () => {
    mockApi([]);
    render(<App />);
    expect(screen.getByRole("button", { name: /Graph/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Findings/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Evaluation/ })).toBeEnabled();
  });

  it("opens the Evaluation view without running an analysis", async () => {
    mockApi([["GET", /runs$/, []]]);
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: /Evaluation/ }));
    expect(await screen.findByTestId("no-runs")).toBeInTheDocument();
  });
});

import analysis from "./__fixtures__/analysis_c.json";
import graph from "./__fixtures__/graph_c.json";
import finding from "./__fixtures__/finding_c.json";
import evidence from "./__fixtures__/evidence_c.json";
import semantic from "./__fixtures__/semantic_c.json";
import triage from "./__fixtures__/triage_c.json";

describe("App — full user journey", () => {
  it("analyze -> graph -> findings -> open violation -> run evidence-guided analysis", async () => {
    const A = analysis.analysis_id;
    const { calls } = mockApi([
      ["POST", /repositories\/analyze/, analysis],
      ["GET", new RegExp(`/analysis/${A}/graph$`), graph],
      ["GET", new RegExp(`/analysis/${A}/findings$`), analysis.findings],
      ["GET", new RegExp(`/analysis/${A}/triage$`), triage],
      ["GET", new RegExp(`/analysis/${A}/findings/${finding.id}$`), finding],
      ["GET", /\/evidence/, evidence],
      ["POST", /semantic-analysis/, semantic],
    ]);
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    // a successful analysis lands on the Graph view automatically
    expect(await screen.findByText("Dependency graph")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Findings/ })).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: /Findings/ }));
    await userEvent.click(await screen.findByTestId(`row-${finding.id}`));
    await userEvent.click(await screen.findByRole("button", { name: "Run evidence-guided analysis" }));
    expect(await screen.findByTestId("final-pill")).toHaveTextContent("final: justified");
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url.split("?")[0])).toEqual([
      "/api/repositories/analyze",
      `/api/findings/${finding.id}/semantic-analysis`,
    ]);
  });

  it("toggles the theme and persists the choice", async () => {
    mockApi([]);
    render(<App />);
    const toggle = screen.getByRole("button", { name: /theme|light|dark/i });
    const before = document.documentElement.getAttribute("data-theme");
    await userEvent.click(toggle);
    expect(document.documentElement.getAttribute("data-theme")).not.toBe(before);
    expect(localStorage.getItem("theme")).toBeTruthy();
  });
});
