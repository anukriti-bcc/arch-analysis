import json

import httpx
import pytest

from analysis.semantic.llm_client import (
    CachingClient, FunctionClient, LLMResponse, OpenAICompatibleClient, client_from_env,
)


def ok_body(content="hi", usage=True, model="m1"):
    body = {"choices": [{"message": {"content": content}}], "model": model}
    if usage:
        body["usage"] = {"prompt_tokens": 11, "completion_tokens": 5}
    return body


def make(handler, **kw):
    sleeps = []
    client = OpenAICompatibleClient(
        "http://x/v1", "m1", "KEY", transport=httpx.MockTransport(handler),
        sleep=sleeps.append, **kw,
    )
    return client, sleeps


def test_success_reports_tokens_and_latency():
    c, _ = make(lambda r: httpx.Response(200, json=ok_body()))
    r = c.complete("sys", "prompt")
    assert r.ok and r.text == "hi" and (r.input_tokens, r.output_tokens) == (11, 5)
    assert r.latency_s >= 0 and r.cached is False and r.tokens_estimated is False and r.attempts == 1


def test_sends_auth_header_and_json_mode_and_temperature():
    seen = {}
    def h(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok_body())
    c, _ = make(h)
    c.complete("S", "P", temperature=0.0, max_tokens=123)
    assert seen["auth"] == "Bearer KEY"
    assert seen["body"]["temperature"] == 0.0 and seen["body"]["max_tokens"] == 123
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


def test_missing_usage_is_estimated_and_flagged():
    c, _ = make(lambda r: httpx.Response(200, json=ok_body(usage=False)))
    r = c.complete("sys", "prompt")
    assert r.tokens_estimated is True and r.input_tokens > 0 and r.output_tokens > 0


def test_retries_on_429_honouring_retry_after_then_succeeds():
    calls = []
    def h(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "7"}) if len(calls) == 1 else httpx.Response(200, json=ok_body())
    c, sleeps = make(h)
    r = c.complete("s", "p")
    assert r.ok and r.attempts == 2 and sleeps == [7.0]


def test_exponential_backoff_without_retry_after():
    seq = iter([500, 503, 200])
    def h(request):
        code = next(seq)
        return httpx.Response(code, json=ok_body()) if code == 200 else httpx.Response(code)
    c, sleeps = make(h, backoff_s=1.0)
    assert c.complete("s", "p").ok
    assert sleeps == [1.0, 2.0]


def test_gives_up_and_records_failure_instead_of_raising():
    c, sleeps = make(lambda r: httpx.Response(503, text="overloaded"), max_retries=2)
    r = c.complete("s", "p")
    assert not r.ok and "503" in r.error and r.attempts == 3 and len(sleeps) == 2


def test_client_error_is_not_retried():
    n = []
    def h(request):
        n.append(1)
        return httpx.Response(401, text="bad key")
    c, sleeps = make(h)
    r = c.complete("s", "p")
    assert not r.ok and "401" in r.error and len(n) == 1 and sleeps == []


def test_400_triggers_one_retry_without_json_mode():
    bodies = []
    def h(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(400, text="response_format unsupported") if "response_format" in bodies[-1] else httpx.Response(200, json=ok_body())
    c, _ = make(h)
    assert c.complete("s", "p").ok
    assert "response_format" in bodies[0] and "response_format" not in bodies[1]


def test_malformed_body_is_an_error():
    c, _ = make(lambda r: httpx.Response(200, json={"unexpected": True}))
    r = c.complete("s", "p")
    assert not r.ok and "malformed" in r.error


def test_network_error_is_retried_then_reported():
    def h(request):
        raise httpx.ConnectError("refused")
    c, _ = make(h, max_retries=1)
    r = c.complete("s", "p")
    assert not r.ok and "ConnectError" in r.error


def test_cache_hit_returns_original_cost_and_cached_flag(tmp_path):
    stub = FunctionClient(lambda s, p: "answer")
    c = CachingClient(stub, str(tmp_path / "c.sqlite"))
    first = c.complete("S", "P")
    second = c.complete("S", "P")
    assert stub.calls == 1 and (c.hits, c.misses) == (1, 1)
    assert first.cached is False and second.cached is True
    assert (second.input_tokens, second.output_tokens, second.latency_s) == (first.input_tokens, first.output_tokens, first.latency_s)


def test_cache_key_depends_on_prompt_and_temperature(tmp_path):
    stub = FunctionClient(lambda s, p: p)
    c = CachingClient(stub, str(tmp_path / "c.sqlite"))
    c.complete("S", "P1"); c.complete("S", "P2"); c.complete("S", "P1", temperature=0.5)
    assert stub.calls == 3


def test_failures_are_never_cached(tmp_path):
    def boom(s, p):
        raise RuntimeError("provider down")
    stub = FunctionClient(boom)
    c = CachingClient(stub, str(tmp_path / "c.sqlite"))
    assert not c.complete("S", "P").ok and not c.complete("S", "P").ok
    assert stub.calls == 2


def test_cache_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.sqlite")
    CachingClient(FunctionClient(lambda s, p: "v"), path).complete("S", "P")
    stub2 = FunctionClient(lambda s, p: "other")
    r = CachingClient(stub2, path).complete("S", "P")
    assert r.text == "v" and stub2.calls == 0


def test_function_client_turns_exceptions_into_error_responses():
    r = FunctionClient(lambda s, p: 1 / 0).complete("s", "p")
    assert not r.ok and "ZeroDivisionError" in r.error


def test_client_from_env(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert client_from_env() is None
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen")
    assert client_from_env().model == "qwen"
