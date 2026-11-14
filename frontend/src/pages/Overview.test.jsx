import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Overview from "./Overview.jsx";
import { mockApi } from "../test/mockApi.js";
import analysis from "../__fixtures__/analysis_c.json";

afterEach(() => vi.unstubAllGlobals());

describe("Overview", () => {
  it("starts with the bundled demo paths and a hint to run an analysis", () => {
    mockApi([]);
    render(<Overview analysis={null} onAnalyzed={() => {}} />);
    expect(screen.getByLabelText("Repository path")).toHaveValue("../datasets/sample-ecommerce");
    expect(screen.getByLabelText("Architecture file")).toHaveValue("../datasets/sample-ecommerce/architecture/rules.yaml");
    expect(screen.getByText(/No analysis run yet/)).toBeInTheDocument();
  });

  it("sends the entered paths, reports the result upward and shows the stats", async () => {
    const { calls, fn } = mockApi([["POST", /repositories\/analyze/, analysis]]);
    const onAnalyzed = vi.fn();
    render(<Overview analysis={null} onAnalyzed={onAnalyzed} />);
    const repo = screen.getByLabelText("Repository path");
    await userEvent.clear(repo);
    await userEvent.type(repo, "/data/my-repo");
    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await screen.findByText("violations");
    expect(JSON.parse(fn.mock.calls[0][1].body).repository_path).toBe("/data/my-repo");
    expect(calls[0].url).toBe("/api/repositories/analyze");
    expect(onAnalyzed).toHaveBeenCalledWith(expect.objectContaining({ analysis_id: analysis.analysis_id }));
    const violations = analysis.findings.filter((f) => f.status === "violation").length;
    expect(screen.getByText("violations").previousSibling).toHaveTextContent(String(violations));
  });

  it("shows the server's error and lets the user retry", async () => {
    mockApi([["POST", /analyze/, { __status: 400, detail: "Repository path does not exist." }]]);
    render(<Overview analysis={null} onAnalyzed={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText("Repository path does not exist.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });
});
