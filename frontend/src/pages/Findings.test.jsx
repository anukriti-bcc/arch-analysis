import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Findings from "./Findings.jsx";
import { mockApi } from "../test/mockApi.js";
import analysis from "../__fixtures__/analysis_c.json";
import finding from "../__fixtures__/finding_c.json";
import evidence from "../__fixtures__/evidence_c.json";
import semantic from "../__fixtures__/semantic_c.json";
import triage from "../__fixtures__/triage_c.json";

const A = analysis.analysis_id;
const FID = finding.id;

function routes(overrides = {}) {
  return [
    ["GET", new RegExp(`/analysis/${A}/findings$`), analysis.findings],
    ["GET", new RegExp(`/analysis/${A}/triage$`), overrides.triage ?? triage],
    ["GET", new RegExp(`/analysis/${A}/findings/${FID}$`), overrides.finding ?? finding],
    ["GET", new RegExp(`/findings/${FID}/evidence`), overrides.evidence ?? evidence],
    ["POST", new RegExp(`/findings/${FID}/semantic-analysis`), overrides.semantic ?? semantic],
    ["POST", new RegExp(`/findings/${FID}/recommendation`), overrides.recommendation ?? {
      source: "rules", disclaimer: "Suggestion only. Review before applying; nothing here has been changed in your code.",
      summary: "Rule R004 is broken.", recommended_option: "document_exception", warnings: [], note: null, ai: null, model: null,
      options: [{ id: "document_exception", title: "Keep it and document it as a deliberate exception", effort: "low", why: "Record why.", steps: ["Write an ADR."] }],
    }],
  ];
}

afterEach(() => vi.unstubAllGlobals());

describe("Findings list", () => {
  it("shows the triage summary and a per-row triage pill", async () => {
    mockApi(routes());
    render(<Findings analysisId={A} />);
    const summary = await screen.findByTestId("triage-summary");
    expect(within(summary).getByText("need semantic review").previousSibling).toHaveTextContent("1");
    const row = screen.getByTestId(`row-${FID}`);
    expect(within(row).getByText("needs review")).toBeInTheDocument();
    expect(within(row).getByText("violation")).toBeInTheDocument();
  });

  it("lists conformant rows without a triage pill", async () => {
    mockApi(routes());
    render(<Findings analysisId={A} />);
    await screen.findByTestId("triage-summary");
    const conformantRows = screen.getAllByText("conformant").map((el) => el.closest("tr"));
    expect(conformantRows.length).toBeGreaterThan(0);
    conformantRows.forEach((r) => expect(within(r).queryByText("needs review")).not.toBeInTheDocument());
  });

  it("still shows the findings table when triage fails", async () => {
    mockApi([...routes().filter((r) => !String(r[1]).includes("triage")), ["GET", /triage/, { __status: 500, detail: "boom" }]]);
    render(<Findings analysisId={A} />);
    expect(await screen.findByTestId("triage-error")).toHaveTextContent("boom");
    expect(screen.getByTestId(`row-${FID}`)).toBeInTheDocument();
  });

  it("shows an error when findings cannot be loaded", async () => {
    mockApi([["GET", /findings$/, { __status: 404, detail: "Analysis not found." }], ["GET", /triage/, triage]]);
    render(<Findings analysisId={A} />);
    expect(await screen.findByText("Analysis not found.")).toBeInTheDocument();
  });
});

