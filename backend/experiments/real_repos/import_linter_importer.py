"""Turn a repository's import-linter contracts into this project's architecture file.

import-linter contracts are written over *module paths* ("sqlfluff.core" must not
import "sqlfluff.api"). The conformance engine works on *component types* between
which `allowed` / `forbidden` relations hold. The bridge:

  * every module named in a contract becomes a component type (its dotted name) mapped
    to a path prefix (component_mapping keys containing "/", see rules/loader.py);
  * `forbidden`    source -> forbidden            => forbidden rules
  * `layers`       a lower layer must not import a higher one; layers joined with
                   "|" are siblings that must not import each other
  * `independence` modules must not import each other (both directions)
  * containment is expanded: a rule on package P also applies to any mapped component
    inside P (needed because the engine matches exact types, import-linter matches
    packages and everything below them);
  * `ignore_imports` is NOT turned into rules. It is written to tolerated.json, with the
    team's own comment (the reason) attached to each entry.

Known fidelity limits (reported, never hidden):
  * the engine checks DIRECT imports only; import-linter also reports indirect chains;
  * contract types other than forbidden/layers/independence are skipped (listed);
  * wildcard ignore_imports and `allow_indirect_imports` are not interpreted.
"""
from __future__ import annotations

import configparser
import io
import itertools
import os
import re
import tomllib
from dataclasses import dataclass, field

import yaml

SUPPORTED = {"forbidden", "layers", "independence"}


@dataclass
class Contract:
    name: str
    type: str
    fields: dict
    tolerated: list[dict] = field(default_factory=list)  # [{"importer","imported","reason"}]


# ----------------------------------------------------------------------------- parsing
def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    out = []
    for line in str(v).splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


_ARROW = re.compile(r"^\s*([\w.*]+)\s*->\s*([\w.*]+)\s*$")


def _tolerated_with_reasons(raw_text: str, entries: list[str]) -> list[dict]:
    """Attach the comment lines immediately above each `a -> b` entry in the raw file."""
    reasons: dict[str, str] = {}
    pending: list[str] = []
    last_reason = ""  # consecutive entries under one comment share its reason
    for line in raw_text.splitlines():
        stripped = line.strip().lstrip(",").strip()
        if stripped.startswith("#"):
            pending.append(stripped.lstrip("#").strip())
            continue
        m = re.search(r"([\w.*]+)\s*->\s*([\w.*]+)", stripped)
        if m:
            if pending:
                last_reason = " ".join(pending)
            reasons.setdefault(f"{m.group(1)} -> {m.group(2)}", last_reason)
            pending = []
        elif stripped and not stripped.startswith(("]", "[")) and "=" in stripped:
            pending, last_reason = [], ""
    out = []
    for e in entries:
        m = _ARROW.match(e.strip().strip('"\','))
        if m:
            out.append({"importer": m.group(1), "imported": m.group(2),
                        "reason": reasons.get(f"{m.group(1)} -> {m.group(2)}", "")})
    return out


def parse_config(path: str, text: str) -> tuple[dict, list[Contract]]:
    """Return (global options, contracts) from .importlinter / setup.cfg / tox.ini / pyproject.toml."""
    base = os.path.basename(path)
    contracts: list[Contract] = []
    if base == "pyproject.toml":
        data = tomllib.loads(text).get("tool", {}).get("importlinter", {})
        opts = {k: v for k, v in data.items() if k != "contracts"}
        for c in data.get("contracts", []):
            fields = {k: v for k, v in c.items() if k not in ("name", "type", "id")}
            con = Contract(name=c.get("name", c.get("id", "?")), type=c.get("type", "?"), fields=fields)
            con.tolerated = _tolerated_with_reasons(_toml_block(text, con.name), _as_list(c.get("ignore_imports")))
            contracts.append(con)
        return opts, contracts
    cp = configparser.ConfigParser(interpolation=None, allow_no_value=True, strict=False)
    cp.optionxform = str
    cp.read_file(io.StringIO(text))
    opts = dict(cp["importlinter"]) if cp.has_section("importlinter") else {}
    for sec in cp.sections():
        if sec.startswith("importlinter:contract"):
            d = dict(cp[sec])
            fields = {k: v for k, v in d.items() if k not in ("name", "type")}
            con = Contract(name=d.get("name", sec.split(":")[-1]), type=(d.get("type") or "?").strip(), fields=fields)
            con.tolerated = _tolerated_with_reasons(_ini_block(text, sec), _as_list(d.get("ignore_imports")))
            contracts.append(con)
    return opts, contracts


