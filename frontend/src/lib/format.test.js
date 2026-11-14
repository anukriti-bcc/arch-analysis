import { describe, expect, it } from "vitest";
import { formatDate, formatFixed, formatInt, isActiveAdrStatus, methodLabel, methodShort, plural, shortSha } from "./format.js";

describe("format helpers", () => {
  it("formats dates in UTC regardless of time zone", () => {
    expect(formatDate("2025-07-14T23:59:00+00:00")).toBe("14 Jul 2025");
    expect(formatDate(null)).toBe("—");
    expect(formatDate("garbage")).toBe("garbage");
  });
  it("formats numbers and treats missing values as a dash", () => {
    expect(formatFixed(0.81234)).toBe("0.812");
    expect(formatFixed(null)).toBe("—");
    expect(formatFixed(NaN)).toBe("—");
    expect(formatInt(12345.4)).toBe("12,345");
    expect(formatInt(undefined)).toBe("—");
  });
  it("pluralises", () => {
    expect(plural(1, "day")).toBe("1 day");
    expect(plural(2, "day")).toBe("2 days");
    expect(plural(0, "violation")).toBe("0 violations");
  });
  it("shortens shas", () => {
    expect(shortSha("0123456789abcdef")).toBe("01234567");
    expect(shortSha(undefined)).toBe("");
  });
  it("treats only superseded/deprecated/rejected as inactive", () => {
    ["superseded", "deprecated", "rejected", "Superseded"].forEach((s) => expect(isActiveAdrStatus(s)).toBe(false));
    ["accepted", "proposed", "unknown", "", undefined].forEach((s) => expect(isActiveAdrStatus(s)).toBe(true));
  });
  it("labels methods, including seeded M4 runs", () => {
    expect(methodLabel("M5_evidence_guided")).toContain("proposed");
    expect(methodLabel("M4_generic_selective_s3")).toBe("M4 Generic selective (seed 3)");
    expect(methodLabel("A2_no_intent")).toBe("A2 No intent evidence");
    expect(methodLabel("custom")).toBe("custom");
    expect(methodShort("M3_full_hybrid")).toBe("M3");
  });
});
