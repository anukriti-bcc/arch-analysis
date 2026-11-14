"""GitEvolutionAnalyzer — mines *when* and *how* a dependency came to exist.

Question answered for one Finding (source file S depends on target file T):

    At which commit did S first come to depend on T, has that dependency been
    continuously present since, and what does the surrounding history say?

Method (deliberately simple and checkable):
  1. List every commit that touched S or T, oldest first.
  2. At each of those commits, reconstruct the file list of the repository
     (`git ls-tree`) and the content of S (`git show`), parse S with the same
     Tree-sitter parser used on the working tree, and resolve its imports with
     the same `resolve_import_all` the scanner uses. The dependency is "present" at
     that commit iff some import of S resolves to T.
  3. Walk the present/absent sequence. The *introducing commit* is the start of
     the continuous run of "present" states that reaches HEAD.

Why not just report the latest commit touching the file (what a naive
`git log -1 -- file` gives)? Because the latest commit to touch a file is
usually an unrelated edit made long after the dependency appeared; the
question of interest is when the *dependency* appeared. tests/test_git_evolution.py
contains exactly that counter-example.

Known limitations (surfaced in the evidence, not hidden):
  * File renames: S/T are tracked by their current paths. If either was
    renamed, pre-rename history shows the dependency as absent, so the
    introducing commit can be the rename commit. `rename_history_detected`
    flags when `git log --follow` disagrees with plain `git log`.
  * Import resolution at old commits uses that commit's own file list, so a
    dependency on a file that did not yet exist is (correctly) absent.
  * Only commits touching S or T are inspected (a dependency can't appear or
    vanish otherwise, apart from module-name ambiguity changes that
    ModuleIndex's suffix matching can in principle cause).
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from analysis.dependency.module_index import ModuleIndex
from analysis.dependency.repository_scanner import resolve_import_all
from analysis.evolution.base import EvolutionAnalyzer
from analysis.intent.adr import extract_adr_references
from analysis.parser.registry import get_parser_for_file

_TEMPORARY_WORDS = re.compile(
    r"\b(temp|temporary|temporarily|workaround|hotfix|quick[- ]?fix|hack|for now|stop-?gap|interim|short[- ]term)\b",
    re.IGNORECASE,
)
_MIGRATION_WORDS = re.compile(
    r"\b(migrat\w*|transition\w*|legacy|deprecat\w*|phase[- ]?out)\b", re.IGNORECASE
)
_ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")

_RS, _US = "\x1e", "\x1f"


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    author: str
    date: datetime
    subject: str
    body: str

    @property
    def message(self) -> str:
        return (self.subject + ("\n" + self.body if self.body.strip() else "")).strip()

    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "short": self.sha[:8],
            "author": self.author,
            "date": self.date.isoformat(),
            "subject": self.subject,
        }


class GitRepo:
    """Thin, dependency-free wrapper over the `git` command line."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._prefix: str | None = None

    @property
    def prefix(self) -> str:
        """Path of the analysis root *inside* the git repository ("" when the
        analysis root is the repository root, e.g. "projects/shop/" when it is a
        subdirectory). `git show <sha>:<path>` and `git ls-tree` resolve paths
        from the repository root, while every path in this project is relative
        to the analysis root, so lookups must translate between the two."""
        if self._prefix is None:
            self._prefix = self.run("rev-parse", "--show-prefix", check=False).strip()
        return self._prefix

    def run(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", "-C", self.path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    def is_repo(self) -> bool:
        proc = subprocess.run(
            ["git", "-C", self.path, "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "true"

    def head(self) -> str | None:
        out = self.run("rev-parse", "--verify", "HEAD", check=False).strip()
        return out or None

    def commit_info(self, sha: str) -> CommitInfo:
        out = self.run("show", "-s", f"--format=%H{_US}%an{_US}%aI{_US}%s{_US}%b", sha)
        return _parse_commit(out.strip("\n"))

    def commits_touching(self, *paths: str) -> list[CommitInfo]:
        """Commits touching any of `paths`, oldest first (topological order)."""
        out = self.run(
            "log", "--topo-order", "--reverse",
            f"--format={_RS}%H{_US}%an{_US}%aI{_US}%s{_US}%b", "--", *paths,
        )
        return [_parse_commit(rec) for rec in out.split(_RS) if rec.strip()]

    def files_at(self, sha: str) -> list[str]:
        """Files of the analysis root at `sha`, relative to the analysis root."""
        out = self.run("ls-tree", "-r", "--name-only", "--full-tree", sha)
        pre = self.prefix
        return [l[len(pre):] for l in out.split("\n") if l and l.startswith(pre)]

    def file_at(self, sha: str, path: str) -> bytes | None:
        proc = subprocess.run(
            ["git", "-C", self.path, "show", f"{sha}:{self.prefix}{path}"], capture_output=True
        )
        return proc.stdout if proc.returncode == 0 else None

    def count_between(self, older: str, newer: str) -> int:
        out = self.run("rev-list", "--count", f"{older}..{newer}", check=False).strip()
        return int(out) if out.isdigit() else 0

    def log_count(self, path: str, follow: bool) -> int:
        args = ["log", "--format=%H"]
        if follow:
            args.append("--follow")
        out = self.run(*args, "--", path, check=False)
        return len([l for l in out.split("\n") if l.strip()])


def _parse_commit(record: str) -> CommitInfo:
    sha, author, date, subject, body = (record.strip("\n").split(_US) + [""] * 5)[:5]
    return CommitInfo(sha=sha.strip(), author=author, date=datetime.fromisoformat(date), subject=subject, body=body)


class GitEvolutionAnalyzer(EvolutionAnalyzer):
    """See module docstring. One instance can analyse many findings of the
    same repository; per-commit parsing results are cached."""

    def __init__(self, max_commits: int = 1000, anchored_imports: bool = False):
        self.max_commits = max_commits
        # must match the scanner's ModuleIndex mode, or 'introduced when' answers a different question
        self.anchored_imports = anchored_imports
        self._files_cache: dict[tuple[str, str], list[str]] = {}
        self._deps_cache: dict[tuple[str, str, str], frozenset[str]] = {}

    # ------------------------------------------------------------- public

    def analyze(self, repository_path: str, finding: Any) -> dict | None:
        dep = getattr(getattr(finding, "structural_evidence", None), "dependency", None)
        if dep is None:
            return None
        return self.analyze_dependency(repository_path, dep.source, dep.target)

    def analyze_dependency(self, repository_path: str, source: str, target: str) -> dict:
        repo = GitRepo(repository_path)
        if not repo.is_repo():
            return {"available": False, "reason": "not a git repository"}
        head = repo.head()
        if head is None:
            return {"available": False, "reason": "repository has no commits"}

        commits = repo.commits_touching(source, target)
        truncated = len(commits) > self.max_commits
        if truncated:
            commits = commits[-self.max_commits :]
        if not commits:
            return {"available": False, "reason": "no commits touch the source or target file"}

        # present/absent at every relevant commit
        states = [(c, self._present_at(repo, c.sha, source, target)) for c in commits]

        # Transitions (absent->present = introduced / reintroduced; present->absent = removed)
        events: list[dict] = []
        prev = False
        for commit, present in states:
            if present and not prev:
                kind = "introduced" if not any(e["change"] != "removed" for e in events) else "reintroduced"
                events.append({**commit.to_dict(), "change": kind})
            elif prev and not present:
                events.append({**commit.to_dict(), "change": "removed"})
            prev = present

        present_at_head = bool(states and states[-1][1])
        head_info = repo.commit_info(head)
        base: dict[str, Any] = {
            "available": True,
            "source": source,
            "target": target,
            "snapshot_commit": head[:8],
            "snapshot_date": head_info.date.isoformat(),
            "commits_examined": len(states),
            "history_truncated": truncated,
            "present_at_head": present_at_head,
            "timeline": events,
            "rename_history_detected": (
                repo.log_count(source, follow=True) != repo.log_count(source, follow=False)
                or repo.log_count(target, follow=True) != repo.log_count(target, follow=False)
            ),
        }
        if not present_at_head:
            # Seen in the working tree but not in committed history (e.g. an
            # uncommitted edit). There is no introducing commit to report.
            return {**base, "introducing_commit": None, "reason": "dependency not present at HEAD"}

        # Start of the continuous run of presence that reaches HEAD.
        start = len(states) - 1
        while start > 0 and states[start - 1][1]:
            start -= 1
        intro, _ = states[start]
        first_ever = next(c for c, p in states if p)
        source_created_here = self._source_absent_before(repo, states, start, source)

        since = states[start + 1 :]
        intro_message = intro.message
        age_days = (head_info.date - intro.date).days
        referenced = extract_adr_references(intro_message)

        return {
            **base,
            "introducing_commit": {**intro.to_dict(), "message": intro_message},
            "introduced_at": intro.date.isoformat(),
            "age_days": max(age_days, 0),
            "introduced_with_file_creation": source_created_here,
            "reintroduced": first_ever.sha != intro.sha,
            "first_introduced_at": first_ever.date.isoformat(),
            "commits_since_introduction": repo.count_between(intro.sha, head),
            "relevant_commits_since_introduction": len(since),
            "authors_since_introduction": sorted({c.author for c, _ in since} | set()),
            "message_signals": {
                "temporary_language": sorted({m.group(0).lower() for m in _TEMPORARY_WORDS.finditer(intro_message)}),
                "migration_language": sorted({m.group(0).lower() for m in _MIGRATION_WORDS.finditer(intro_message)}),
                "issue_references": sorted({f"#{n}" for n in _ISSUE_REF.findall(intro_message)}),
                "adr_references": referenced,
            },
        }

    # ------------------------------------------------------------ helpers

    def _present_at(self, repo: GitRepo, sha: str, source: str, target: str) -> bool:
        return target in self._internal_targets(repo, sha, source)

    def _internal_targets(self, repo: GitRepo, sha: str, source: str) -> frozenset[str]:
        key = (repo.path, sha, source)
        if key in self._deps_cache:
            return self._deps_cache[key]

        files = self._files_cache.get((repo.path, sha))
        if files is None:
            files = repo.files_at(sha)
            self._files_cache[(repo.path, sha)] = files

        targets: set[str] = set()
        content = repo.file_at(sha, source) if source in set(files) else None
        parser = get_parser_for_file(source)
        if content is not None and parser is not None:
            index = ModuleIndex(strict=self.anchored_imports)
            for f in files:
                if get_parser_for_file(f) is not None:
                    index.add_file(f)
            tree = parser.parse(content)
            for raw in parser.extract_imports(tree, content):
                for resolved in resolve_import_all(source, raw, index):
                    if resolved != source:
                        targets.add(resolved)
        result = frozenset(targets)
        self._deps_cache[key] = result
        return result

    def _source_absent_before(self, repo: GitRepo, states, start: int, source: str) -> bool:
        """True when the introducing commit is also the one that created the
        source file (i.e. the file was born with this dependency)."""
        commit = states[start][0]
        parents = repo.run("rev-list", "--parents", "-n", "1", commit.sha).split()[1:]
        if not parents:
            return True
        return repo.file_at(parents[0], source) is None