def _toml_block(text: str, name: str) -> str:
    parts = re.split(r"\n(?=\[\[tool\.importlinter\.contracts\]\])", text)
    for p in parts:
        if f'"{name}"' in p or f"'{name}'" in p:
            return p.split("\n[tool.", 1)[0]
    return ""


def _ini_block(text: str, sec: str) -> str:
    i = text.find(f"[{sec}]")
    if i < 0:
        return ""
    j = text.find("\n[", i + 1)
    return text[i: j if j > 0 else len(text)]


# ----------------------------------------------------------------------------- semantics
def _strip_optional(m: str) -> str:
    return m.strip().strip("()").strip()


def layer_levels(contract: Contract) -> list[list[str]]:
    containers = _as_list(contract.fields.get("containers"))
    levels: list[list[str]] = []
    for raw in _as_list(contract.fields.get("layers")):
        siblings = [_strip_optional(x) for x in raw.split("|") if x.strip()]
        if containers:
            siblings = [f"{c}.{s}" for c in containers for s in siblings]
        levels.append(siblings)
    return levels


def contract_pairs(contract: Contract) -> tuple[list[tuple[str, str]], list[str]]:
    """The (importer-module, forbidden-module) pairs a contract prohibits + mentioned modules."""
    t = contract.type
    pairs: list[tuple[str, str]] = []
    mods: list[str] = []
    if t == "forbidden":
        src, forb = _as_list(contract.fields.get("source_modules")), _as_list(contract.fields.get("forbidden_modules"))
        pairs = [(s, f) for s in src for f in forb]
        mods = src + forb
    elif t == "independence":
        ms = _as_list(contract.fields.get("modules"))
        pairs = [(a, b) for a, b in itertools.permutations(ms, 2)]
        mods = ms
    elif t == "layers":
        levels = layer_levels(contract)
        for i, high in enumerate(levels):
            for low in levels[i + 1:]:
                pairs += [(l, h) for l in low for h in high]  # lower must not import higher
        for lvl in levels:  # siblings are independent of each other
            pairs += [(a, b) for a, b in itertools.permutations(lvl, 2)]
        mods = [m for lvl in levels for m in lvl]
    return pairs, mods


def _within(a: str, b: str) -> bool:
    return a == b or a.startswith(b + ".")


def build_architecture(contracts: list[Contract], root_package: str, name: str) -> tuple[dict, dict]:
    """Return (rules.yaml dict, report dict)."""
    skipped = sorted({c.type for c in contracts if c.type not in SUPPORTED})
    used = [c for c in contracts if c.type in SUPPORTED]
    all_pairs: list[tuple[str, str, str]] = []
    modules: set[str] = set()
    for c in used:
        pairs, mods = contract_pairs(c)
        modules.update(mods)
        all_pairs += [(s, f, c.name) for s, f in pairs]
    mapping = {m.replace(".", "/"): {"type": m} for m in sorted(modules)}
    rules: list[dict] = []
    seen: dict[tuple[str, str], dict] = {}
    for s, f, cname in all_pairs:
        for a in (m for m in modules if _within(m, s)):
            for b in (m for m in modules if _within(m, f)):
                if a == b:
                    continue
                key = (a, b)
                if key in seen:
                    if cname not in seen[key]["_contracts"]:
                        seen[key]["_contracts"].append(cname)
                    continue
                rule = {"id": f"R{len(rules) + 1:03d}", "name": f"{a} -/-> {b}", "source": a, "target": b,
                        "relation": "forbidden", "_contracts": [cname]}
                seen[key] = rule
                rules.append(rule)
    for r in rules:
        r["description"] = "import-linter: " + "; ".join(r.pop("_contracts"))
    arch = {"architecture": {"name": f"{name} (import-linter contracts)"}, "import_resolution": "anchored",
            "component_mapping": mapping, "rules": rules}
    report = {"contracts_total": len(contracts), "contracts_used": len(used), "skipped_types": skipped,
              "modules": len(modules), "rules": len(rules)}
    return arch, report


