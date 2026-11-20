"""Storage selection: PostgreSQL when DATABASE_URL is set, otherwise memory (the default, which needs nothing installed).

`store` is a lazy proxy so that importing the API never opens a database connection; the real store is created on first use, and
`describe()` reports which backend is in use (shown by /health)."""
from __future__ import annotations

import os
import threading


def create_store():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        from storage.postgres_store import PostgresStore
        return PostgresStore(url)
    from storage.memory_store import _MemoryStore
    return _MemoryStore()


class _LazyStore:
    def __init__(self) -> None:
        self._real = None
        self._lock = threading.Lock()

    def _get(self):
        if self._real is None:
            with self._lock:
                if self._real is None:
                    self._real = create_store()
        return self._real

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def reset(self, real=None) -> None:
        """Forget the current store (tests, or switching backend); the next use creates a fresh one, or uses `real`."""
        with self._lock:
            self._real = real

    def describe(self) -> dict:
        s = self._get()
        try:
            ok = s.ping()
        except Exception as e:  # database down: report it instead of crashing the health check
            return {"backend": s.backend, "ok": False, "error": type(e).__name__}
        return {"backend": s.backend, "ok": ok}


store = _LazyStore()
