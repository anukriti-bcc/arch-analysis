import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import DecisionPanel from "./DecisionPanel.jsx";
import evidenceA from "../__fixtures__/evidence_a.json";
import evidenceC from "../__fixtures__/evidence_c.json";
import semanticA from "../__fixtures__/semantic_a.json";
import semanticC from "../__fixtures__/semantic_c.json";

const base = { running: false, error: null, onRun: () => {} };

describe("DecisionPanel — before running", () => {
  it("says the evidence is sufficient when the policy would not escalate", () => {
    render(<DecisionPanel {...base} policy={evidenceA.policy} />);
    expect(screen.getByTestId("verdict-banner")).toHaveTextContent("Evidence is sufficient — no LLM needed");
    expect(screen.getByTestId("policy-reasons")).toHaveTextContent("no relevant active intent");
  });

  it("recommends semantic review and shows the policy's reasons when it would escalate", () => {
    render(<DecisionPanel {...base} policy={evidenceC.policy} />);
    expect(screen.getByTestId("verdict-banner")).toHaveTextContent("semantic review recommended");
    expect(screen.getByTestId("policy-reasons")).toHaveTextContent("I1");
  });

  it("offers both a policy-respecting run and a forced LLM review", async () => {
    const onRun = vi.fn();
    render(<DecisionPanel {...base} policy={evidenceC.policy} onRun={onRun} />);
    await userEvent.click(screen.getByRole("button", { name: "Run evidence-guided analysis" }));
    await userEvent.click(screen.getByRole("button", { name: "Force LLM review" }));
    expect(onRun.mock.calls).toEqual([[false], [true]]);
  });

  it("disables both buttons while running", () => {
    render(<DecisionPanel {...base} policy={evidenceC.policy} running />);
    expect(screen.getByRole("button", { name: "Analyzing…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Force LLM review" })).toBeDisabled();
  });
});

describe("DecisionPanel — after running", () => {
  it("shows an LLM-justified outcome with the model's explanation and cost", () => {
    render(<DecisionPanel {...base} policy={evidenceC.policy} decision={semanticC.decision} semantic={semanticC.semantic_analysis} />);
    expect(screen.getByTestId("verdict-banner")).toHaveTextContent("Justified by documented intent");
    expect(screen.getByTestId("decision-how")).toHaveTextContent("Resolved by extraction and computation");
    expect(screen.getByTestId("semantic-explanation")).toHaveTextContent(semanticC.semantic_analysis.explanation);
    expect(screen.getByTestId("semantic-meta")).toHaveTextContent("stub-model");
    expect(screen.getByRole("button", { name: "Run again" })).toBeInTheDocument();
  });

  it("shows a direct verdict with no LLM result block", () => {
    render(<DecisionPanel {...base} policy={evidenceA.policy} decision={semanticA.decision} semantic={null} />);
    expect(screen.getByTestId("verdict-banner")).toHaveTextContent("Confirmed violation");
    expect(screen.getByTestId("decision-how")).toHaveTextContent("No LLM call was made");
    expect(screen.queryByTestId("semantic-result")).not.toBeInTheDocument();
  });

  it("is honest when an LLM call produced nothing usable", () => {
    const decision = { ...semanticC.decision, final_verdict: "violation", outcome_source: "fallback" };
    const semantic = { ...semanticC.semantic_analysis, parsed_ok: false, verdict: null, confidence: null, error: "unparseable model output" };
    render(<DecisionPanel {...base} policy={evidenceC.policy} decision={decision} semantic={semantic} />);
    expect(screen.getByTestId("decision-how")).toHaveTextContent("structural verdict was kept");
    expect(screen.getByText("no usable output")).toBeInTheDocument();
    expect(screen.getByText("unparseable model output")).toBeInTheDocument();
  });

  it("says when a review was forced against the policy", () => {
    const decision = { ...semanticA.decision, llm_called: true, forced: true, outcome_source: "llm" };
    render(<DecisionPanel {...base} policy={evidenceA.policy} decision={decision} semantic={null} />);
    expect(screen.getByTestId("decision-how")).toHaveTextContent("forced");
  });

  it("displays a configuration error (e.g. no LLM set up) clearly", () => {
    render(<DecisionPanel {...base} policy={evidenceC.policy} error="no LLM is configured. Set LLM_BASE_URL" />);
    expect(screen.getByTestId("decision-error")).toHaveTextContent("LLM_BASE_URL");
  });

  it("flags estimated token counts and cache hits", () => {
    const semantic = { ...semanticC.semantic_analysis, cached: true, tokens_estimated: true };
    render(<DecisionPanel {...base} policy={evidenceC.policy} decision={semanticC.decision} semantic={semantic} />);
    expect(screen.getByTestId("semantic-meta")).toHaveTextContent("cached");
    expect(screen.getByTestId("semantic-meta")).toHaveTextContent("token counts estimated");
  });
});