def tolerated_list(contracts: list[Contract]) -> list[dict]:
    out = []
    for c in contracts:
        for t in c.tolerated:
            out.append({**t, "contract": c.name})
    return out


def write_outputs(arch: dict, tolerated: list[dict], out_dir: str) -> tuple[str, str]:
    import json
    os.makedirs(out_dir, exist_ok=True)
    rp, tp = os.path.join(out_dir, "rules.yaml"), os.path.join(out_dir, "tolerated.json")
    with open(rp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(arch, fh, sort_keys=False, width=120)
    with open(tp, "w", encoding="utf-8") as fh:
        json.dump(tolerated, fh, indent=2)
    return rp, tp


# ----------------------------------------------------------------------------- retrospective use
def prune_contracts(contracts: list[Contract], present: "callable") -> list[Contract]:
    """Restrict contracts to modules that exist at some older commit, so that today's
    intent can be applied to the past without referring to modules that did not exist yet."""
    out: list[Contract] = []
    for c in contracts:
        f = dict(c.fields)
        if c.type == "forbidden":
            src = [m for m in _as_list(f.get("source_modules")) if present(m)]
            forb = [m for m in _as_list(f.get("forbidden_modules")) if present(m)]
            if not src or not forb:
                continue
            f["source_modules"], f["forbidden_modules"] = src, forb
        elif c.type == "independence":
            ms = [m for m in _as_list(f.get("modules")) if present(m)]
            if len(ms) < 2:
                continue
            f["modules"] = ms
        elif c.type == "layers":
            # With `containers`, layer names are RELATIVE ("web" means "<container>.web"), so
            # existence must be tested on the qualified name. A layer found in only some of the
            # containers is kept but marked optional "(web)", which import-linter accepts; testing
            # the bare name would drop every containers-based contract at old commits.
            containers = _as_list(f.get("containers"))

            def exists(name: str) -> bool:
                return any(present(f"{k}.{name}") for k in containers) if containers else present(name)

            def exists_everywhere(name: str) -> bool:
                return all(present(f"{k}.{name}") for k in containers) if containers else True

            lv = []
            for raw in _as_list(f.get("layers")):
                keep = []
                for x in raw.split("|"):
                    name = _strip_optional(x)
                    if name and exists(name):
                        keep.append(x.strip() if exists_everywhere(name) else f"({name})")
                if keep:
                    lv.append(" | ".join(keep))
            if len(lv) < 2:
                continue
            f["layers"] = lv
        else:
            continue
        tol = [t for t in c.tolerated if present(t["importer"]) and present(t["imported"])]
        f["ignore_imports"] = [f"{t['importer']} -> {t['imported']}" for t in tol]
        out.append(Contract(name=c.name, type=c.type, fields=f, tolerated=tol))
    return out


def to_ini(opts: dict, contracts: list[Contract]) -> str:
    """Serialise contracts as an .importlinter file the reference tool can run."""
    lines = ["[importlinter]", f"root_package = {opts.get('root_package') or opts.get('root_packages')}",
             ""]
    for i, c in enumerate(contracts, 1):
        # per-contract option: at old commits some documented exceptions do not exist yet
        lines += [f"[importlinter:contract:{i}]", f"name = {c.name}", f"type = {c.type}",
                  "unmatched_ignore_imports_alerting = none"]
        for k, v in c.fields.items():
            vals = _as_list(v) if not isinstance(v, (bool, int)) else [str(v)]
            if not vals:
                continue
            lines.append(f"{k} = " + ("" if len(vals) > 1 else vals[0]))
            if len(vals) > 1:
                lines += [f"    {x}" for x in vals]
        lines.append("")
    return "\n".join(lines)
