"""Give the demo repository (datasets/sample-ecommerce) a git history of its own.

Why this exists
---------------
datasets/sample-ecommerce is only a subfolder of this project's repository, so
`git -C datasets/sample-ecommerce ...` walks up and uses the *project's*
history. The Evolution Evidence panel then shows the project's own commits,
which is correct but confusing for a demo.

This script builds a separate, standalone repository whose history tells the
story the sample code already describes: a clean layered app, then a
"temporary" hotfix that makes PaymentService.refund reach into the database
directly (the deliberate violation), then a few later commits that leave it
in place.

    cd backend
    python scripts/make_sample_history.py            # -> ../datasets/sample-ecommerce-history
    python scripts/make_sample_history.py --out /some/other/folder

Then point the UI at the new folder:
    Repository path:   ../datasets/sample-ecommerce-history
    Architecture file: ../datasets/sample-ecommerce/architecture/rules.yaml

Properties
----------
* Reproducible: commit dates and authors are fixed, so the same files give the
  same commit hashes every time.
* The final commit's tree is checked to be byte-identical to
  datasets/sample-ecommerce, so the two cannot drift apart silently.
* Re-running replaces the output folder.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

from experiments.benchmark.gitbuilder import GitBuilder  # noqa: E402

SAMPLE = os.path.join(REPO_ROOT, "datasets", "sample-ecommerce")
DEFAULT_OUT = os.path.join(REPO_ROOT, "datasets", "sample-ecommerce-history")

ALICE = "Alice Chen"
BEN = "Ben Okafor"
CAROL = "Carol Rossi"


def when(month: int, day: int, hour: int = 10) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


def read_sample(rel: str) -> str:
    with open(os.path.join(SAMPLE, rel), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
# Intermediate versions of the two files whose content changes over time.
# Everything else is committed exactly as it is in datasets/sample-ecommerce.
# --------------------------------------------------------------------------

USER_CONTROLLER_V1 = '''from backend.services.user_service import UserService


class UserController:
    def __init__(self):
        self.service = UserService()

    def get(self, user_id: int):
        return self.service.get_user(user_id)

    def register(self, user_data: dict):
        return self.service.register_user(user_data)
'''

PAYMENT_CONTROLLER_V1 = '''from backend.services.payment_service import PaymentService


class PaymentController:
    """Controller layer for payments — talks to PaymentService only."""

    def __init__(self):
        self.service = PaymentService()

    def charge(self, order_id: int, amount: float):
        return self.service.charge(order_id, amount)

    def get_transaction(self, order_id: int):
        return self.service.get_transaction(order_id)
'''

# v1: clean, goes through the repository only
PAYMENT_SERVICE_V1 = '''from backend.repositories.payment_repository import PaymentRepository


class PaymentService:
    """Service layer for payments."""

    def __init__(self):
        self.repository = PaymentRepository()

    def charge(self, order_id: int, amount: float):
        transaction = {"order_id": order_id, "amount": amount, "status": "charged"}
        return self.repository.save_transaction(transaction)

    def get_transaction(self, order_id: int):
        return self.repository.find_by_order_id(order_id)
'''

# v2: adds helpers (still clean)
PAYMENT_SERVICE_V2 = PAYMENT_SERVICE_V1 + '''
    def _validate_amount(self, amount: float) -> bool:
        return amount > 0

    def _build_receipt(self, transaction: dict) -> dict:
        return {
            "order_id": transaction.get("order_id"),
            "amount": transaction.get("amount"),
            "status": transaction.get("status"),
        }

    def _log_payment_event(self, event: str, order_id: int):
        # placeholder for future audit logging
        pass
'''

# v3: the hotfix. refund() reaches straight into the database layer.
PAYMENT_SERVICE_V3 = PAYMENT_SERVICE_V2 + '''
    def refund(self, order_id: int, amount: float):
        # TEMP (#142): PaymentRepository has no update method yet.
        from backend.database.connection import get_connection

        db = get_connection()
        return db.execute(
            "UPDATE transactions SET status = 'refunded' WHERE order_id = %s",
            (order_id,),
        )
'''
# v4 (final) is the file in datasets/sample-ecommerce, read at run time.


def build(out: str) -> None:
    if os.path.exists(out):
        # git object files are read-only on Windows; make them deletable
        def _writable(func, path, _exc):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        shutil.rmtree(out, onerror=_writable)

    g = GitBuilder(out, default_author=ALICE)

    # 1 ------------------------------------------------------------------
    g.write("backend/__init__.py", read_sample("backend/__init__.py"))
    g.write("backend/database/__init__.py", read_sample("backend/database/__init__.py"))
    g.write("backend/database/connection.py", read_sample("backend/database/connection.py"))
    for layer in ("repositories", "services", "controllers"):
        g.write(f"backend/{layer}/__init__.py", read_sample(f"backend/{layer}/__init__.py"))
    g.commit("Initial skeleton: layer packages and database connection", when(3, 2), ALICE)

    # 2 ------------------------------------------------------------------
    g.write("backend/repositories/user_repository.py", read_sample("backend/repositories/user_repository.py"))
    g.write("backend/services/user_service.py", read_sample("backend/services/user_service.py"))
    g.write("backend/controllers/user_controller.py", USER_CONTROLLER_V1)
    g.commit("Add user repository, service and controller", when(3, 9), ALICE)

    # 3 ------------------------------------------------------------------
    g.write("backend/repositories/payment_repository.py", read_sample("backend/repositories/payment_repository.py"))
    g.write("backend/services/payment_service.py", PAYMENT_SERVICE_V1)
    g.commit("Add payment repository and service (charge, lookup)", when(3, 23), BEN)

    # 4 ------------------------------------------------------------------
    g.write("backend/controllers/payment_controller.py", PAYMENT_CONTROLLER_V1)
    g.commit("Add payment controller", when(4, 6), BEN)

    # 5 ------------------------------------------------------------------
    g.write("architecture/rules.yaml", read_sample("architecture/rules.yaml"))
    g.commit("Add architecture/rules.yaml: layered architecture rules", when(4, 14), ALICE)

    # 6 ------------------------------------------------------------------
    g.write("backend/services/payment_service.py", PAYMENT_SERVICE_V2)
    g.commit("Add amount validation, receipt and audit-log helpers to PaymentService", when(5, 18), BEN)

    # 7  the introducing commit ------------------------------------------
    g.write("backend/services/payment_service.py", PAYMENT_SERVICE_V3)
    g.write("backend/controllers/payment_controller.py", read_sample("backend/controllers/payment_controller.py"))
    g.commit(
        "Hotfix: temporary refund path, write to DB directly for now (#142)\n"
        "\n"
        "Customers are waiting on refunds and PaymentRepository has no update\n"
        "method yet. Call the connection directly as a stop-gap; move it into\n"
        "the repository next sprint.",
        when(6, 11, 17),
        CAROL,
    )

    # 8  unrelated work that does not touch the payment files ------------
    g.write("backend/controllers/user_controller.py", read_sample("backend/controllers/user_controller.py"))
    g.commit("Document layering rule in UserController docstring", when(7, 6), ALICE)

    # 9  the violation is still there; the team only annotates it --------
    g.write("backend/services/payment_service.py", read_sample("backend/services/payment_service.py"))
    g.commit("Document the known refund shortcut in PaymentService", when(8, 17), ALICE)

    # ---- guard: the history must end exactly at the sample's content ----
    mismatches = _tree_differences(SAMPLE, out)
    if mismatches:
        raise SystemExit(
            "Generated repository differs from datasets/sample-ecommerce.\n"
            "The sample changed; update the intermediate versions in this script.\n  "
            + "\n  ".join(mismatches)
        )


def _tree_files(root: str) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            with open(full, "rb") as f:
                # ignore CRLF vs LF: Windows checkouts and git's autocrlf change line endings
                found[os.path.relpath(full, root).replace(os.sep, "/")] = f.read().replace(b"\r\n", b"\n")
    return found


def _tree_differences(a: str, b: str) -> list[str]:
    fa, fb = _tree_files(a), _tree_files(b)
    out = [f"only in sample: {p}" for p in sorted(fa.keys() - fb.keys())]
    out += [f"only in history: {p}" for p in sorted(fb.keys() - fa.keys())]
    out += [f"content differs: {p}" for p in sorted(fa.keys() & fb.keys()) if fa[p] != fb[p]]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT, help="where to create the repository")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    build(out)
    log = subprocess.run(
        ["git", "-C", out, "log", "--format=%h  %ad  %<(12,trunc)%an  %s", "--date=short"],
        capture_output=True,
        text=True,
    ).stdout
    print(f"Created {out}\n")
    print(log)
    rel = os.path.relpath(out, BACKEND).replace(os.sep, "/")
    print("In the UI use:")
    print(f"  Repository path:   {rel}")
    print("  Architecture file: ../datasets/sample-ecommerce/architecture/rules.yaml")


if __name__ == "__main__":
    main()
