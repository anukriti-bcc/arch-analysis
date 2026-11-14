"""Architecture Decision Records (ADRs) as a source of *architectural intent*.

The synopsis names ADRs, alongside explicit rules, as the intent evidence
the project reasons over (Buchgeher et al. 2023 found ADRs in 921 GitHub
repositories). Real ADRs are free text in a handful of loose conventions, so
this parser is deliberately tolerant. It understands:

  * Nygard format   -> "# 7. Title", "Date: 2026-01-01", "## Status\\n\\nAccepted"
  * MADR format     -> "# Title", "* Status: accepted", "* Date: 2026-01-01"
  * YAML front matter -> "---\\nid: ADR-007\\nstatus: accepted\\ndate: 2026-01-01\\n---"

It extracts only what is cheap and reliable to extract deterministically:
id, title, status, date. Everything else stays as raw text, because deciding
what a decision *means* for a given dependency is exactly the semantic task
the LLM layer exists for.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import yaml

# Directories (relative to the repository root) searched for ADR files.
ADR_DIRECTORIES = (
    "architecture/adr",
    "architecture/adrs",
    "architecture/decisions",
    "docs/adr",
    "docs/adrs",
    "docs/decisions",
    "docs/architecture/decisions",
    "doc/adr",
    "adr",
    "adrs",
    "decisions",
)

# Statuses after which a decision no longer authorises anything.
INACTIVE_STATUSES = frozenset({"superseded", "deprecated", "rejected"})

_ID_IN_TEXT = re.compile(r"\bADR[-_ ]?0*(\d+)\b", re.IGNORECASE)
_FILENAME_ID = re.compile(r"^(?:adr[-_ ]?)?0*(\d+)", re.IGNORECASE)
_HEADING_ID = re.compile(r"^#\s*(?:ADR[-_ ]?)?0*(\d+)\s*[.:\-–]\s*(.+)$", re.IGNORECASE)
_DATE_LINE = re.compile(r"^\W*date\W*[:=]\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE | re.MULTILINE)
_STATUS_LINE = re.compile(r"^\W*status\W*[:=]\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def normalize_adr_id(number: int | str) -> str:
    """ADR ids are written many ways (ADR-7, adr_007, 0007). Normalise."""
    return f"ADR-{int(number):03d}"


def extract_adr_references(text: str) -> list[str]:
    """Every ADR id mentioned in free text (e.g. a commit message), normalised
    and de-duplicated, in order of first appearance."""
    seen: list[str] = []
    for m in _ID_IN_TEXT.finditer(text or ""):
        adr_id = normalize_adr_id(m.group(1))
        if adr_id not in seen:
            seen.append(adr_id)
    return seen


def normalize_status(raw: str | None) -> str:
    """Collapse the many ways status is written into a small fixed set:
    accepted | proposed | superseded | deprecated | rejected | unknown."""
    if not raw:
        return "unknown"
    word = re.sub(r"[^a-z ]", " ", raw.lower()).split()
    head = word[0] if word else ""
    if head in {"accepted", "approved", "adopted", "active", "decided"}:
        return "accepted"
    if head in {"proposed", "draft", "pending"}:
        return "proposed"
    if head in {"superseded", "replaced", "obsoleted", "obsolete"}:
        return "superseded"
    if head == "deprecated":
        return "deprecated"
    if head == "rejected":
        return "rejected"
    return "unknown"


@dataclass(frozen=True)
class ADR:
    id: str
    title: str
    status: str  # normalised, see normalize_status
    status_raw: str
    date: Optional[date]
    path: str  # relative to the repository root
    text: str  # full file contents, untouched

    @property
    def is_active(self) -> bool:
        """False only when the record says it no longer applies. A missing or
        unparseable status is treated as possibly-active: we would rather
        escalate an unclear record to semantic review than silently discard it."""
        return self.status not in INACTIVE_STATUSES

    def to_dict(self, include_text: bool = False) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "status_raw": self.status_raw,
            "date": self.date.isoformat() if self.date else None,
            "path": self.path,
        }
        if include_text:
            d["text"] = self.text
        return d


def _split_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n")
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            try:
                meta = yaml.safe_load("\n".join(parts[1:i])) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), "\n".join(parts[i + 1 :])
    return {}, text


def _status_from_section(body: str) -> str | None:
    """Nygard style: a '## Status' heading followed by the status on the next
    non-empty line."""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s*status\s*$", line.strip(), re.IGNORECASE):
            for nxt in lines[i + 1 :]:
                if nxt.strip():
                    return nxt.strip()
    return None


def _to_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def parse_adr(relative_path: str, text: str) -> ADR:
    meta, body = _split_front_matter(text)
    filename = os.path.basename(relative_path)
    stem = filename.rsplit(".", 1)[0]

    # --- title (and possibly id) from the first heading
    title, heading_number = stem, None
    for line in body.split("\n"):
        if line.startswith("#"):
            m = _HEADING_ID.match(line.strip())
            if m:
                heading_number, title = m.group(1), m.group(2).strip()
            else:
                title = line.lstrip("#").strip() or stem
            break

    # --- id: front matter > filename > heading
    adr_id = None
    if meta.get("id") is not None:
        refs = extract_adr_references(str(meta["id"])) or [
            normalize_adr_id(m.group(1)) for m in [re.search(r"(\d+)", str(meta["id"]))] if m
        ]
        adr_id = refs[0] if refs else None
    if adr_id is None:
        m = _FILENAME_ID.match(stem)
        if m:
            adr_id = normalize_adr_id(m.group(1))
    if adr_id is None and heading_number is not None:
        adr_id = normalize_adr_id(heading_number)
    if adr_id is None:
        adr_id = f"ADR-{stem}"

    # --- status: front matter > section > "Status:" line
    status_raw = ""
    if meta.get("status") is not None:
        status_raw = str(meta["status"])
    else:
        status_raw = _status_from_section(body) or ""
        if not status_raw:
            m = _STATUS_LINE.search(body)
            status_raw = m.group(1).strip() if m else ""

    # --- date: front matter > "Date:" line
    adr_date = _to_date(meta.get("date"))
    if adr_date is None:
        m = _DATE_LINE.search(body)
        if m:
            adr_date = _to_date(m.group(1))

    return ADR(
        id=adr_id,
        title=title,
        status=normalize_status(status_raw),
        status_raw=status_raw,
        date=adr_date,
        path=relative_path.replace(os.sep, "/"),
        text=text,
    )


def load_adrs(repository_path: str, extra_dirs: tuple[str, ...] = ()) -> list[ADR]:
    """Load every ADR found under the conventional ADR directories."""
    root = os.path.abspath(repository_path)
    found: dict[str, ADR] = {}
    for rel_dir in (*ADR_DIRECTORIES, *extra_dirs):
        directory = os.path.join(root, rel_dir)
        if not os.path.isdir(directory):
            continue
        for fname in sorted(os.listdir(directory)):
            if not fname.lower().endswith((".md", ".markdown", ".txt")):
                continue
            if fname.lower() in {"readme.md", "index.md", "template.md"}:
                continue
            full = os.path.join(directory, fname)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel in found:
                continue
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                found[rel] = parse_adr(rel, f.read())
    return sorted(found.values(), key=lambda a: a.id)


# ---------------------------------------------------------------- relevance


@dataclass(frozen=True)
class ADRMatch:
    adr: ADR
    reasons: tuple[str, ...]  # why this ADR was judged relevant

    def to_dict(self, include_text: bool = False) -> dict:
        d = self.adr.to_dict(include_text=include_text)
        d["match_reasons"] = list(self.reasons)
        return d


_GENERIC_STEMS = frozenset({"__init__", "index", "main", "app", "utils", "util", "common", "base"})


def _mentions(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE))


def _stem(path: str) -> str:
    return os.path.basename(path).rsplit(".", 1)[0]


def find_relevant_adrs(
    adrs: list[ADR],
    *,
    rule_id: str | None,
    source_path: str,
    target_path: str,
    source_type: str,
    target_type: str,
) -> list[ADRMatch]:
    """Cheap, deterministic, *recall-oriented* relevance test.

    An ADR is a candidate when its text mentions
      - the id of the rule that was triggered, OR
      - the file names of both ends of the dependency, OR
      - the architectural component types of both ends.

    This intentionally over-matches: it is only deciding which records are
    worth *reading*. Whether a record actually authorises or forbids the
    dependency is a semantic judgement left to the LLM (or to the policy's
    cheap rules about record status).
    """
    src_stem, tgt_stem = _stem(source_path), _stem(target_path)
    matches: list[ADRMatch] = []
    for adr in adrs:
        reasons: list[str] = []
        if rule_id and _mentions(adr.text, rule_id):
            reasons.append("rule_id")
        if (
            src_stem not in _GENERIC_STEMS
            and tgt_stem not in _GENERIC_STEMS
            and _mentions(adr.text, src_stem)
            and _mentions(adr.text, tgt_stem)
        ):
            reasons.append("file_names")
        if source_type and target_type and _mentions(adr.text, source_type) and _mentions(adr.text, target_type):
            reasons.append("component_types")
        if reasons:
            matches.append(ADRMatch(adr=adr, reasons=tuple(reasons)))
    return matches
