"""The frontend tests run against JSON fixtures exported from this backend.
If an endpoint's response shape changes, the fixtures go stale and the UI tests
would keep passing against a fiction. This test fails instead, and tells you to
re-run scripts/export_frontend_fixtures.py."""
import json
import os

import pytest

from scripts.export_frontend_fixtures import export

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "__fixtures__")


def key_shape(obj):
    """Recursive set of key names; lists are merged across their elements."""
    if isinstance(obj, dict):
        return {k: key_shape(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        merged: dict = {}
        for item in obj:
            s = key_shape(item)
            if isinstance(s, dict):
                for k, v in s.items():
                    merged[k] = v if k not in merged or not isinstance(merged[k], dict) else {**merged[k], **(v if isinstance(v, dict) else {})}
        return [merged] if merged else []
    return None


def test_committed_fixtures_match_live_api_shapes(tmp_path):
    export(str(tmp_path))
    names = sorted(f for f in os.listdir(tmp_path) if f.endswith(".json"))
    assert names, "export produced nothing"
    stale = []
    for name in names:
        committed_path = os.path.join(FIXTURES, name)
        assert os.path.exists(committed_path), f"missing committed fixture {name}"
        live = json.load(open(tmp_path / name))
        committed = json.load(open(committed_path))
        if key_shape(live) != key_shape(committed):
            stale.append(name)
    assert not stale, f"stale frontend fixtures {stale}: run `python scripts/export_frontend_fixtures.py`"
