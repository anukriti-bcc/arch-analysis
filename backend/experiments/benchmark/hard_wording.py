"""HARD wording tier: ADRs whose meaning is harder to read by rule.

Why this tier exists
--------------------
In the primary wording a code-only reader (M6) resolves every targeted case, so that benchmark cannot show
where an LLM is needed. This tier keeps the SAME repositories, scenarios and ground-truth labels and changes
how the decision record is written, plus two scenarios that exist only here. Every phenomenon below is a way
real ADRs vary; none is invented to target a particular regex.

  phenomenon                                        scenarios
  ------------------------------------------------- ---------
  a rejected ALTERNATIVE inside a permitting ADR    B, F
  scope given by description, not by file names     B
  permission worded outside any keyword list         J
  a date cut-off introduced by an unusual phrase     C, D
  a negated PROPOSAL ("was not approved")            E
  a permission about something else in the same ADR  G
  one ADR deciding for two modules (mixed)           L, M   (hard tier only)

Ground truth is unchanged by construction: the label of each case depends only on what the decision says,
not on how it is phrased.

Provenance (state this in the report): written after the deterministic reader M6 (analysis/intent/reader.py)
was frozen. Phenomena were chosen from general ADR variation, but the author knew M6's lexicon, so results on
this tier are exploratory evidence about code-versus-LLM readability, not a blind test. The held-out wording
remains the blind test.

Pure functions: they take the same context `_adr_content` takes and return the same tuple
(title, status, context, decision, consequences), or None to mean "use the primary wording for this scenario".
"""
from __future__ import annotations

import random
from datetime import date

# Scenarios that exist only in the hard tier: (label, number of cases).
HARD_ONLY_SCENARIOS: dict[str, tuple[str, int]] = {
    "L_adr_mixed_permits_target": ("justified", 6),
    "M_adr_mixed_prohibits_target": ("violation", 6),
}

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _written_date(d: date, wr: random.Random) -> str:
    style = wr.randint(0, 2)
    if style == 0:
        return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
    if style == 1:
        return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"
    return f"{_ordinal(d.day)} of {_MONTHS[d.month - 1]} {d.year}"


_SOFT_NOS = [
    "Access continues to go through the proper layer.",
    "The performance concern will be handled inside the proper layer.",
    "Storage access stays behind the proper layer for now.",
]


def adr_content_hard(scenario: str, wr: random.Random, f: dict, pair, other: str, cutoff: date | None, number: int,
                     reason: str):
    SF, TF, S, T, R = f["src_stem"], f["tgt_stem"], f["src_desc"], f["tgt_desc"], pair.rule_id
    reason = reason.rstrip(".")

    if scenario in ("B_adr_permanent_exception", "F_adr_superseded"):
        status = "Accepted" if scenario.startswith("B") else f"Superseded by ADR-{number + 20:03d}"
        if wr.randint(0, 1) == 0 and scenario.startswith("B"):
            # scope by DESCRIPTION: neither module is named by its file name
            title = "Accepted trade-off on storage reads"
            context = f"{reason.capitalize()}."
            decision = (f"The team accepts that {S} reads from {T} directly. We chose this over adding a new "
                        f"abstraction, and revisit it only if the storage approach changes.")
            return title, status, context, decision, "The layering rule is knowingly bent in this one place."
        # names the modules, and quotes a REJECTED ALTERNATIVE inside a permitting decision
        title = f"Direct reads in {SF}"
        context = (f"{reason.capitalize()}. Two options were considered: routing the call through the proper layer, "
                   f"or reading from {T} directly.")
        decision = (f"We rejected routing through the proper layer, because it cannot meet the need. `{SF}` will "
                    f"therefore read from `{TF}` directly, and we consider the resulting layering breach an acceptable cost.")
        return title, status, context, decision, "Nothing else is affected."

    if scenario in ("C_adr_grandfathered_before_cutoff", "D_adr_grandfathered_after_cutoff"):
        title = f"Tolerate direct access from {SF} during the migration"
        context = f"Rule {R} forbids this access, but {reason}, and the proper layer will not be ready for some time."
        decision = (f"While the layer migration is under way, `{SF}` may keep reading from `{TF}` directly. The tolerance "
                    f"covers code merged up to the freeze on {_written_date(cutoff, wr)}; anything merged after the "
                    f"freeze has to go through the proper layer.")
        return title, "Accepted", context, decision, "The tolerated access is removed when the migration finishes."

    if scenario == "E_adr_reaffirms_prohibition":
        title = f"Proposal: direct access from {SF} to {TF}"
        context = f"A proposal was raised because {reason}."
        decision = f"The proposal to allow `{SF}` to use `{TF}` directly was not approved. {wr.choice(_SOFT_NOS)}"
        return title, "Accepted", context, decision, "The proposal can be raised again if circumstances change."

    if scenario == "G_adr_passing_mention":
        title = "Cache hot lookups"
        context = "Several read paths are slow under load."
        decision = (f"`{SF}` reads `{TF}` lookup results only through the new cache wrapper, never directly, with a 60 "
                    f"second TTL and invalidation on writes. Serving results up to 60 seconds stale is acceptable.")
        return title, "Accepted", context, decision, "The cache wrapper is covered by its own tests."

    if scenario == "J_adr_cited_by_commit_only":
        title = f"{f['src_abs'].capitalize()} and storage"
        context = f"{reason.capitalize()}."
        decision = (f"{f['src_abs'].capitalize()} is cleared to query {f['tgt_abs']} directly for this purpose, and we "
                    f"are comfortable with the resulting coupling. No other code is covered by this decision.")
        return title, "Accepted", context, decision, "Revisit if the data-access approach changes."

    if scenario in HARD_ONLY_SCENARIOS:
        OF = f"{other}_{pair.src_type}"
        permitted, forbidden = (SF, OF) if scenario.startswith("L") else (OF, SF)
        title = f"Direct access to {TF}"
        context = f"{reason.capitalize()}, but only some modules are affected."
        decision = (f"`{permitted}` may use `{TF}` directly because {reason}. "
                    f"`{forbidden}` must keep going through the proper layer.")
        return title, "Accepted", context, decision, f"Rule {R} still applies to every module not named here."

    return None  # A, H have no principal ADR; K keeps its primary wording as a control