describe("Finding detail", () => {
  async function open() {
    const api = mockApi(routes());
    render(<Findings analysisId={A} />);
    await userEvent.click(await screen.findByTestId(`row-${FID}`));
    await screen.findByTestId("decision-panel");
    return api;
  }

  it("loads the finding scoped to its analysis run and shows all evidence sections", async () => {
    const { calls } = await open();
    expect(calls.some((c) => c.url === `/api/analysis/${A}/findings/${FID}`)).toBe(true);
    expect(calls.some((c) => c.url === `/api/findings/${FID}/evidence?analysis_id=${A}`)).toBe(true);
    ["Structural evidence", "Architectural intent", "Evolution evidence", "Decision"].forEach((t) =>
      expect(screen.getByText(t, { exact: false, selector: "h4" })).toBeInTheDocument()
    );
    expect(screen.getByTestId("code-snippet").querySelector('[data-hit="true"]')).not.toBeNull();
    expect(screen.getByTestId("adr-list")).toBeInTheDocument();
    expect(screen.getByTestId("timeline")).toBeInTheDocument();
    expect(screen.getByTestId("verdict-banner")).toHaveTextContent("semantic review recommended");
  });

  it("runs the analysis and then shows the final verdict, explanation and cost", async () => {
    const { calls } = await open();
    await userEvent.click(screen.getByRole("button", { name: "Run evidence-guided analysis" }));
    await screen.findByTestId("semantic-result");
    const post = calls.find((c) => c.method === "POST");
    expect(post.url).toBe(`/api/findings/${FID}/semantic-analysis?analysis_id=${A}`);
    expect(screen.getByTestId("final-pill")).toHaveTextContent("final: justified");
    expect(screen.getByTestId("semantic-explanation")).toHaveTextContent(semantic.semantic_analysis.explanation);
    expect(screen.getByTestId("verdict-banner")).toHaveTextContent("Justified by documented intent");
  });

  it("suggests a fix on request, scoped to its analysis run, and labels it as a suggestion", async () => {
    const { calls } = await open();
    expect(screen.getByText("Suggested fix", { exact: false, selector: "h4" })).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/recommendation"))).toBe(false); // nothing is requested until the user asks
    await userEvent.click(screen.getByTestId("suggest-fix"));
    await screen.findByTestId("recommendation-banner");
    expect(calls.find((c) => c.url.includes("/recommendation")).url).toBe(`/api/findings/${FID}/recommendation?analysis_id=${A}`);
    expect(screen.getByTestId("recommendation-banner")).toHaveTextContent("Review before applying");
    expect(screen.getByTestId("option-document_exception")).toBeInTheDocument();
  });

  it("passes force=true for the forced review", async () => {
    const { calls } = await open();
    await userEvent.click(screen.getByRole("button", { name: "Force LLM review" }));
    await screen.findByTestId("semantic-result");
    expect(calls.find((c) => c.method === "POST").url).toContain("force=true");
  });

  it("tells the user how to configure an LLM when none is set up", async () => {
    mockApi(routes({ semantic: { __status: 503, detail: "no LLM is configured. Set LLM_BASE_URL and LLM_MODEL" } }));
    render(<Findings analysisId={A} />);
    await userEvent.click(await screen.findByTestId(`row-${FID}`));
    await screen.findByTestId("decision-panel");
    await userEvent.click(screen.getByRole("button", { name: "Run evidence-guided analysis" }));
    expect(await screen.findByTestId("decision-error")).toHaveTextContent("LLM_BASE_URL");
    expect(screen.queryByTestId("final-pill")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run evidence-guided analysis" })).toBeEnabled();
  });

  it("restores a previously stored decision when the finding is reopened", async () => {
    mockApi(routes({ finding: { ...finding, decision: semantic.decision, semantic_analysis: semantic.semantic_analysis } }));
    render(<Findings analysisId={A} />);
    await userEvent.click(await screen.findByTestId(`row-${FID}`));
    expect(await screen.findByTestId("final-pill")).toHaveTextContent("final: justified");
    expect(screen.getByTestId("semantic-result")).toBeInTheDocument();
  });

  it("does not load evidence or offer analysis for a conformant dependency", async () => {
    const conformant = { ...finding, id: "F001", status: "conformant" };
    const rows = [{ ...analysis.findings[0], id: "F001", status: "conformant" }];
    const { calls } = mockApi([
      ["GET", new RegExp(`/analysis/${A}/findings$`), rows],
      ["GET", /triage/, { summary: { violations: 0, resolved_directly: 0, needs_semantic_review: 0 }, items: [] }],
      ["GET", /findings\/F001$/, conformant],
    ]);
    render(<Findings analysisId={A} />);
    await userEvent.click(await screen.findByTestId("row-F001"));
    expect(await screen.findByText(/conforms to its rule/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/evidence"))).toBe(false);
    expect(screen.queryByTestId("decision-panel")).not.toBeInTheDocument();
  });

  it("shows evidence errors without hiding the finding, and can go back to the list", async () => {
    mockApi(routes({ evidence: { __status: 500, detail: "git exploded" } }));
    render(<Findings analysisId={A} />);
    await userEvent.click(await screen.findByTestId(`row-${FID}`));
    expect(await screen.findByText("git exploded")).toBeInTheDocument();
    await userEvent.click(screen.getByText("← back to findings"));
    await waitFor(() => expect(screen.getByTestId("triage-summary")).toBeInTheDocument());
  });

  it("keeps the raw JSON available for transparency", async () => {
    await open();
    await userEvent.click(screen.getByText("Raw finding (JSON)"));
    expect(screen.getByText(new RegExp(`"id": "${FID}"`))).toBeInTheDocument();
  });
});
