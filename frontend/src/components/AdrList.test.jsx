import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import AdrList from "./AdrList.jsx";
import evidenceC from "../__fixtures__/evidence_c.json";
import evidenceF from "../__fixtures__/evidence_f.json";

describe("AdrList", () => {
  it("shows an empty state when nothing is relevant", () => {
    render(<AdrList adrs={[]} />);
    expect(screen.getByTestId("adr-empty")).toBeInTheDocument();
    render(<AdrList adrs={undefined} />);
  });

  it("lists real ADRs with status and the reasons they were selected", () => {
    const adr = evidenceC.evidence.adrs[0];
    render(<AdrList adrs={evidenceC.evidence.adrs} />);
    const card = within(screen.getByTestId(`adr-${adr.id}`));
    expect(card.getByText(adr.title)).toBeInTheDocument();
    expect(card.getByText("accepted")).toBeInTheDocument();
    expect(card.getByText("names both files")).toBeInTheDocument();
  });

  it("marks a superseded record as inactive", () => {
    render(<AdrList adrs={evidenceF.evidence.adrs} />);
    expect(screen.getByText(/inactive · superseded/)).toBeInTheDocument();
  });

  it("reveals the full record text on demand", async () => {
    const adr = evidenceC.evidence.adrs[0];
    render(<AdrList adrs={evidenceC.evidence.adrs} />);
    await userEvent.click(screen.getByText("Read the record"));
    expect(screen.getByText(/grandfathered/i, { selector: "pre" })).toBeInTheDocument();
    expect(adr.text).toContain("grandfathered");
  });

  it("explains commit-cited records", () => {
    const adrs = [{ id: "ADR-009", title: "t", status: "accepted", path: "p", match_reasons: ["commit_reference"] }];
    render(<AdrList adrs={adrs} />);
    expect(screen.getByText("cited by the introducing commit")).toBeInTheDocument();
  });
});
