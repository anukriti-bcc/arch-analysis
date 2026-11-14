"""
Loads an architecture definition file (YAML) into:
  - a ComponentMapping: directory-name -> architectural_type
  - an Architecture: named set of ArchitectureRule

Expected schema (see rules/schema_example.yaml and
datasets/sample-ecommerce/architecture/rules.yaml for worked examples):

architecture:
  name: layered-architecture

component_mapping:
  controllers:
    type: controller
  services:
    type: service
  repositories:
    type: repository
  database:
    type: database

rules:
  - id: R001
    name: controller-service
    source: controller
    target: service
    relation: allowed
  - id: R003
    name: service-database
    source: service
    target: database
    relation: forbidden

This is intentionally simple (see currentplan.docx §6-7): only
allowed/forbidden relations are acted on for Milestone 1. `required` and
`conditional` are accepted by the schema (so files don't need rewriting
later) but the conformance engine does not yet implement them.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from models.rule import Architecture, ArchitectureRule, RelationType


class ArchitectureFileError(ValueError):
    """Raised when an architecture YAML file is missing required fields."""


@dataclass(frozen=True)
class ComponentMapping:
    """Maps a top-level (or nested) directory name to an architectural type.

    e.g. {"controllers": "controller", "services": "service", ...}
    """

    mapping: dict[str, str]
    # Real repositories are rarely organised so that a bare directory NAME identifies
    # a component (`core` appears in many places). Keys containing "/" in
    # component_mapping are therefore path prefixes relative to the scanned root
    # ("src/pkg/core" matches the package or the module file pkg/core.py). The longest
    # matching prefix wins. Empty for every directory-name-only file, so existing
    # behaviour is unchanged.
    path_prefixes: tuple[tuple[str, str], ...] = ()
    # `import_resolution: anchored` in the architecture file (see ModuleIndex.strict).
    anchored_imports: bool = False

    def type_for_directory(self, directory_name: str) -> str | None:
        return self.mapping.get(directory_name)

    def type_for_path(self, relative_path: str) -> str | None:
        if not self.path_prefixes:
            return None
        stem = relative_path[:-3] if relative_path.endswith(".py") else relative_path
        best: tuple[str, str] | None = None
        for prefix, component_type in self.path_prefixes:
            if stem == prefix or stem.startswith(prefix + "/"):
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, component_type)
        return best[1] if best else None


def load_architecture_file(path: str) -> tuple[Architecture, ComponentMapping]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ArchitectureFileError(f"Architecture file '{path}' is empty.")

    arch_meta = raw.get("architecture") or {}
    name = arch_meta.get("name", "unnamed-architecture")

    raw_mapping = raw.get("component_mapping") or {}
    mapping: dict[str, str] = {}
    path_prefixes: list[tuple[str, str]] = []
    for dir_name, cfg in raw_mapping.items():
        if not isinstance(cfg, dict) or "type" not in cfg:
            raise ArchitectureFileError(
                f"component_mapping entry '{dir_name}' must have a 'type' field."
            )
        if "/" in str(dir_name):
            path_prefixes.append((str(dir_name).strip("/"), cfg["type"]))
        else:
            mapping[dir_name] = cfg["type"]

    raw_rules = raw.get("rules") or []
    rules: list[ArchitectureRule] = []
    for r in raw_rules:
        for field_name in ("id", "source", "target", "relation"):
            if field_name not in r:
                raise ArchitectureFileError(
                    f"Rule {r} is missing required field '{field_name}'."
                )
        try:
            relation = RelationType(r["relation"])
        except ValueError as exc:
            raise ArchitectureFileError(
                f"Rule {r['id']} has unknown relation '{r['relation']}'."
            ) from exc
        rules.append(
            ArchitectureRule(
                id=r["id"],
                name=r.get("name", r["id"]),
                source=r["source"],
                target=r["target"],
                relation=relation,
                description=r.get("description", ""),
            )
        )

    return Architecture(name=name, rules=tuple(rules)), ComponentMapping(
        mapping=mapping,
        path_prefixes=tuple(sorted(path_prefixes, key=lambda kv: -len(kv[0]))),
        anchored_imports=str(raw.get("import_resolution", "")).lower() == "anchored",
    )
