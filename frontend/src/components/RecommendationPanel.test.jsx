import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RecommendationPanel from "./RecommendationPanel.jsx";

const options = [
  { id: "route_via_repository", title: "Route the call through the repository layer", effort: "medium", why: "The architecture allows it.", steps: ["Add a repository method.", "Call it."] },
  { id: "document_exception", title: "Keep it and document it as a deliberate exception", effort: "low", why: "Record why.", steps: ["Write an ADR."], adr_draft: "# ADR-<number>: Allow `a` to use `b` directly" },
];
const base = { disclaimer: "Suggestion only. Review before applying; nothing here has been changed in your code.", summary: "Rule R004 is broken.", options, recommended_option: "route_via_repository", warnings: [], note: null, ai: null, model: null };

describe("RecommendationPanel", () => {
  it("offers a button first and calls onRun", async () => {
    const onRun = vi.fn();
    render(<RecommendationPanel rec={null} loading={false} error={null} onRun={onRun} />);
    await userEvent.click(screen.getByTestId("suggest-fix"));
    expect(onRun).toHaveBeenCalledWith(false);
  });

  it("labels rule-based advice as such and shows options, the recommended one, and the ADR draft", () => {
    render(<RecommendationPanel rec={{ ...base, source: "rules", note: "No language model is configured, so only rule-derived options are shown." }} onRun={() => {}} />);
    expect(screen.getByTestId("recommendation-banner")).toHaveTextContent("Rule-based suggestion (no AI model used)");
    expect(screen.getByTestId("recommendation-banner")).toHaveTextContent("Review before applying");
    expect(screen.getByTestId("option-route_via_repository")).toHaveTextContent("recommended");
    expect(screen.getByTestId("option-document_exception")).not.toHaveTextContent("recommended");
    expect(screen.getByTestId("adr-draft")).toHaveTextContent("ADR-<number>");
    expect(screen.queryByTestId("ai-steps")).toBeNull();
    expect(screen.getByTestId("recommendation-note")).toHaveTextContent("No language model");
  });

  it("labels AI advice as AI-generated, shows its steps, the model, and any warning about unknown files", () => {
    const rec = { ...base, source: "ai", model: "qwen2.5:3b-instruct", ai: { summary: "s", steps: ["Add a method to order_repository.", "Remove the import."], risks: ["Query may differ."], recommended_option: "route_via_repository" },
      warnings: ["The AI mentioned file(s) not found in this repository: ghost.py. Check them before following the steps."] };
    render(<RecommendationPanel rec={rec} onRun={() => {}} />);
    expect(screen.getByTestId("recommendation-banner")).toHaveTextContent("AI-generated suggestion — review before applying");
    expect(screen.getByTestId("ai-steps")).toHaveTextContent("qwen2.5:3b-instruct");
    expect(screen.getByTestId("ai-steps")).toHaveTextContent("Add a method to order_repository.");
    expect(screen.getByTestId("ai-steps")).toHaveTextContent("Query may differ.");
    expect(screen.getByTestId("recommendation-warning")).toHaveTextContent("ghost.py");
  });

  it("regenerate asks for a refresh, and an error is shown", async () => {
    const onRun = vi.fn();
    const { rerender } = render(<RecommendationPanel rec={{ ...base, source: "rules" }} onRun={onRun} />);
    await userEvent.click(screen.getByTestId("regenerate-fix"));
    expect(onRun).toHaveBeenCalledWith(true);
    rerender(<RecommendationPanel rec={null} error="Request failed (500)" onRun={onRun} />);
    expect(screen.getByTestId("recommendation-error")).toHaveTextContent("Request failed (500)");
  });

  it("shows no options for a finding that needs no fix", () => {
    render(<RecommendationPanel rec={{ ...base, source: "rules", options: [], recommended_option: null, summary: "The evidence indicates this dependency is an intentional, documented exception, so no fix is recommended." }} onRun={() => {}} />);
    expect(screen.getByTestId("recommendation-summary")).toHaveTextContent("no fix is recommended");
    expect(screen.queryByTestId("option-route_via_repository")).toBeNull();
  });
});
