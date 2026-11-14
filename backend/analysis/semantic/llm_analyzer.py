"""LLM-based semantic analysis of conformance findings (Milestone 4)."""
from __future__ import annotations

import json
import re
from typing import Any

from analysis.evidence.aggregator import EvidenceBundle
from analysis.semantic.base import SemanticAnalyzer
from analysis.semantic.llm_client import LLMClient, LLMResponse
from analysis.semantic.prompts import (
    PROMPT_VARIANTS, PROMPT_VERSION, render_edge_prompt, render_review_prompt,
)

REVIEW_VERDICTS = {"violation", "justified", "uncertain"}
EDGE_VERDICTS = {"conformant", "violation", "justified", "uncertain"}


def parse_verdict_json(text: str, allowed: set[str]) -> dict | None:
    """Extract the model's JSON object from its reply and validate it.

    Tolerates code fences and surrounding prose (small local models often add
    both). Returns None when no valid verdict can be recovered — the caller
    records that as a parse failure rather than guessing.
    """
    if not text:
        return None
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))
    # first balanced {...} block
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : i + 1])
                break
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        verdict = str(obj.get("verdict", "")).strip().lower()
        if verdict not in allowed:
            continue
        try:
            conf = float(obj.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        used = obj.get("evidence_used")
        return {
            "verdict": verdict,
            "confidence": min(max(conf, 0.0), 1.0),
            "explanation": str(obj.get("explanation", "")).strip(),
            "evidence_used": [str(u) for u in used] if isinstance(used, list) else [],
        }
    return None


def _check_variant(variant: str) -> str:
    if variant not in PROMPT_VARIANTS:
        raise ValueError(f"unknown prompt variant {variant!r}; choose from {sorted(PROMPT_VARIANTS)}")
    return variant


def _result(resp: LLMResponse, parsed: dict | None, mode: str, variant: str = "full") -> dict:
    return {
        "mode": mode,
        "prompt_version": PROMPT_VERSION,
        "prompt_variant": variant,
        "verdict": parsed["verdict"] if parsed else None,
        "confidence": parsed["confidence"] if parsed else None,
        "explanation": parsed["explanation"] if parsed else None,
        "evidence_used": parsed["evidence_used"] if parsed else [],
        "parsed_ok": parsed is not None,
        "error": resp.error if not resp.ok else (None if parsed else "unparseable model output"),
        "model": resp.model,
        "tokens_used": {"input": resp.input_tokens, "output": resp.output_tokens},
        "tokens_estimated": resp.tokens_estimated,
        "latency_s": resp.latency_s,
        "cached": resp.cached,
        "attempts": resp.attempts,
        "raw_text": resp.text,
    }


class LLMSemanticAnalyzer(SemanticAnalyzer):
    """Review a finding the deterministic checker has already flagged."""

    def __init__(self, client: LLMClient, *, include_adrs: bool = True, include_evolution: bool = True,
                 max_tokens: int = 600, variant: str = "full"):
        self.variant = _check_variant(variant)
        self.client = client
        self.include_adrs = include_adrs
        self.include_evolution = include_evolution
        self.max_tokens = max_tokens

    def analyze(self, finding: Any, evidence: EvidenceBundle) -> dict:
        prompt = render_review_prompt(
            evidence, include_adrs=self.include_adrs, include_evolution=self.include_evolution
        )
        system = PROMPT_VARIANTS[self.variant][0]
        resp = self.client.complete(system, prompt, temperature=0.0, max_tokens=self.max_tokens)
        parsed = parse_verdict_json(resp.text, REVIEW_VERDICTS) if resp.ok else None
        return _result(resp, parsed, "review", self.variant)


class LLMEdgeAnalyzer:
    """LLM-only baseline: judge a raw import with no structural pre-check."""

    def __init__(self, client: LLMClient, max_tokens: int = 600, variant: str = "full"):
        self.variant = _check_variant(variant)
        self.client = client
        self.max_tokens = max_tokens

    def analyze_edge(self, **fields: Any) -> dict:
        prompt = render_edge_prompt(**fields)
        system = PROMPT_VARIANTS[self.variant][1]
        resp = self.client.complete(system, prompt, temperature=0.0, max_tokens=self.max_tokens)
        parsed = parse_verdict_json(resp.text, EDGE_VERDICTS) if resp.ok else None
        return _result(resp, parsed, "edge", self.variant)
