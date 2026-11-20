"""Readability gates: can the code-only reading of an ADR be TRUSTED for this dependency?

Why this module exists
----------------------
Experiments showed that the deterministic reader (`reader.py`, method M6) is not
only unsure on irregular ADR text, it is often *confidently wrong*: on the hard
tier 198 of its 216 readings were "clear" and only 56% were right. So "escalate
when the reader says unclear" is not a safe policy. What is needed is a test of
whether a clear-looking reading is *verifiable*.

A reading is trusted only if it passes every gate below. Each gate targets a
well-known way in which lexical reading of decision text goes wrong, and each
fails SAFE (a failed gate means "ask the model", never "decide"):

  G_clear        the reader reached a stance and a verdict for this dependency
  G_section      a Decision section exists (otherwise the whole ADR, including
                 Context that quotes the rule being overridden, was read)
  G_polarity     the decision text does not contain both prohibiting and
                 permitting cues (e.g. "rejected ... acceptable cost")
  G_negation     a reading of "permits" contains no negation anywhere in the
                 decision ("was not approved", "never directly ... acceptable")
  G_anchor       the sentence carrying the stance names BOTH ends of the
                 dependency, so the cue is about this dependency and not a
                 passing mention ("... is acceptable" two sentences after the
                 module was named)
  G_temporal     every calendar date is explained by a recognised cut-off
                 clause, and no temporal wording appears without one
                 ("up to the freeze on <date>", "until", "while under way")
  G_conditions   no hedge or condition ("unless", "only if", "except", "but")
  G_subject      the decision names no module other than the dependency's own
                 two ends, i.e. the stance does not have to be attributed to
                 one of several named subjects
  G_single       at most one active, strongly scoped ADR governs the dependency

Design notes
------------
* The gates are generic linguistic risk indicators, chosen from known failure
  modes of cue-based reading. They were nevertheless chosen after inspecting
  the reader's errors on the hard-tier DEVELOPMENT seeds, which the deviations
  log records; confirmation uses seeds and a wording not used here.
* Pure functions, no I/O. The gates read only the text and the reading; they
  never see the benchmark's labels or scenario names.
* Over-firing costs one model call; under-firing costs a silent error. The
  gates therefore err toward firing, and the evaluation reports both.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from analysis.intent.adr import ADR, ADRMatch
from analysis.intent.reader import (
    ADRReading, _PERMIT, _PROHIBIT, decision_section, find_dates, match_strength, read_adr, sentences,
)

_NEGATION = re.compile(r"\b(?:not|never|no|none|neither|nor|without|cannot|can't|won't|don't|doesn't|isn't|wasn't|n't)\b", re.I)
_CONDITION = re.compile(
    r"\b(?:unless|provided\s+that|only\s+if|only\s+when|except(?!ion)\w*|however|but|although|though|pending|"
    r"subject\s+to|conditional\w*|as\s+long\s+as|so\s+long\s+as|once|whereas)\b", re.I)
_TEMPORAL = re.compile(
    r"\b(?:until|till|freeze|frozen|deadline|temporar\w*|interim|for\s+now|under\s+way|underway|"
    r"in\s+progress|transition\w*|migrat\w*|phase[- ]?out|sunset\w*|within\s+\d+\s+(?:day|week|month|year)s?|"
    r"by\s+the\s+end\s+of|next\s+(?:release|quarter|sprint)|after|before|prior\s+to|since)\b", re.I)
_BACKTICKED = re.compile(r"`([^`\n]+)`")
# 'exception', 'approved', 'continue to' and 'bypass' also appear when a decision REJECTS an exception, so on their own
# they do not make a prohibiting decision contradictory; the cues below do.
_STRONG_PERMIT = re.compile(
    r"\b(?:allow\w*|permit\w*|may\b|will\s+(?:use|access|import|depend|call)|accept(?:s|ed)?\s+that|tolerat\w*|"
    r"acceptable|waive\w*|grandfather\w*|exempt\w*)\b", re.I)

GATES = ("G_clear", "G_section", "G_polarity", "G_negation", "G_anchor", "G_temporal", "G_conditions", "G_subject", "G_single")


def _stem(path_or_name: str) -> str:
    base = os.path.basename(path_or_name.replace("\\", "/"))
    base = re.sub(r"\.(py|pyi)$", "", base)
    return base.split(".")[-1].lower()


def named_subjects(text: str) -> set[str]:
    """Module-like names written in backticks in the text (reduced to a final dotted component)."""
    return {_stem(m.group(1).strip()) for m in _BACKTICKED.finditer(text) if m.group(1).strip()}


def _tokens(path_or_name: str) -> list[str]:
    return [t for t in re.split(r"[_\W]+", _stem(path_or_name)) if t]


def mentions(text: str, path_or_name: str) -> bool:
    """True if the text names a module either by its file stem (`booking_controller`) or by describing it
    with all of the stem's words ("the booking controller", "payment repositories"). Plural-tolerant.
    Deliberately generous: over-matching only means more escalation, never a silent verdict."""
    low = text.lower()
    stem = _stem(path_or_name)
    if stem and stem in low:
        return True
    toks = _tokens(path_or_name)
    return bool(toks) and all(re.search(rf"\b{re.escape(t)}(?:s|es|ies)?\b", low) for t in toks)


def scope_of(match: ADRMatch, source_path: str, target_path: str) -> str:
    """'strong' (names both ends or the introducing commit cites the ADR), 'described' (the text names or
    describes both ends), else 'weak' (shares only component-type words or a rule id).

    'described' fixes a gap of the v1 matcher, which needed file names: an ADR that says "the analytics
    service reads from the database connection module" is about this dependency even though it never
    writes `analytics_service`."""
    if match_strength(match) == "strong":
        return "strong"
    if mentions(match.adr.text, source_path) and mentions(match.adr.text, target_path):
        return "described"
    return "weak"


@dataclass
class Readability:
    """Outcome of the gates for one governing ADR."""
    adr_id: str
    reading: ADRReading
    failed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def decisive(self) -> bool:
        return not self.failed

    @property
    def verdict_violation(self) -> Optional[bool]:
        """The code verdict if decisive (True = genuine violation), else None."""
        if not self.decisive or self.reading.permitted is None:
            return None
        return not self.reading.permitted


def assess(
    adr: ADR, *, introduced: Optional[date], source_path: str, target_path: str, other_strong_active: int = 0,
) -> Readability:
    reading = read_adr(adr, introduced)
    section, found = decision_section(adr.text)
    sents = sentences(section)
    out = Readability(adr.id, reading)

    def fail(gate: str, why: str) -> None:
        if gate not in out.failed:
            out.failed.append(gate)
        out.notes.append(f"{gate}: {why}")

    if reading.stance == "unclear" or reading.permitted is None:
        fail("G_clear", "the reader reached no verdict")
    if not found:
        fail("G_section", "no Decision section")

    prohibit = [s for s in sents if _PROHIBIT.search(s)]
    permit = [s for s in sents if _PERMIT.search(s)]
    strong_permit = [s for s in sents if _STRONG_PERMIT.search(s)]
    if prohibit and strong_permit:
        fail("G_polarity", "both prohibiting and permitting cues: " + prohibit[0][:50] + " / " + strong_permit[0][:50])

    clause_sents = {c.sentence for c in reading.clauses}  # "introduced after D is NOT covered" is a cut-off, read as such
    if reading.stance == "permits":
        neg = [s for s in sents if _NEGATION.search(s) and s not in clause_sents]
        if neg:
            fail("G_negation", "negation in a decision read as permitting: " + neg[0][:70])

    cue_sents = prohibit if reading.stance == "prohibits" else permit
    if reading.stance in ("permits", "prohibits") and not any(
        mentions(s, source_path) and mentions(s, target_path) for s in cue_sents
    ):
        fail("G_anchor", "no stance-bearing sentence names both ends of the dependency")

    dates = find_dates(section)
    explained = len(reading.clauses)
    if dates and explained < len(dates):
        fail("G_temporal", f"{len(dates)} date(s) in the decision but {explained} recognised cut-off clause(s)")
    elif not dates and _TEMPORAL.search(section):
        fail("G_temporal", "temporal wording without a calendar date")
    elif dates and _TEMPORAL.search(section) and not reading.clauses:
        fail("G_temporal", "temporal wording with no recognised clause")

    cond = _CONDITION.search(section)
    if cond:
        fail("G_conditions", f"condition or hedge word '{cond.group(0)}'")

    names = named_subjects(section)
    own = {_stem(source_path), _stem(target_path)}
    foreign = {n for n in names - own if not (mentions(n, source_path) or mentions(n, target_path))}
    if foreign:
        fail("G_subject", "decision also names: " + ", ".join(sorted(foreign)))

    if other_strong_active > 0:
        fail("G_single", f"{other_strong_active} other active, strongly scoped ADR(s) also govern this dependency")
    return out


def governing_adr(matches: list[ADRMatch], source_path: str, target_path: str) -> tuple[Optional[ADRMatch], int]:
    """The latest active ADR that is about this dependency (strong or described scope; the reader's rules
    1-2) and how many others compete."""
    strong = [m for m in matches if m.adr.is_active and scope_of(m, source_path, target_path) != "weak"]
    if not strong:
        return None, 0
    gov = max(strong, key=lambda m: (m.adr.date or date.min, m.adr.id))
    return gov, len(strong) - 1
