"""Provider-agnostic LLM access.

Design goals, driven by the evaluation (not by convenience):

1. Provider-agnostic. Anything that speaks the de-facto "OpenAI chat
   completions" HTTP API works: Ollama (http://localhost:11434/v1), Google's
   OpenAI-compatibility endpoint for Gemini, OpenRouter, OpenAI itself, vLLM,
   LM Studio ... Choosing a model is therefore configuration, not code.
2. Every response carries what the efficiency analysis needs: input/output
   tokens, latency, and whether it came from the cache.
3. Failures are DATA. `complete()` never raises: it returns an LLMResponse
   with `error` set. The experiment layer counts these separately instead of
   quietly converting them into verdicts (which would corrupt precision/recall).
4. Reproducible and cheap to re-run: CachingClient stores successful
   responses keyed by (model, temperature, prompts). A cache hit still reports
   the *original* tokens and latency, so a re-run measures the same cost
   without paying for it again.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

import httpx


@dataclass
class LLMResponse:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    model: str = ""
    cached: bool = False
    error: Optional[str] = None
    attempts: int = 1
    tokens_estimated: bool = False  # True when the server did not report usage

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return asdict(self)


class LLMClient(ABC):
    model: str = ""

    @abstractmethod
    def complete(
        self, system: str, prompt: str, *, temperature: float = 0.0, max_tokens: int = 600
    ) -> LLMResponse: ...


def _estimate_tokens(text: str) -> int:
    # Rough (~4 characters per token). Only used when a server omits `usage`;
    # such responses are flagged `tokens_estimated=True` and should be reported as such.
    return max(1, len(text) // 4)


class OpenAICompatibleClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        timeout: float = 120.0,
        max_retries: int = 3,
        backoff_s: float = 2.0,
        json_mode: bool = True,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.json_mode = json_mode
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def complete(self, system, prompt, *, temperature=0.0, max_tokens=600) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        use_json_mode = self.json_mode
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 2):
            started = time.perf_counter()
            try:
                resp = self._http.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._backoff(attempt, None)
                continue
            elapsed = time.perf_counter() - started

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"] or ""
                except (ValueError, KeyError, IndexError, TypeError):
                    return LLMResponse(model=self.model, error="malformed response body", attempts=attempt)
                usage = data.get("usage") or {}
                in_tok, out_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
                estimated = in_tok is None or out_tok is None
                if estimated:
                    in_tok = _estimate_tokens(system + prompt)
                    out_tok = _estimate_tokens(text)
                return LLMResponse(
                    text=text, input_tokens=int(in_tok), output_tokens=int(out_tok),
                    latency_s=elapsed, model=data.get("model") or self.model,
                    attempts=attempt, tokens_estimated=estimated,
                )

            body = resp.text[:300].replace("\n", " ")
            last_error = f"HTTP {resp.status_code}: {body}"
            if resp.status_code == 400 and use_json_mode:
                # Some servers reject response_format; retry once without it.
                use_json_mode = False
                payload.pop("response_format", None)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            return LLMResponse(model=self.model, error=last_error, attempts=attempt)  # 4xx: not retryable

        return LLMResponse(model=self.model, error=f"gave up after {self.max_retries + 1} attempts: {last_error}", attempts=self.max_retries + 1)

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if attempt > self.max_retries:
            return
        try:
            delay = float(retry_after) if retry_after else self.backoff_s * (2 ** (attempt - 1))
        except ValueError:
            delay = self.backoff_s * (2 ** (attempt - 1))
        self._sleep(min(delay, 60.0))


class CachingClient(LLMClient):
    """Wraps any client with an on-disk response cache (SQLite)."""

    def __init__(self, inner: LLMClient, cache_path: str):
        self.inner = inner
        self.model = inner.model
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)) or ".", exist_ok=True)
        self._db = sqlite3.connect(cache_path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, response TEXT NOT NULL)")
        self._db.commit()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def _key(self, system: str, prompt: str, temperature: float, max_tokens: int) -> str:
        blob = json.dumps([self.inner.model, temperature, max_tokens, system, prompt], ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def complete(self, system, prompt, *, temperature=0.0, max_tokens=600) -> LLMResponse:
        key = self._key(system, prompt, temperature, max_tokens)
        with self._lock:
            row = self._db.execute("SELECT response FROM cache WHERE key=?", (key,)).fetchone()
        if row:
            self.hits += 1
            data = json.loads(row[0])
            data["cached"] = True
            return LLMResponse(**data)
        self.misses += 1
        resp = self.inner.complete(system, prompt, temperature=temperature, max_tokens=max_tokens)
        if resp.ok:  # never cache failures
            with self._lock:
                self._db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (key, json.dumps(resp.to_dict())))
                self._db.commit()
        return resp


class FunctionClient(LLMClient):
    """Adapter that turns a plain function into a client (tests, smoke runs).
    The function receives (system, prompt) and returns the model's text."""

    def __init__(self, fn: Callable[[str, str], str], model: str = "function-stub"):
        self.fn = fn
        self.model = model
        self.calls = 0

    def complete(self, system, prompt, *, temperature=0.0, max_tokens=600) -> LLMResponse:
        self.calls += 1
        started = time.perf_counter()
        try:
            text = self.fn(system, prompt)
        except Exception as exc:  # a stub raising simulates a provider failure
            return LLMResponse(model=self.model, error=f"{type(exc).__name__}: {exc}")
        return LLMResponse(
            text=text, input_tokens=_estimate_tokens(system + prompt), output_tokens=_estimate_tokens(text),
            latency_s=time.perf_counter() - started, model=self.model, tokens_estimated=True,
        )


def client_from_env() -> LLMClient | None:
    """Build a client from LLM_BASE_URL / LLM_MODEL / LLM_API_KEY, or None.

    Examples:
      Ollama : LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=qwen2.5:7b-instruct
      Gemini : LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
               LLM_MODEL=<a model your key can use>  LLM_API_KEY=...
    """
    base, model = os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_MODEL")
    if not base or not model:
        return None
    client: LLMClient = OpenAICompatibleClient(base, model, os.environ.get("LLM_API_KEY"))
    cache = os.environ.get("LLM_CACHE_PATH")
    return CachingClient(client, cache) if cache else client
