// Talks to the FastAPI backend via the /api proxy set up in vite.config.js
// (see server.proxy) — so this file never needs to know the backend's
// host/port and CORS is a non-issue in dev.

const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const message = body.detail || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return res.json();
}

function qs(params) {
  const sp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== false) sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function analyzeRepository(repositoryPath, architectureFile) {
  return request("/repositories/analyze", {
    method: "POST",
    body: JSON.stringify({
      repository_path: repositoryPath,
      architecture_file: architectureFile,
    }),
  });
}

export function getAnalysis(analysisId) {
  return request(`/analysis/${analysisId}`);
}

export function getAnalysisGraph(analysisId) {
  return request(`/analysis/${analysisId}/graph`);
}

export function getAnalysisFindings(analysisId) {
  return request(`/analysis/${analysisId}/findings`);
}

// Finding ids (F001, ...) repeat across analysis runs, so always pass the run.
export function getFinding(findingId, analysisId) {
  return analysisId
    ? request(`/analysis/${analysisId}/findings/${findingId}`)
    : request(`/findings/${findingId}`);
}

export function getFindingEvolution(findingId, analysisId) {
  return request(`/findings/${findingId}/evolution${qs({ analysis_id: analysisId })}`);
}

// Intent + structural + evolution evidence and the policy's decision. No LLM.
export function getFindingEvidence(findingId, analysisId) {
  return request(`/findings/${findingId}/evidence${qs({ analysis_id: analysisId })}`);
}

// Runs the evidence-guided workflow; calls the LLM only if the policy says so (or force).
export function requestSemanticAnalysis(findingId, analysisId, force = false) {
  return request(
    `/findings/${findingId}/semantic-analysis${qs({ analysis_id: analysisId, force })}`,
    { method: "POST" }
  );
}

// "How would I fix this?" Rule-derived options always; AI-tailored steps when a model is connected. Nothing is applied.
export function requestRecommendation(findingId, analysisId, refresh = false) {
  return request(`/findings/${findingId}/recommendation${qs({ analysis_id: analysisId, refresh })}`, { method: "POST" });
}

// Per-violation: is the evidence sufficient, or does it need semantic review? No LLM.
export function getTriage(analysisId) {
  return request(`/analysis/${analysisId}/triage`);
}

export function listExperimentRuns() {
  return request("/experiments/runs");
}

export function getExperimentRun(name) {
  return request(`/experiments/runs/${encodeURIComponent(name)}`);
}

export function getExperimentPredictions(name, filters = {}) {
  return request(`/experiments/runs/${encodeURIComponent(name)}/predictions${qs(filters)}`);
}
