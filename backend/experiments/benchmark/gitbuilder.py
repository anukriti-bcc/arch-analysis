"""Build small Git repositories with fully controlled history.

Used by the unit tests (to pin down exactly what the evolution analyzer must
find) and by the benchmark generator (so the ground truth about *when* a
dependency was introduced is known by construction, not guessed).

Commit timestamps are explicit, which makes generated repositories
reproducible: the same inputs give the same commit hashes.
"""
from __future__ import annotations

import os
import subprocess
from datetime import date, datetime, time, timezone


def _as_datetime(d: date | datetime) -> datetime:
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc)


class GitBuilder:
    def __init__(self, path: str, default_author: str = "dev"):
        self.path = os.path.abspath(path)
        self.default_author = default_author
        os.makedirs(self.path, exist_ok=True)
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "bench@example.invalid")
        self._git("config", "user.name", default_author)
        self._git("config", "commit.gpgsign", "false")

    def _git(self, *args: str, env: dict | None = None) -> str:
        proc = subprocess.run(
            ["git", "-C", self.path, *args],
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout

    def write(self, relative_path: str, content: str) -> None:
        full = os.path.join(self.path, relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)

    def append(self, relative_path: str, content: str) -> None:
        full = os.path.join(self.path, relative_path)
        with open(full, "a", encoding="utf-8") as f:
            f.write(content)

    def read(self, relative_path: str) -> str:
        with open(os.path.join(self.path, relative_path), encoding="utf-8") as f:
            return f.read()

    def remove(self, relative_path: str) -> None:
        os.remove(os.path.join(self.path, relative_path))

    def commit(self, message: str, when: date | datetime, author: str | None = None) -> str:
        stamp = _as_datetime(when).isoformat()
        who = author or self.default_author
        env = {
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
            "GIT_AUTHOR_NAME": who,
            "GIT_COMMITTER_NAME": who,
            "GIT_AUTHOR_EMAIL": "bench@example.invalid",
            "GIT_COMMITTER_EMAIL": "bench@example.invalid",
        }
        self._git("add", "-A", env=env)
        self._git("commit", "-q", "--allow-empty", "-m", message, env=env)
        return self._git("rev-parse", "HEAD").strip()
