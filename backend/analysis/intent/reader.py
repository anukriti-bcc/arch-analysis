"""Deterministic reading of an Architecture Decision Record (no LLM).

Why this module exists
----------------------
An examiner's obvious question is "why do you need an LLM at all?". This module
is the honest answer's other half: it extracts, with plain code, as much of an
ADR's meaning as code can reliably extract, so the evaluation can measure how
far code alone gets (baseline M6) and where it stops.

What it reads
-------------
  * SCOPE    does the ADR name both ends of the dependency, or is it cited by
             the commit that introduced the dependency? (`match_strength`)
  * STANCE   does the decision text permit or prohibit? Only the *Decision*
             section is read (Nygard "Decision", MADR "Decision Outcome"),
             because Context sections routinely quote the rule being
             overridden ("rule R005 normally forbids this ...").
  * DATES    cut-off clauses such as "introduced on or before 2025-09-13", in
             several common date formats, compared in code against the date the
             dependency was introduced.

Design rules
------------
  * Written from general ADR conventions, not from the benchmark generator's
    sentences. Several date formats and phrasings are supported on purpose, so
    the baseline is not a straw man.
  * Conservative: when the reading is unclear it says so (`stance="unclear"`),
    and callers fall back to the structural verdict instead of guessing.
  * Pure functions, no I/O: everything is unit-testable.

Known limits (these are the point of the comparison, not bugs to hide):
  negation spread over several sentences, conditions that are not dates
  ("until the migration completes"), scope expressed by description rather
  than by name, and any ADR whose Decision section is missing or free-form.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from analysis.intent.adr import ADR, ADRMatch

# ------------------------------------------------------------------ scope

STRONG_REASONS = frozenset({"file_names", "commit_reference"})


def match_strength(match: ADRMatch) -> str:
    """'strong' when the ADR names both endpoints or the introducing commit
    cites it; 'weak' when it only shares component-type words or a rule id
    (a rule id alone shows the ADR is about the *rule*, not this dependency)."""
    return "strong" if STRONG_REASONS & set(match.reasons) else "weak"


# ------------------------------------------------------------------ sections

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.*?)\s*#*\s*$")
_DECISION_HEADING = re.compile(r"^(?:decision(?:\s+outcome)?|outcome|resolution|decision\s+and\s+rationale)\b", re.I)


def _strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("\n")
        for i in range(1, len(parts)):
            if parts[i].strip() == "---":
                return "\n".join(parts[i + 1 :])
    return text


def decision_section(text: str) -> tuple[str, bool]:
    """(text of the Decision section, whether such a section was found).
    Falls back to the whole body when no Decision heading exists."""
    body = _strip_front_matter(text)
    lines = body.split("\n")
    out: list[str] = []
    inside = False
    found = False
    for line in lines:
        m = _HEADING.match(line)
        if m:
            title = re.sub(r"^\d+[.):]\s*", "", m.group(1))
            if _DECISION_HEADING.match(title):
                inside, found = True, True
                continue
            if inside:
                break
        elif inside:
            out.append(line)
    return ("\n".join(out).strip(), True) if found else (body, False)


def sentences(text: str) -> list[str]:
    text = text.replace("`", "")
    chunks = re.split(r"\n\s*\n|\n(?=\s*[-*]\s)", text)
    out: list[str] = []
    for chunk in chunks:
        chunk = " ".join(chunk.split())
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", chunk) if s.strip()]
    return out


# ------------------------------------------------------------------ dates

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

_DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"), lambda m: (m[1], m[2], m[3])),
    (re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?,?\s+(\d{{4}})", re.I),
     lambda m: (m[3], m[2], m[1])),
    (re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", re.I), lambda m: (m[3], m[1], m[2])),
]


def _mk(y, mo, d) -> Optional[date]:
    try:
        month = int(mo) if str(mo).isdigit() else _MONTHS[str(mo).lower().rstrip(".")]
        return date(int(y), month, int(d))
    except (ValueError, KeyError):
        return None


@dataclass(frozen=True)
class FoundDate:
    value: date
    start: int
    end: int


def find_dates(text: str) -> list[FoundDate]:
    found: list[FoundDate] = []
    for rx, pick in _DATE_PATTERNS:
        for m in rx.finditer(text):
            d = _mk(*pick(m))
            if d and not any(f.start < m.end() and m.start() < f.end for f in found):
                found.append(FoundDate(d, m.start(), m.end()))
    return sorted(found, key=lambda f: f.start)


# ------------------------------------------------------------------ stance cues

_PROHIBIT = re.compile(
    r"\b(?:must\s+not|shall\s+not|should\s+not|may\s+not|cannot|can\s+not|will\s+not|won't|do(?:es)?\s+not\s+(?:allow|permit)"
    r"|not\s+(?:be\s+)?(?:allowed|permitted|acceptable|authori[sz]ed)|forbid\w*|prohibit\w*|disallow\w*|reject\w*"
    r"|den(?:y|ied|ies|ial)|declin\w*|reaffirm\w*|no\s+exceptions?|not\s+an\s+exception|remains?\s+(?:forbidden|prohibited))\b",
    re.I,
)
_NOT_COVERED = re.compile(r"\bnot\s+(?:be\s+)?(?:covered|exempt|grandfathered|included)|\bno\s+longer\s+(?:permitted|allowed)"
                          r"|\bmust\s+be\s+treated\s+as\s+a\s+violation|\bis\s+a\s+violation\b", re.I)
_PERMIT = re.compile(
    r"\b(?:allow\w*|permit\w*|may\b|will\s+(?:use|access|import|depend|call)|exception|exempt\w*|grandfather\w*"
    r"|accept(?:s|ed)?\s+that|tolerat\w*|acceptable|waive\w*|approv\w*|continue\s+to|bypass\w*)\b",
    re.I,
)

_BEFORE_INCL = re.compile(r"(?:on\s+or\s+before|no\s+later\s+than|not\s+later\s+than|up\s+to\s+and\s+including|through|until|till|by)\s*$", re.I)
_BEFORE_EXCL = re.compile(r"(?:before|prior\s+to|earlier\s+than|up\s+to)\s*$", re.I)
_AFTER = re.compile(r"(?:after|later\s+than|since|following|from)\s*$", re.I)


@dataclass(frozen=True)
class DateClause:
    kind: str  # 'through' (<= d) | 'before' (< d) | 'after' (> d)
    cutoff: date
    sentence: str

    def permits(self, introduced: date) -> bool:
        return {"through": introduced <= self.cutoff, "before": introduced < self.cutoff,
                "after": introduced > self.cutoff}[self.kind]


def _date_clauses(sents: list[str]) -> tuple[list[DateClause], list[str]]:
    """Date-bearing sentences that express a cut-off, and the sentences that
    were consumed doing so (so stance is not judged on them)."""
    clauses: list[DateClause] = []
    consumed: list[str] = []
    for s in sents:
        dates = find_dates(s)
        if not dates:
            continue
        negative = bool(_NOT_COVERED.search(s) or _PROHIBIT.search(s))
        positive = bool(_PERMIT.search(s))
        for fd in dates:
            before = s[: fd.start]
            before_type = True
            if _BEFORE_INCL.search(before):
                kind = "through"
            elif _BEFORE_EXCL.search(before):
                kind = "before"
            elif _AFTER.search(before):
                before_type = False
                # "introduced after D is NOT covered" == permitted through D;
                # "allowed for code introduced after D" == permitted only after D.
                kind = "through" if negative else "after"
                if not negative and not positive:
                    continue
            else:
                continue
            if before_type and negative and not positive:
                continue  # "forbidden before D": a shape we deliberately do not interpret
            clauses.append(DateClause(kind, fd.value, s))
            consumed.append(s)
    return clauses, consumed


# ------------------------------------------------------------------ reading

@dataclass
class ADRReading:
    adr_id: str
    stance: str  # 'permits' | 'prohibits' | 'unclear'
    section_found: bool
    clauses: list[DateClause] = field(default_factory=list)
    permitted: Optional[bool] = None  # for THIS dependency, after applying date clauses; None = could not tell
    notes: list[str] = field(default_factory=list)


def read_adr(adr: ADR, introduced: Optional[date]) -> ADRReading:
    section, found = decision_section(adr.text)
    sents = sentences(section)
    clauses, consumed = _date_clauses(sents)
    rest = [s for s in sents if s not in consumed]

    prohibits = [s for s in rest if _PROHIBIT.search(s) or _NOT_COVERED.search(s)]
    permits = [s for s in rest if _PERMIT.search(s) and s not in prohibits]
    reading = ADRReading(adr.id, "unclear", found, clauses)
    if not found:
        reading.notes.append("no Decision section; whole text read")

    if prohibits:
        reading.stance, reading.permitted = "prohibits", False
        reading.notes.append("prohibition cue: " + prohibits[0][:90])
        return reading
    if not permits and not clauses:
        reading.notes.append("no permission or prohibition cue in the decision text")
        return reading

    reading.stance = "permits"
    if clauses:
        if introduced is None:
            reading.notes.append("date clause present but introduction date unknown")
            return reading
        verdicts = {c.permits(introduced) for c in clauses}
        reading.permitted = all(c.permits(introduced) for c in clauses)
        reading.notes.append(
            "date clause: " + "; ".join(f"{c.kind} {c.cutoff.isoformat()}" for c in clauses)
            + f" vs introduced {introduced.isoformat()}"
        )
        if len(verdicts) > 1:
            reading.notes.append("date clauses disagree; treated as not permitted")
    else:
        reading.permitted = True
    return reading


# ------------------------------------------------------------------ decision

@dataclass
class DeterministicDecision:
    predicted_violation: bool
    outcome: str  # 'justified' | 'violation' | 'unclear'
    reason: str
    adr_id: Optional[str] = None


def introduction_date(evolution: Optional[dict]) -> Optional[date]:
    """Date the dependency was introduced, from the Git evolution evidence (None when unknown)."""
    if not evolution or not evolution.get("available"):
        return None
    raw = evolution.get("introduced_at")
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def decide_deterministic(matches: list[ADRMatch], evolution: Optional[dict]) -> DeterministicDecision:
    """The code-only verdict for one structural violation.

    1. keep ADRs that are still active and strongly scoped to this dependency
    2. let the most recent of them govern (later decisions override earlier)
    3. read it; justified only if it clearly permits THIS dependency
    Anything unclear keeps the structural verdict (violation), labelled so.
    """
    strong = [m for m in matches if m.adr.is_active and match_strength(m) == "strong"]
    if not strong:
        why = "no relevant ADR" if not matches else "relevant ADRs are inactive or only weakly scoped"
        return DeterministicDecision(True, "violation", why)
    governing = max(strong, key=lambda m: (m.adr.date or date.min, m.adr.id))
    reading = read_adr(governing.adr, introduction_date(evolution))
    note = f"{governing.adr.id}: {reading.stance}; " + "; ".join(reading.notes)
    if reading.permitted is True:
        return DeterministicDecision(False, "justified", note, governing.adr.id)
    if reading.permitted is False:
        return DeterministicDecision(True, "violation", note, governing.adr.id)
    return DeterministicDecision(True, "unclear", note, governing.adr.id)


_intro_date = introduction_date  # backwards-compatible alias
