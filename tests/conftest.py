"""Tests never spend credits or quota: real model calls fail the test, and nothing reaches YouTube."""

import litellm
import pytest
from agents import set_tracing_disabled

set_tracing_disabled(True)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    calls = []

    async def blocked(*args, **kwargs):
        calls.append(kwargs.get("model"))
        raise RuntimeError("Tests must not call a real model.")

    monkeypatch.setattr(litellm, "acompletion", blocked)
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("CACHE_DIR", "")
    monkeypatch.setenv("LOG_FILE", "")
    monkeypatch.setenv("SENTIMENT_BACKEND", "vader")  # fast; the transformer is checked by hand
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-unused")
    yield calls
    assert not calls, f"A test called a real model: {calls}"
