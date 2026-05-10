"""Tests for pure helper functions in triage.py."""

from pathlib import Path

import triage


def test_extract_sender_lowercases_and_strips():
    assert triage.extract_sender("Foo <Foo@Example.COM>") == "foo@example.com"
    assert triage.extract_sender("  bare@example.com  ") == "bare@example.com"
    assert triage.extract_sender("") == ""


def test_domain_of():
    assert triage.domain_of("foo@example.com") == "example.com"
    assert triage.domain_of("FOO@EXAMPLE.COM") == "example.com"
    assert triage.domain_of("no-at-sign") == ""


def test_parse_list_file_handles_comments_and_pipes(tmp_path: Path):
    p = tmp_path / "allowed.txt"
    p.write_text(
        "# header comment\n"
        "\n"
        "foo@example.com | Newsletter/Tech | weekly digest\n"
        "BAR@example.com | Junk/Promo\n"
        "  \n"
        "noemail | should keep |  \n"
    )
    out = triage.parse_list_file(p)
    assert out["foo@example.com"] == "Newsletter/Tech"
    assert out["bar@example.com"] == "Junk/Promo"
    assert "noemail" in out


def test_parse_list_file_missing_returns_empty(tmp_path: Path):
    assert triage.parse_list_file(tmp_path / "nope.txt") == {}


def test_extract_text_excerpt_handles_plain_and_html():
    plain = b"Subject: x\r\nFrom: a@b\r\nContent-Type: text/plain\r\n\r\nLine 1\nLine 2\nLine 3\n"
    assert "Line 1" in triage.extract_text_excerpt(plain, n_lines=2)

    html = b"Subject: x\r\nFrom: a@b\r\nContent-Type: text/html\r\n\r\n<p>Hello <b>world</b></p>"
    out = triage.extract_text_excerpt(html, n_lines=2)
    assert "Hello" in out
    assert "<" not in out  # tags stripped


def test_is_security_sender_flags_otp_and_security_paths():
    """Body excerpts go to the LLM in mode 3. Senders likely to send OTPs,
    password resets, or security alerts must be flagged so we never fetch
    their bodies."""
    flagged = [
        "noreply@google.com",
        "no-reply@apple.com",
        "security-noreply@github.com",
        "verify@stripe.com",
        "verification@bank.com",
        "2fa@example.com",
        "otp@example.com",
        "mfa@x.com",
        "password-reset@x.com",
        "login@accounts.google.com",
    ]
    for s in flagged:
        assert triage.is_security_sender(s), f"{s} should be flagged"

    safe = [
        "alice@example.com",
        "newsletter@digest.com",
        "support@vendor.com",  # generic, not flagged
        "author@blog.com",      # contains 'auth' but only as substring of 'author'
    ]
    for s in safe:
        assert not triage.is_security_sender(s), f"{s} should NOT be flagged"
