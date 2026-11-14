"""Evidence aggregation (Milestone 3): gather everything known about one
conformance finding into a single EvidenceBundle.

The three evidence sources of the synopsis map onto the bundle like so:

  architectural intent -> rule text + ADRs (`adrs`)
  structural evidence  -> the dependency, its location and a code snippet
  evolution evidence   -> `evolution` (introducing commit, age, signals ...)

Evolution evidence also *improves* the intent evidence: a commit message that
cites "ADR-009" lets us pull that record in even when the record's wording
shares no file names or component types with the dependency (so a purely
text-based relevance test would miss it). This is one concrete way history can
inform interpretation, and it is switchable (`use_evolution=False`) so the
ablation "remove evolution evidence" removes it too.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from analysis.evolution.base import EvolutionAnalyzer
from analysis.evolution.git_evolution import GitRepo
from analysis.intent.adr import ADR, ADRMatch, find_relevant_adrs
from models.finding import Finding
from models.rule import Architecture


@dataclass
class EvidenceBundle:
    finding_key: str
    finding_id: str
    rule_id: Optional[str]
    rule_name: str
    rule_relation: str
    rule_description: str
    source_path: str
    target_path: str
    source_type: str
    target_type: str
    line: int
    import_reference: str
    code_snippet: str
    snapshot_date: Optional[str]
    adrs: list[ADRMatch] = field(default_factory=list)
    evolution: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "finding_key": self.finding_key,
            "rule": {
                "id": self.rule_id,
                "name": self.rule_name,
                "relation": self.rule_relation,
                "description": self.rule_description,
            },
            "structural": {
                "source": self.source_path,
                "target": self.target_path,
                "source_type": self.source_type,
                "target_type": self.target_type,
                "line": self.line,
                "import": self.import_reference,
                "code_snippet": self.code_snippet,
            },
            "snapshot_date": self.snapshot_date,
            "adrs": [m.to_dict(include_text=True) for m in self.adrs],
            "evolution": self.evolution,
        }


def read_snippet(repository_path: str, relative_path: str, line: int, radius: int = 4) -> str:
    full = os.path.join(repository_path, relative_path)
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return ""
    lo, hi = max(line - 1 - radius, 0), min(line + radius, len(lines))
    return "\n".join(f"{i + 1:>4}: {lines[i]}" for i in range(lo, hi))


class EvidenceAggregator:
    def __init__(
        self,
        repository_path: str,
        architecture: Architecture,
        adrs: list[ADR],
        evolution_analyzer: EvolutionAnalyzer | None = None,
    ):
        self.repository_path = os.path.abspath(repository_path)
        self.architecture = architecture
        self.adrs = adrs
        self.evolution_analyzer = evolution_analyzer
        self._snapshot_date: Optional[str] | bool = False  # False = not computed yet

    def snapshot_date(self) -> Optional[str]:
        """Date of the HEAD commit — the repository's 'now'. Deterministic,
        unlike the wall clock, and available to every method (it is a property
        of the repository state, not of the evolution analysis)."""
        if self._snapshot_date is False:
            repo = GitRepo(self.repository_path)
            value = None
            if repo.is_repo() and repo.head():
                value = repo.commit_info(repo.head()).date.isoformat()
            self._snapshot_date = value
        return self._snapshot_date  # type: ignore[return-value]

    def build(
        self,
        finding: Finding,
        *,
        use_adrs: bool = True,
        use_evolution: bool = True,
    ) -> EvidenceBundle:
        dep = finding.structural_evidence.dependency
        rule = next((r for r in self.architecture.rules if r.id == finding.rule_id), None)

        matches: list[ADRMatch] = []
        if use_adrs:
            matches = find_relevant_adrs(
                self.adrs,
                rule_id=finding.rule_id,
                source_path=dep.source,
                target_path=dep.target,
                source_type=dep.source_component,
                target_type=dep.target_component,
            )

        evolution = None
        if use_evolution and self.evolution_analyzer is not None:
            evolution = self.evolution_analyzer.analyze(self.repository_path, finding)
            if use_adrs and evolution and evolution.get("available"):
                cited = (evolution.get("message_signals") or {}).get("adr_references", [])
                by_id = {m.adr.id: m for m in matches}
                for adr_id in cited:
                    known = next((a for a in self.adrs if a.id == adr_id), None)
                    if known is None:
                        continue
                    if adr_id in by_id:
                        old = by_id[adr_id]
                        by_id[adr_id] = ADRMatch(old.adr, (*old.reasons, "commit_reference"))
                    else:
                        by_id[adr_id] = ADRMatch(known, ("commit_reference",))
                matches = sorted(by_id.values(), key=lambda m: m.adr.id)

        return EvidenceBundle(
            finding_key=finding.key,
            finding_id=finding.id,
            rule_id=finding.rule_id,
            rule_name=rule.name if rule else "",
            rule_relation=rule.relation.value if rule else "",
            rule_description=rule.description if rule else "",
            source_path=dep.source,
            target_path=dep.target,
            source_type=dep.source_component,
            target_type=dep.target_component,
            line=dep.location.line,
            import_reference=dep.raw_reference,
            code_snippet=read_snippet(self.repository_path, dep.source, dep.location.line),
            snapshot_date=self.snapshot_date(),
            adrs=matches,
            evolution=evolution,
        )
