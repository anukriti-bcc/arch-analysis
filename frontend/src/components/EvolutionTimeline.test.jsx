import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EvolutionTimeline from "./EvolutionTimeline.jsx";
import evidenceC from "../__fixtures__/evidence_c.json";

const evo = evidenceC.evidence.evolution;

describe("EvolutionTimeline", () => {
  it("shows the introducing commit, age and snapshot for real backend data", () => {
    render(<EvolutionTimeline evolution={evo} />);
    expect(screen.getByTestId("timeline")).toBeInTheDocument();
    expect(screen.getByText(/Introduced/, { selector: ".timeline-label strong" })).toBeInTheDocument();
    expect(screen.getByText(/Snapshot \(HEAD\)/)).toBeInTheDocument();
    expect(screen.getByText(`${evo.age_days} days`)).toBeInTheDocument();
    expect(screen.getByTestId("commit-message")).toHaveTextContent(evo.introducing_commit.subject);
    expect(screen.getByText(evo.introducing_commit.sha.slice(0, 8))).toBeInTheDocument();
  });

  it("explains the commit counts", () => {
    render(<EvolutionTimeline evolution={evo} />);
    expect(screen.getByText(new RegExp(`${evo.commits_since_introduction} \\(${evo.relevant_commits_since_introduction} touching`))).toBeInTheDocument();
  });

  it("shows no signal chips when the commit message has none", () => {
    render(<EvolutionTimeline evolution={evo} />);
    expect(screen.queryByTestId("signals")).not.toBeInTheDocument();
  });

  it("shows temporary-language, ADR and issue signals when present", () => {
    const e = { ...evo, message_signals: { temporary_language: ["temp", "workaround"], migration_language: ["legacy"], adr_references: ["ADR-009"], issue_references: ["#142"] } };
    render(<EvolutionTimeline evolution={e} />);
    const signals = within(screen.getByTestId("signals"));
    ["“temp”", "“workaround”", "“legacy”", "ADR-009", "#142"].forEach((t) => expect(signals.getByText(t)).toBeInTheDocument());
  });

  it("explains when no Git history is available", () => {
    render(<EvolutionTimeline evolution={{ available: false, reason: "not a git repository" }} />);
    expect(screen.getByTestId("evolution-unavailable")).toHaveTextContent("not a git repository");
  });

  it("explains when the dependency is not in committed history", () => {
    render(<EvolutionTimeline evolution={{ available: true, introducing_commit: null }} />);
    expect(screen.getByTestId("evolution-absent")).toBeInTheDocument();
  });

  it("handles missing evidence", () => {
    render(<EvolutionTimeline evolution={null} />);
    expect(screen.getByText("History evidence not loaded.")).toBeInTheDocument();
  });

  it("warns about renames and truncated history", () => {
    render(<EvolutionTimeline evolution={{ ...evo, rename_history_detected: true, history_truncated: true }} />);
    expect(screen.getByTestId("rename-warning")).toBeInTheDocument();
    expect(screen.getByText(/Only the most recent commits were examined/)).toBeInTheDocument();
  });

  it("labels a removed-then-reintroduced history", () => {
    const e = {
      ...evo, reintroduced: true,
      timeline: [
        { change: "introduced", date: "2026-01-01T00:00:00+00:00", short: "a", subject: "x", author: "a" },
        { change: "removed", date: "2026-02-01T00:00:00+00:00", short: "b", subject: "y", author: "a" },
        { change: "reintroduced", date: "2026-03-01T00:00:00+00:00", short: "c", subject: "z", author: "a" },
      ],
    };
    render(<EvolutionTimeline evolution={e} />);
    ["Introduced", "Removed", "Reintroduced"].forEach((t) => expect(screen.getByText(t, { selector: "strong" })).toBeInTheDocument());
  });
});
