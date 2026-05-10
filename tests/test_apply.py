"""Tests for cmd_apply: IMAP search semantics, error handling, log behavior."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import triage


@pytest.fixture
def fake_account(monkeypatch, tmp_path):
    """Stand up a fake account dir with one allowed and one disallowed sender."""
    acc = "test@gmail.com"
    acc_dir = tmp_path / acc
    acc_dir.mkdir()
    (acc_dir / "allowed.txt").write_text(
        "# header\nkeep@example.com | Newsletter/Tech | weekly digest\n"
    )
    (acc_dir / "disallowed.txt").write_text(
        "# header\nspam@example.com | Junk/Promo | promo bulk\n"
    )
    monkeypatch.setattr(triage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(triage, "load_account", lambda e: (acc, "fakepass"))
    return acc, acc_dir


def _mock_conn(search_uids=b""):
    conn = MagicMock()
    conn.select.return_value = ("OK", [b""])
    conn.uid.return_value = ("OK", [search_uids])
    conn.logout.return_value = ("BYE", [b""])
    return conn


def test_apply_search_uses_xgm_raw_exact_match(fake_account, monkeypatch):
    """Apply must use X-GM-RAW with from: token, not raw FROM substring."""
    acc, _ = fake_account
    conn = _mock_conn()
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)

    triage.cmd_apply(acc, dry_run=True)

    search_calls = [
        c for c in conn.uid.call_args_list
        if c.args and c.args[0] == "SEARCH"
    ]
    assert search_calls, "expected at least one SEARCH call"
    for call in search_calls:
        assert "X-GM-RAW" in call.args, (
            f"SEARCH must use X-GM-RAW for exact-match, got {call.args}"
        )
        # The query string should be of the form '"from:foo@bar"'
        query = call.args[-1]
        assert query.startswith('"from:') and query.endswith('"'), (
            f"Expected from: query, got {query!r}"
        )


def test_apply_scope_none_sentinel_is_noop(fake_account, monkeypatch):
    """APPLY_CATEGORIES=__NONE__ means user unchecked everything: no SEARCH."""
    acc, _ = fake_account
    conn = _mock_conn()
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)
    monkeypatch.setenv("APPLY_CATEGORIES", "__NONE__")

    triage.cmd_apply(acc, dry_run=True)

    search_calls = [
        c for c in conn.uid.call_args_list
        if c.args and c.args[0] == "SEARCH"
    ]
    assert search_calls == [], (
        "APPLY_CATEGORIES=__NONE__ must skip all senders"
    )


def test_apply_scope_empty_means_no_filter(fake_account, monkeypatch):
    """APPLY_CATEGORIES unset or empty = process every sender."""
    acc, _ = fake_account
    conn = _mock_conn()
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)
    monkeypatch.delenv("APPLY_CATEGORIES", raising=False)

    triage.cmd_apply(acc, dry_run=True)

    search_calls = [
        c for c in conn.uid.call_args_list
        if c.args and c.args[0] == "SEARCH"
    ]
    # Two senders in fixture: one allowed, one disallowed. Both get searched.
    assert len(search_calls) == 2


def test_apply_scope_subset_filter(fake_account, monkeypatch):
    """APPLY_CATEGORIES=Junk only acts on senders whose sublabel starts with Junk."""
    acc, _ = fake_account
    conn = _mock_conn()
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)
    monkeypatch.setenv("APPLY_CATEGORIES", "Junk")

    triage.cmd_apply(acc, dry_run=True)

    search_calls = [
        c for c in conn.uid.call_args_list
        if c.args and c.args[0] == "SEARCH"
    ]
    # Only the Junk/Promo sender survives the filter.
    assert len(search_calls) == 1
    assert "spam@example.com" in search_calls[0].args[-1]


def test_apply_logs_store_failure(fake_account, monkeypatch, capsys):
    """A failing STORE response must be logged as ERR, not silently swallowed."""
    acc, acc_dir = fake_account
    monkeypatch.delenv("APPLY_CATEGORIES", raising=False)

    # First call (SELECT) returns OK. SEARCH returns one UID. STORE returns NO.
    conn = MagicMock()
    conn.select.return_value = ("OK", [b""])
    conn.logout.return_value = ("BYE", [b""])

    def uid_side_effect(*args, **kwargs):
        op = args[0]
        if op == "SEARCH":
            return ("OK", [b"42"])
        if op == "STORE":
            return ("NO", [b"label rejected"])
        if op == "MOVE":
            return ("NO", [b"move rejected"])
        return ("OK", [b""])

    conn.uid.side_effect = uid_side_effect
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)

    triage.cmd_apply(acc, dry_run=False)

    out = capsys.readouterr().out
    assert "ERR" in out, f"Expected error in output, got:\n{out}"
    log_text = (acc_dir / "applied.log").read_text()
    assert "ERR" in log_text, f"Expected ERR in log, got:\n{log_text}"
    assert "failed" in log_text.lower() or "ERR" in log_text


def test_apply_summary_reports_failure_count(fake_account, monkeypatch, capsys):
    """Apply must print a final summary including the failure count."""
    acc, _ = fake_account
    monkeypatch.delenv("APPLY_CATEGORIES", raising=False)

    conn = MagicMock()
    conn.select.return_value = ("OK", [b""])
    conn.logout.return_value = ("BYE", [b""])

    def uid_side_effect(*args, **kwargs):
        op = args[0]
        if op == "SEARCH":
            return ("OK", [b"1 2 3"])
        if op == "STORE":
            return ("NO", [b"err"])
        return ("OK", [b""])

    conn.uid.side_effect = uid_side_effect
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)

    triage.cmd_apply(acc, dry_run=False)
    out = capsys.readouterr().out
    # Two senders, both fail STORE -> at least 2 failures
    assert "failure" in out.lower() or "failed" in out.lower()
