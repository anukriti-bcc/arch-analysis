import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CodeSnippet from "./CodeSnippet.jsx";
import evidenceC from "../__fixtures__/evidence_c.json";

describe("CodeSnippet", () => {
  it("highlights exactly the offending import line from real backend data", () => {
    const { structural } = evidenceC.evidence;
    const { container } = render(<CodeSnippet snippet={structural.code_snippet} highlightLine={structural.line} />);
    const hits = container.querySelectorAll('[data-hit="true"]');
    expect(hits).toHaveLength(1);
    expect(hits[0].textContent).toContain("import");
  });

  it("keeps line numbers and code apart, including blank lines", () => {
    render(<CodeSnippet snippet={"   1: import x\n   2: \n   3: y = 1"} highlightLine={3} />);
    expect(screen.getByText("import x")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("handles a missing snippet", () => {
    render(<CodeSnippet snippet="" />);
    expect(screen.getByText("Source not available.")).toBeInTheDocument();
  });
});
