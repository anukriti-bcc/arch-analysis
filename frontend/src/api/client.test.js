import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getExperimentPredictions, getFinding, getFindingEvidence, getTriage, requestSemanticAnalysis,
} from "./client.js";
import { mockApi } from "../test/mockApi.js";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("scopes finding lookups to the analysis run when given one", async () => {
    const { calls } = mockApi([["GET", /.*/, {}]]);
    await getFinding("F001", "A0007");
    await getFinding("F001");
    expect(calls.map((c) => c.url)).toEqual(["/api/analysis/A0007/findings/F001", "/api/findings/F001"]);
  });

  it("passes analysis_id and force as query params, omitting false/empty ones", async () => {
    const { calls } = mockApi([["POST", /.*/, {}], ["GET", /.*/, {}]]);
    await requestSemanticAnalysis("F002", "A1", false);
    await requestSemanticAnalysis("F002", "A1", true);
    await getFindingEvidence("F002", "A1");
    expect(calls[0].url).toBe("/api/findings/F002/semantic-analysis?analysis_id=A1");
    expect(calls[1].url).toBe("/api/findings/F002/semantic-analysis?analysis_id=A1&force=true");
    expect(calls[2].url).toBe("/api/findings/F002/evidence?analysis_id=A1");
    expect(calls[0].method).toBe("POST");
  });

  it("builds prediction filters and skips unset ones", async () => {
    const { calls } = mockApi([["GET", /.*/, {}]]);
    await getExperimentPredictions("run 1", { method: "M5", scenario: "", wrong_only: true, llm_only: false, limit: 50 });
    expect(calls[0].url).toBe("/api/experiments/runs/run%201/predictions?method=M5&wrong_only=true&limit=50");
  });

  it("surfaces the server's detail message as the error", async () => {
    mockApi([["GET", /triage/, { __status: 404, detail: "Analysis 'X' not found." }]]);
    await expect(getTriage("X")).rejects.toThrow("Analysis 'X' not found.");
  });

  it("falls back to a generic message when the error body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 502, json: async () => { throw new Error("x"); } })));
    await expect(getTriage("X")).rejects.toThrow("Request failed (502)");
  });
});
