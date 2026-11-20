"""Stance attribution check for mixed decisions (the fix for scenario M).

Measured problem: when ONE decision permits module X and requires module Y (the flagged one) to keep to the rule, the
extractor's single `decision` field is answered for the ADR as a whole. In 7 of 18 confirmation cases the model said
"permits, covers this module: yes" and the permission written for X was applied to Y (a real violation called justified).

The check is code, in the same spirit as `ground_limit`: it needs no prompt change and no extra call. A "permits" reading
is accepted when the decision is about this dependency alone, or when a sentence that mentions THIS source module carries
a permitting cue. If a decision names other modules and no sentence about this module permits anything, the permission
belongs to someone else: the reading is changed to `does_not_address`, which the computation turns into a violation.

Limits (stated, not hidden): it relies on the reader's permitting-cue lexicon, and on a permission and the module it is
given to sharing a sentence. A permission expressed in a sentence that only says "it", or in words outside the lexicon, is
downgraded to a violation (the conservative direction: a justified dependency is reported, never hidden). It only runs when
the decision names a module other than this dependency's two ends.
"""
from __future__ import annotations

from analysis.intent.readability import _stem, mentions, named_subjects
import re

from analysis.intent.reader import _PERMIT, decision_section

_CLAUSE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def clauses(section: str) -> list[str]:
    """Sentence-ish units. Unlike the reader's splitter this also breaks before a lower-case or backticked word,
    because decisions often start a sentence with a module name written in backticks."""
    return [c.strip() for c in _CLAUSE_SPLIT.split(section) if c.strip()]


def foreign_subjects(section: str, source_path: str, target_path: str) -> set[str]:
    own = {_stem(source_path), _stem(target_path)}
    return {n for n in named_subjects(section) - own if not (mentions(n, source_path) or mentions(n, target_path))}


def check_attribution(x: dict, adrs: list, source_path: str, target_path: str) -> dict:
    """Return a copy of the extraction with `attribution` noting what the check did (never raises)."""
    out = dict(x)
    out["attribution"] = "not applicable"
    if x.get("decision") != "permits" or x.get("covers_this_dependency") != "yes":
        return out
    chosen = [m.adr for m in adrs if x.get("adr_id") and m.adr.id == x["adr_id"]] or [m.adr for m in adrs if m.adr.is_active]
    if not chosen:
        return out
    notes = []
    for a in chosen:
        section, _ = decision_section(a.text)
        foreign = foreign_subjects(section, source_path, target_path)
        if not foreign:
            out["attribution"] = "accepted: the decision is about this dependency alone"
            return out
        own_sents = [s for s in clauses(section) if mentions(s, source_path)]
        if any(_PERMIT.search(s) for s in own_sents):
            out["attribution"] = "accepted: a sentence about this module permits it (decision also names " + ", ".join(sorted(foreign)) + ")"
            return out
        notes.append(a.id)
    out.update(
        decision="does_not_address",
        attribution="rejected: the decision names other modules and no sentence about this module permits it, so the permission is theirs",
    )
    return out
