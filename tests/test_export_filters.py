"""Tests for cmd_export_filters: must reflect edited list files, not stale JSON."""

import json
from pathlib import Path

import pytest

import triage


@pytest.fixture
def acc_with_drift(monkeypatch, tmp_path):
    """Set up an account where proposed_categories.json and allowed.txt disagree.

    The list files are the source of truth post-review. proposed_categories.json
    is written by analyze and not regenerated when the user edits lists in the UI.
    """
    acc = "drift@gmail.com"
    acc_dir = tmp_path / acc
    acc_dir.mkdir()

    # Stale JSON: claims old@example.com is junk_promo with sublabel Junk/Stale
    (acc_dir / "proposed_categories.json").write_text(json.dumps({
        "categories": {"junk_promo": ["old@example.com"]},
        "sender_assignments": {
            "old@example.com": {
                "category": "junk_promo",
                "sublabel": "Junk/Stale",
                "confidence": 90,
                "reasoning": "marketing",
            },
        },
    }))

    # Edited lists: user moved old@example.com out, added new@example.com as keep
    # and bad@example.com as trash.
    (acc_dir / "allowed.txt").write_text(
        "# header\nnew@example.com | Newsletter/Tech | weekly digest\n"
    )
    (acc_dir / "disallowed.txt").write_text(
        "# header\nbad@example.com | Junk/Promo | promo bulk\n"
    )

    monkeypatch.setattr(triage, "DATA_DIR", tmp_path)
    return acc, acc_dir


def test_export_filters_reads_lists_not_stale_json(acc_with_drift):
    acc, acc_dir = acc_with_drift
    triage.cmd_export_filters(acc)

    xml = (acc_dir / "filters.xml").read_text()
    assert "new@example.com" in xml, "lists' allowed sender must appear in xml"
    assert "bad@example.com" in xml, "lists' disallowed sender must appear in xml"
    assert "old@example.com" not in xml, (
        "stale json sender must NOT appear in xml; export must read from lists"
    )
    # The disallowed entry should set archive=true (junk path).
    assert "shouldArchive" in xml


def test_export_filters_errors_when_no_lists(monkeypatch, tmp_path):
    acc = "empty@gmail.com"
    acc_dir = tmp_path / acc
    acc_dir.mkdir()
    monkeypatch.setattr(triage, "DATA_DIR", tmp_path)
    with pytest.raises(SystemExit):
        triage.cmd_export_filters(acc)
