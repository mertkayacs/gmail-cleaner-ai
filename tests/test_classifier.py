"""Tests for lib/classifier.py: retry behavior, JSON extraction tolerance."""

from unittest.mock import MagicMock

import pytest

from lib import classifier as classifier_mod


class _FakeCompletionResponse:
    def __init__(self, content):
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        self.choices = [choice]


def _make_classifier(completion_fn):
    """Build a Classifier with an injected completion callable."""
    c = classifier_mod.Classifier.__new__(classifier_mod.Classifier)
    c._completion = completion_fn
    c.model = "test-model"
    c.api_base = None
    return c


def test_classify_batch_retries_on_transient_error(monkeypatch):
    monkeypatch.setattr(classifier_mod.time, "sleep", lambda *_a: None)

    calls = {"n": 0}

    def flaky_completion(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient 429")
        return _FakeCompletionResponse('{"foo@bar.com": {"category": "keep_other"}}')

    c = _make_classifier(flaky_completion)
    out = c.classify_batch("prompt")
    assert calls["n"] == 3
    assert out == {"foo@bar.com": {"category": "keep_other"}}


def test_classify_batch_raises_after_max_attempts(monkeypatch):
    monkeypatch.setattr(classifier_mod.time, "sleep", lambda *_a: None)

    def always_fail(**kwargs):
        raise RuntimeError("persistent failure")

    c = _make_classifier(always_fail)
    with pytest.raises(RuntimeError, match="persistent failure"):
        c.classify_batch("prompt")


def test_extract_json_tolerates_fences():
    raw = "```json\n{\"a\": 1}\n```"
    assert classifier_mod._extract_json(raw) == {"a": 1}

    raw2 = 'Here is the JSON: {"a": 2} done.'
    assert classifier_mod._extract_json(raw2) == {"a": 2}
