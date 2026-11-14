// Small display helpers. Dates are formatted in UTC so output does not depend
// on the viewer's time zone (commit dates are what matters, not "where you are").

export function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

export function formatFixed(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

export function formatInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Math.round(Number(value)).toLocaleString("en-US");
}

export function plural(n, singular, pluralForm) {
  return `${n} ${n === 1 ? singular : pluralForm || `${singular}s`}`;
}

export function shortSha(sha) {
  return sha ? String(sha).slice(0, 8) : "";
}

export const INACTIVE_ADR_STATUSES = ["superseded", "deprecated", "rejected"];

export function isActiveAdrStatus(status) {
  return !INACTIVE_ADR_STATUSES.includes(String(status || "").toLowerCase());
}

export const MATCH_REASON_LABELS = {
  rule_id: "names the triggered rule",
  file_names: "names both files",
  component_types: "mentions both layers",
  commit_reference: "cited by the introducing commit",
};

export const METHOD_LABELS = {
  M1_static: "M1 Static rules",
  M2_llm_only: "M2 LLM-only",
  M3_full_hybrid: "M3 Full hybrid",
  M4_generic_selective_mean: "M4 Generic selective (mean of seeds)",
  M5_evidence_guided: "M5 Evidence-guided (proposed)",
  A1_no_history: "A1 No evolution evidence",
  A2_no_intent: "A2 No intent evidence",
};

export function methodLabel(method) {
  if (METHOD_LABELS[method]) return METHOD_LABELS[method];
  const seed = /^M4_generic_selective_s(\d+)$/.exec(method || "");
  return seed ? `M4 Generic selective (seed ${seed[1]})` : method;
}

export function methodShort(method) {
  const m = /^([A-Z]\d)/.exec(method || "");
  return m ? m[1] : method;
}
