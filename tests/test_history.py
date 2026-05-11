"""Tests for the history snapshot commands."""

from pathlib import Path

import pytest

import triage


@pytest.fixture
def acc(monkeypatch, tmp_path):
    name = "test@gmail.com"
    d = tmp_path / name
    d.mkdir()
    (d / "allowed.txt").write_text("# allowed\nkeep@x.com | Keep/A | a\n")
    (d / "disallowed.txt").write_text("# disallowed\nbad@x.com | Junk/A | b\n")
    (d / "proposed_categories.json").write_text('{"sender_assignments": {}}')
    (d / "filters.xml").write_text("<feed/>")
    monkeypatch.setattr(triage, "DATA_DIR", tmp_path)
    return name, d


def test_save_copies_decision_files(acc):
    name, d = acc
    snap_id = triage.cmd_history_save(name)
    snap = d / "history" / snap_id
    assert snap.is_dir()
    assert (snap / "allowed.txt").read_text() == (d / "allowed.txt").read_text()
    assert (snap / "disallowed.txt").read_text() == (d / "disallowed.txt").read_text()
    assert (snap / "proposed_categories.json").exists()
    assert (snap / "filters.xml").exists()


def test_save_writes_label_when_given(acc):
    name, d = acc
    snap_id = triage.cmd_history_save(name, label="opus before sonnet")
    label = (d / "history" / snap_id / "label.txt").read_text().strip()
    assert label == "opus before sonnet"


def test_save_omits_missing_files(acc):
    name, d = acc
    (d / "filters.xml").unlink()
    snap_id = triage.cmd_history_save(name)
    snap = d / "history" / snap_id
    assert not (snap / "filters.xml").exists()
    assert (snap / "allowed.txt").exists()


def test_save_with_no_lists_raises(monkeypatch, tmp_path):
    d = tmp_path / "empty@gmail.com"
    d.mkdir()
    monkeypatch.setattr(triage, "DATA_DIR", tmp_path)
    with pytest.raises(SystemExit):
        triage.cmd_history_save("empty@gmail.com")


def test_list_prints_snapshots_oldest_first(acc, capsys):
    name, _ = acc
    snap1 = triage.cmd_history_save(name, label="first")
    # Force a distinct second-resolution timestamp.
    import time
    time.sleep(1.0)
    snap2 = triage.cmd_history_save(name, label="second")

    triage.cmd_history_list(name)
    out = capsys.readouterr().out
    i1 = out.index(snap1)
    i2 = out.index(snap2)
    assert i1 < i2
    assert "first" in out and "second" in out


def test_list_empty_says_so(monkeypatch, tmp_path, capsys):
    d = tmp_path / "empty@gmail.com"
    d.mkdir()
    monkeypatch.setattr(triage, "DATA_DIR", tmp_path)
    triage.cmd_history_list("empty@gmail.com")
    assert "No history" in capsys.readouterr().out


def test_restore_overwrites_current(acc):
    name, d = acc
    snap_id = triage.cmd_history_save(name)
    # Mutate active files
    (d / "allowed.txt").write_text("# allowed\nDIFFERENT@x.com | X | x\n")
    (d / "disallowed.txt").write_text("# disallowed\n")

    triage.cmd_history_restore(name, snap_id)
    assert "keep@x.com" in (d / "allowed.txt").read_text()
    assert "bad@x.com" in (d / "disallowed.txt").read_text()


def test_restore_missing_snapshot_raises(acc):
    name, _ = acc
    with pytest.raises(SystemExit):
        triage.cmd_history_restore(name, "2099-01-01_000000")


def test_delete_removes_snapshot_dir(acc):
    name, d = acc
    snap_id = triage.cmd_history_save(name)
    snap = d / "history" / snap_id
    assert snap.is_dir()

    triage.cmd_history_delete(name, snap_id)
    assert not snap.exists()


def test_delete_missing_snapshot_raises(acc):
    name, _ = acc
    with pytest.raises(SystemExit):
        triage.cmd_history_delete(name, "2099-01-01_000000")
