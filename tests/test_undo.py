"""Tests for cmd_undo: parses last-apply TRASH lines and restores from Trash."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import triage


def _write_log(p: Path, text: str):
    p.write_text(text)


def test_parse_last_trash_actions_picks_only_last_session(tmp_path):
    log = tmp_path / "applied.log"
    _write_log(log, """
# Apply log: a@b
# 2026-05-01T00:00:00+00:00
# dry_run: False

  KEEP keep1@a.com (3 mails) -> label 'Keep/Old'
  TRASH old-spam@a.com (5 mails) -> label 'Junk/Promo', move to Trash

# Apply log: a@b
# 2026-05-08T00:00:00+00:00
# dry_run: False

  KEEP keep2@a.com (4 mails) -> label 'Keep/New'
  TRASH new-spam-1@a.com (10 mails) -> label 'Junk/Promo', move to Trash
  TRASH new-spam-2@a.com (7 mails) -> label 'Junk/Promo', move to Trash
""")
    actions = triage.parse_last_trash_actions(log)
    assert actions == [
        ("new-spam-1@a.com", 10),
        ("new-spam-2@a.com", 7),
    ]


def test_parse_last_trash_actions_missing_log(tmp_path):
    assert triage.parse_last_trash_actions(tmp_path / "nope.log") == []


def test_parse_last_trash_actions_no_trash_lines(tmp_path):
    log = tmp_path / "applied.log"
    _write_log(log, "# Apply log: a@b\n# 2026-05-08T00:00:00+00:00\n\n  KEEP a@b (1 mails) -> label 'k'\n")
    assert triage.parse_last_trash_actions(log) == []


@pytest.fixture
def acc_with_trash_log(monkeypatch, tmp_path):
    acc = "test@gmail.com"
    acc_dir = tmp_path / acc
    acc_dir.mkdir()
    (acc_dir / "applied.log").write_text(
        "\n# Apply log: test@gmail.com\n"
        "# 2026-05-09T00:00:00+00:00\n"
        "# dry_run: False\n\n"
        "  TRASH spam@example.com (3 mails) -> label 'Junk/Promo', move to Trash\n"
    )
    monkeypatch.setattr(triage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(triage, "load_account", lambda e: (acc, "fakepass"))
    return acc, acc_dir


def test_undo_dry_run_makes_no_imap_changes(acc_with_trash_log, monkeypatch, capsys):
    acc, _ = acc_with_trash_log
    conn = MagicMock()
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)

    triage.cmd_undo(acc, dry_run=True)

    out = capsys.readouterr().out
    assert "spam@example.com" in out
    assert "DRY RUN" in out
    conn.select.assert_not_called()
    conn.uid.assert_not_called()


def test_undo_searches_trash_and_moves_back(acc_with_trash_log, monkeypatch, capsys):
    acc, acc_dir = acc_with_trash_log
    conn = MagicMock()
    conn.select.return_value = ("OK", [b""])
    conn.logout.return_value = ("BYE", [b""])

    def uid_side_effect(*args, **kwargs):
        op = args[0]
        if op == "SEARCH":
            return ("OK", [b"1 2 3"])
        if op == "MOVE":
            return ("OK", [b""])
        return ("OK", [b""])

    conn.uid.side_effect = uid_side_effect
    monkeypatch.setattr(triage, "imap_connect", lambda *a, **kw: conn)

    triage.cmd_undo(acc, dry_run=False)

    # Must select the Trash folder, not All Mail.
    assert conn.select.call_args.args[0] == triage.TRASH_FOLDER
    # Must MOVE matching mail back to All Mail.
    move_calls = [c for c in conn.uid.call_args_list if c.args[0] == "MOVE"]
    assert move_calls, "expected at least one MOVE call back to All Mail"
    assert move_calls[0].args[-1] == triage.ALL_MAIL_FOLDER

    log_text = (acc_dir / "applied.log").read_text()
    assert "RESTORED" in log_text
