"""A deterministic STAND-IN for a language model.

It exists so the whole experiment pipeline can be smoke-tested, demonstrated
and unit-tested without an API key or a local model. It is a few keyword rules
that read the prompt the way a careful human would on the benchmark's ADR
wording. It is NOT a language model and its numbers are NOT results: the runner
stamps every output produced with it as a smoke test.
"""
from __future__ import annotations

import json
import re

_INACTIVE = {"superseded", "rejected", "deprecated"}


def _blocks(prompt: str) -> list[str]:
    return re.findall(r"<adr id=.*?</adr>", prompt, re.S)


def _judge_block(block: str, src_stem: str, intro: str | None) -> str:
    low = block.lower()
    m = re.search(r"status \(parsed\): (\w+)", low)
    if m and m.group(1) in _INACTIVE:
        return "no"
    if "reaffirm" in low or "was reviewed and rejected" in low:
        return "no"
    if "grandfathered" in low:
        cutoff = re.search(r"on or before (\d{4}-\d{2}-\d{2})", low)
        if not cutoff:
            return "no"
        if intro is None:
            return "uncertain"
        return "yes" if intro <= cutoff.group(1) else "no"
    if "permanent" in low and "exception" in low:
        return "yes" if src_stem.lower() in low else "no"
    if "commit_reference" in low and "may query" in low:
        return "yes"
    return "no"


def _verdict(blocks: list[str], src_stem: str, intro: str | None, allowed_no: str) -> dict:
    results = [_judge_block(b, src_stem, intro) for b in blocks]
    if "yes" in results:
        v, why = "justified", "An active decision record permits this dependency."
    elif "uncertain" in results:
        v, why = "uncertain", "A date condition applies but the introduction date is unknown."
    else:
        v, why = allowed_no, "No active decision record permits this dependency."
    return {"verdict": v, "confidence": 0.7, "explanation": why, "evidence_used": []}


def mock_model(system: str, prompt: str) -> str:
    blocks = _blocks(prompt)
    if "ONE import statement" in system:  # LLM-only edge prompt
        src = re.search(r"Source file: (\S+)", prompt)
        tgt = re.search(r"resolves to (\S+)\)", prompt)
        types = dict(re.findall(r"^\s+(\w+)/ -> (\w+)$", prompt, re.M))

        def type_of(path: str) -> str | None:
            return next((types[d] for d in path.split("/")[:-1][::-1] if d in types), None)

        forbidden = set(re.findall(r"\[forbidden\] (\w+) -> (\w+)", prompt))
        if not src or not tgt or (type_of(src.group(1)), type_of(tgt.group(1))) not in forbidden:
            return json.dumps({"verdict": "conformant", "confidence": 0.7, "explanation": "Allowed by the rules.", "evidence_used": []})
        stem = src.group(1).rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return json.dumps(_verdict(blocks, stem, None, "violation"))
    src = re.search(r"Source file: (\S+)", prompt)
    stem = src.group(1).rsplit("/", 1)[-1].rsplit(".", 1)[0] if src else ""
    intro = re.search(r"introduced on (\d{4}-\d{2}-\d{2})", prompt)
    return json.dumps(_verdict(blocks, stem, intro.group(1) if intro else None, "violation"))
