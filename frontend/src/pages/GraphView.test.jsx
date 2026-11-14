import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import GraphView from "./GraphView.jsx";
import { mockApi } from "../test/mockApi.js";
import graph from "../__fixtures__/graph_c.json";

afterEach(() => vi.unstubAllGlobals());
const A = "A0001";
const load = () => mockApi([["GET", new RegExp(`/analysis/${A}/graph$`), graph]]);
const edgePaths = (c) => [...c.querySelectorAll("svg path[stroke]")];

describe("GraphView", () => {
  it("shows a loading state, then the graph", async () => {
    load();
    render(<GraphView analysisId={A} />);
    expect(screen.getByText("Loading graph…")).toBeInTheDocument();
    expect(await screen.findByText("Dependency graph")).toBeInTheDocument();
  });

  it("draws one edge per dependency, with exactly the violating edges in red", async () => {
    load();
    const { container } = render(<GraphView analysisId={A} />);
    await screen.findByText("Dependency graph");
    const edges = edgePaths(container);
    expect(edges).toHaveLength(graph.edges.length);
    const red = edges.filter((e) => e.getAttribute("stroke") === "#e5472b");
    expect(red).toHaveLength(graph.edges.filter((e) => e.is_violation).length);
    expect(red.length).toBeGreaterThan(0);
  });

  it("lays out components in architectural order, top to bottom", async () => {
    load();
    const { container } = render(<GraphView analysisId={A} />);
    await screen.findByText("Dependency graph");
    const y = (label) => {
      const text = [...container.querySelectorAll("svg text")].find((t) => t.textContent === label);
      return Number(/translate\([\d.]+, ([\d.]+)\)/.exec(text.closest("g").getAttribute("transform"))[1]);
    };
    const rows = ["controller", "service", "repository", "database"].map(y);
    expect(rows).toEqual([...rows].sort((a, b) => a - b));
    expect(new Set(rows).size).toBe(rows.length);
  });

  it("hides files with no dependencies until asked, and says how many", async () => {
    load();
    const { container } = render(<GraphView analysisId={A} />);
    const toggle = await screen.findByRole("checkbox");
    const hidden = Number(/show (\d+) file/.exec(toggle.closest("label").textContent)[1]);
    expect(hidden).toBeGreaterThan(0);
    const before = container.querySelectorAll("svg g[transform]").length;
    await userEvent.click(toggle);
    expect(container.querySelectorAll("svg g[transform]").length).toBe(before + hidden);
  });

  it("shows the details of a clicked edge, flagging violations", async () => {
    load();
    const { container } = render(<GraphView analysisId={A} />);
    await screen.findByText("Dependency graph");
    const red = edgePaths(container).find((e) => e.getAttribute("stroke") === "#e5472b");
    await userEvent.click(red);
    expect(screen.getByText("Violating edge")).toBeInTheDocument();
    const green = edgePaths(container).find((e) => e.getAttribute("stroke") === "#3cae55");
    await userEvent.click(green);
    expect(screen.getByText("Edge")).toBeInTheDocument();
  });

  it("shows server errors", async () => {
    mockApi([["GET", /graph$/, { __status: 404, detail: "Analysis 'A0001' not found." }]]);
    render(<GraphView analysisId={A} />);
    expect(await screen.findByText("Analysis 'A0001' not found.")).toBeInTheDocument();
  });

  it("copes with a graph that has no edges", async () => {
    mockApi([["GET", /graph$/, { nodes: graph.nodes.slice(0, 2), edges: [] }]]);
    render(<GraphView analysisId={A} />);
    expect(await screen.findByText("Dependency graph")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("checkbox")).toBeInTheDocument());
  });

  it("places unknown architectural types after the standard layers", async () => {
    const nodes = [
      { id: "x.py", name: "x.py", architectural_type: "plugin" },
      { id: "c.py", name: "c.py", architectural_type: "controller" },
    ];
    mockApi([["GET", /graph$/, { nodes, edges: [{ source: "c.py", target: "x.py", is_violation: false, source_component: "controller", target_component: "plugin", dependency_type: "import" }] }]]);
    const { container } = render(<GraphView analysisId={A} />);
    await screen.findByText("Dependency graph");
    const ys = ["controller", "plugin"].map((label) => {
      const t = [...container.querySelectorAll("svg text")].find((n) => n.textContent === label);
      return Number(/translate\([\d.]+, ([\d.]+)\)/.exec(t.closest("g").getAttribute("transform"))[1]);
    });
    expect(ys[0]).toBeLessThan(ys[1]);
  });
});
