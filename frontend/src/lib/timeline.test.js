import { describe, expect, it } from "vitest";
import { daysBetween, layoutTimeline } from "./timeline.js";

const ev = (change, date) => ({ change, date, short: "abc", subject: "s", author: "a" });

describe("layoutTimeline", () => {
  it("returns nothing for no events and no snapshot", () => {
    expect(layoutTimeline([], null)).toEqual([]);
    expect(layoutTimeline(undefined, undefined)).toEqual([]);
  });

  it("places a lone event in the middle", () => {
    const [n] = layoutTimeline([ev("introduced", "2026-01-01T00:00:00Z")], null);
    expect(n.x).toBe(50);
  });

  it("orders events by date and puts the snapshot last", () => {
    const nodes = layoutTimeline(
      [ev("removed", "2026-03-01T00:00:00Z"), ev("introduced", "2026-01-01T00:00:00Z")],
      "2026-05-01T00:00:00Z"
    );
    expect(nodes.map((n) => n.kind)).toEqual(["introduced", "removed", "snapshot"]);
    expect(nodes[0].x).toBeLessThan(nodes[1].x);
    expect(nodes[1].x).toBeLessThan(nodes[2].x);
  });

  it("spaces nodes in proportion to elapsed time", () => {
    const nodes = layoutTimeline([ev("introduced", "2026-01-01T00:00:00Z")], "2026-01-11T00:00:00Z");
    expect(nodes[0].x).toBeCloseTo(7, 0);
    expect(nodes[1].x).toBeCloseTo(93, 0);
  });

  it("keeps a minimum gap so labels cannot collide, and stays inside the track", () => {
    const nodes = layoutTimeline(
      [ev("introduced", "2026-01-01T00:00:00Z"), ev("removed", "2026-01-02T00:00:00Z"), ev("reintroduced", "2026-01-03T00:00:00Z")],
      "2026-12-31T00:00:00Z"
    );
    for (let i = 1; i < nodes.length; i++) expect(nodes[i].x - nodes[i - 1].x).toBeGreaterThanOrEqual(7);
    expect(Math.min(...nodes.map((n) => n.x))).toBeGreaterThanOrEqual(0);
    expect(Math.max(...nodes.map((n) => n.x))).toBeLessThanOrEqual(100);
  });

  it("spreads same-day events evenly instead of stacking them", () => {
    const nodes = layoutTimeline([ev("introduced", "2026-01-01T00:00:00Z")], "2026-01-01T00:00:00Z");
    expect(nodes[0].x).not.toBe(nodes[1].x);
  });

  it("alternates label rows above and below", () => {
    const nodes = layoutTimeline([ev("introduced", "2026-01-01T00:00:00Z"), ev("removed", "2026-02-01T00:00:00Z")], "2026-03-01T00:00:00Z");
    expect(nodes.map((n) => n.row)).toEqual(["above", "below", "above"]);
  });

  it("ignores events with missing or invalid dates", () => {
    const nodes = layoutTimeline([{ change: "introduced", date: "not a date" }, { change: "removed" }], "2026-01-01T00:00:00Z");
    expect(nodes.map((n) => n.kind)).toEqual(["snapshot"]);
  });
});

describe("daysBetween", () => {
  it("counts whole days", () => {
    expect(daysBetween("2026-02-01T12:00:00Z", "2026-05-02T12:00:00Z")).toBe(90);
  });
});