describe("DecisionPanel — extract-then-compute (method M7)", () => {
  const extract = {
    mode: "extract_compute", parsed_ok: true, verdict: "violation", confidence: null, evidence_used: [], error: null,
    explanation: "The ADR permits direct access for code introduced on or before the freeze.",
    extraction: { adr_id: "ADR-014", decision: "permits", covers_this_dependency: "yes", limit: "introduced_on_or_before", limit_date: "2025-07-14", grounding: "accepted" },
    computed: "introduced 2025-08-13 does not satisfy 'introduced_on_or_before 2025-07-14'",
    model: "stub-model", tokens_used: { input: 900, output: 60 }, latency_s: 1.2, cached: false, tokens_estimated: false,
  };
  const decision = { ...semanticC.decision, final_verdict: "violation", outcome_source: "llm_extract", resolution: "extract_compute" };

  it("shows what the model extracted and what code computed from it", () => {
    render(<DecisionPanel {...base} policy={evidenceC.policy} decision={decision} semantic={extract} />);
    expect(screen.getByText("Verdict computed from extracted facts")).toBeInTheDocument();
    expect(screen.getByTestId("extracted-facts")).toHaveTextContent("permits");
    expect(screen.getByTestId("extracted-facts")).toHaveTextContent("introduced on or before 2025-07-14");
    expect(screen.getByTestId("computed-verdict")).toHaveTextContent("does not satisfy");
    expect(screen.getByTestId("grounding")).toHaveTextContent("accepted");
    expect(screen.getByTestId("verdict-banner")).toHaveTextContent("Confirmed violation");
  });

  it("shows no date limit plainly and hides the grounding line when there is no limit", () => {
    const sem = { ...extract, verdict: "justified", computed: "permits this module, no date limit",
                  extraction: { ...extract.extraction, limit: "none", limit_date: null, grounding: "no limit claimed" } };
    render(<DecisionPanel {...base} policy={evidenceC.policy} decision={{ ...decision, final_verdict: "justified" }} semantic={sem} />);
    expect(screen.getByTestId("extracted-facts")).toHaveTextContent("no date limit");
    expect(screen.queryByTestId("grounding")).not.toBeInTheDocument();
  });

  it("labels an unresolved extraction honestly", () => {
    const sem = { ...extract, verdict: null, computed: "limit stated but the introduction date is unknown" };
    render(<DecisionPanel {...base} policy={evidenceC.policy} decision={{ ...decision, outcome_source: "fallback" }} semantic={sem} />);
    expect(screen.getByText("unresolved")).toBeInTheDocument();
    expect(screen.getByTestId("decision-how")).toHaveTextContent("gave no usable verdict");
  });

  it("keeps the ordinary review wording for history-only escalations", () => {
    const review = { ...semanticC.decision, resolution: "review", outcome_source: "llm" };
    const reviewResult = { ...semanticC.semantic_analysis, mode: "review", extraction: undefined, computed: undefined };
    render(<DecisionPanel {...base} policy={evidenceC.policy} decision={review} semantic={reviewResult} />);
    expect(screen.getByTestId("decision-how")).toHaveTextContent("Resolved by LLM semantic review");
    expect(screen.queryByTestId("extracted-facts")).not.toBeInTheDocument();
  });
});

