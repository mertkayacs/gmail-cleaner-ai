#!/usr/bin/env python3
"""
Gmail triage tool. Single-file Python program.

Reads Gmail accounts via IMAP using App Passwords, classifies senders via the
Anthropic API, applies labels and trash decisions back via IMAP. Per-account,
debuggable, three subcommands: inventory, analyze, apply.

Setup:
  1. Generate an App Password per account at myaccount.google.com/apppasswords
     (requires 2-Step Verification on the account)
  2. Copy .env.example to .env and fill in
  3. pip install -r requirements.txt   (or uv pip install -r requirements.txt)

Usage:
  python3 triage.py inventory <account-email>
  python3 triage.py analyze   <account-email>
  python3 triage.py apply     <account-email> [--dry-run]
"""

import argparse
import imaplib
import json
import os
import re
import sys
import textwrap
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email import message_from_bytes
from email.utils import parseaddr
from pathlib import Path

# anthropic and dotenv are lazy-imported inside the functions that need them
# so that `triage.py --help` works without installing deps first.

DATA_DIR = Path(__file__).parent / "data"

# Defaults overridable via env vars (Streamlit UI sets them in subprocess env).
SENDER_BATCH_SIZE = int(os.environ.get("SENDER_BATCH_SIZE", "50"))    # senders per classification call
TOP_SENDER_CAP = int(os.environ.get("TOP_SENDER_CAP", "200"))         # only classify top N senders by volume
FETCH_BATCH_SIZE = int(os.environ.get("FETCH_BATCH_SIZE", "500"))     # IMAP fetch chunk size
CLASSIFY_MODE = os.environ.get("CLASSIFY_MODE", "sender_subject")     # sender_only | sender_subject | sender_subject_body
BODY_LINES = int(os.environ.get("BODY_LINES", "5"))                   # body lines per sample mail (mode 3 only)
BODY_SAMPLES_PER_SENDER = 3                                           # how many sample mails per top sender to fetch body for
ALL_MAIL_FOLDER = '"[Gmail]/All Mail"'
TRASH_FOLDER = '"[Gmail]/Trash"'


# -------------------- Account loading -----------------------------------------

def load_account(account_email):
    """Find account in .env, return (email, app_password)."""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    for i in range(1, 21):
        env_email = os.environ.get(f"GMAIL_ACCOUNT_{i}")
        if env_email and env_email.lower() == account_email.lower():
            password = os.environ.get(f"GMAIL_APPPASS_{i}")
            if not password:
                raise SystemExit(f"GMAIL_APPPASS_{i} missing in .env")
            return env_email, password
    raise SystemExit(
        f"Account {account_email} not found in .env. "
        f"Add as GMAIL_ACCOUNT_<n> with matching GMAIL_APPPASS_<n>."
    )


# -------------------- IMAP helpers --------------------------------------------

def imap_connect(email_addr, password):
    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    conn.login(email_addr, password)
    return conn


def parse_fetch_response(msg_data):
    """Walk imaplib FETCH response, yield (uid, header_bytes) tuples."""
    for entry in msg_data:
        if isinstance(entry, tuple) and len(entry) >= 2:
            envelope = entry[0]
            header_bytes = entry[1]
            if not isinstance(header_bytes, (bytes, bytearray)):
                continue
            envelope_str = envelope.decode(errors="ignore") if isinstance(envelope, (bytes, bytearray)) else str(envelope)
            uid_match = re.search(r"UID (\d+)", envelope_str)
            uid = uid_match.group(1) if uid_match else None
            yield uid, bytes(header_bytes)


def parse_headers(header_bytes):
    msg = message_from_bytes(header_bytes)
    return {
        "from": msg.get("From", "") or "",
        "subject": msg.get("Subject", "") or "",
        "list_unsubscribe": msg.get("List-Unsubscribe", "") or "",
    }


def extract_sender(from_header):
    _, addr = parseaddr(from_header)
    return addr.lower().strip() if addr else ""


def domain_of(email_addr):
    return email_addr.split("@", 1)[1].lower() if "@" in email_addr else ""


def extract_text_excerpt(body_bytes, n_lines):
    """Pull a short text excerpt from a fetched message body.

    Walks MIME parts, prefers text/plain over text/html. Strips HTML if
    only HTML is available. Returns the first n_lines of meaningful text,
    truncated to keep the prompt small.
    """
    msg = message_from_bytes(body_bytes)
    text = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(errors="ignore")
                break
        if text is None:
            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                if ctype == "text/html":
                    payload = part.get_payload(decode=True) or b""
                    text = re.sub(r"<[^>]+>", " ", payload.decode(errors="ignore"))
                    break
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, (bytes, bytearray)):
            text = payload.decode(errors="ignore")
            if (msg.get_content_type() or "").lower() == "text/html":
                text = re.sub(r"<[^>]+>", " ", text)
    if not text:
        return ""

    lines = []
    for raw in text.splitlines():
        cleaned = " ".join(raw.split())
        if cleaned:
            lines.append(cleaned[:200])
        if len(lines) >= n_lines:
            break
    return "\n".join(lines)


# -------------------- Inventory -----------------------------------------------

def cmd_inventory(account_email):
    email_addr, password = load_account(account_email)
    print(f"Connecting to IMAP for {email_addr}...")
    conn = imap_connect(email_addr, password)
    try:
        typ, _ = conn.select(ALL_MAIL_FOLDER, readonly=True)
        if typ != "OK":
            raise SystemExit(f"Could not select {ALL_MAIL_FOLDER}: {typ}")

        print("Searching all mail...")
        typ, data = conn.uid("SEARCH", None, "ALL")
        if typ != "OK":
            raise SystemExit(f"Search failed: {typ}")
        uids = data[0].split()
        total = len(uids)
        print(f"Total mail: {total}")
        if total == 0:
            print("No mail found.")
            return

        senders = Counter()
        domains = Counter()
        has_unsubscribe = 0
        samples = defaultdict(list)
        # Per-sender UID list, capped at BODY_SAMPLES_PER_SENDER, used by mode-3
        # body-fetch pass below. Building it during pass 1 avoids a third lookup.
        sender_uids = defaultdict(list)

        n_batches = (total + FETCH_BATCH_SIZE - 1) // FETCH_BATCH_SIZE
        for i, batch_start in enumerate(range(0, total, FETCH_BATCH_SIZE)):
            batch_uids = uids[batch_start:batch_start + FETCH_BATCH_SIZE]
            uid_set = b",".join(batch_uids).decode()
            print(f"  Fetching batch {i + 1}/{n_batches} ({len(batch_uids)} mails)...")
            typ, msg_data = conn.uid(
                "FETCH",
                uid_set,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT LIST-UNSUBSCRIBE)])",
            )
            if typ != "OK":
                print(f"  Fetch failed: {typ}")
                continue
            for uid, header_bytes in parse_fetch_response(msg_data):
                hdrs = parse_headers(header_bytes)
                sender = extract_sender(hdrs["from"])
                if not sender:
                    continue
                senders[sender] += 1
                d = domain_of(sender)
                if d:
                    domains[d] += 1
                if hdrs["list_unsubscribe"]:
                    has_unsubscribe += 1
                if hdrs["subject"] and len(samples[sender]) < 5:
                    samples[sender].append(hdrs["subject"][:200])
                if uid and len(sender_uids[sender]) < BODY_SAMPLES_PER_SENDER:
                    sender_uids[sender].append(uid)

        # Pass 2 (mode 3 only): fetch body excerpts for top senders' sample UIDs.
        # Skipped entirely for sender_only and sender_subject so privacy and speed
        # are unchanged for the default flow.
        sample_bodies = {}
        if CLASSIFY_MODE == "sender_subject_body":
            top_for_body = [s for s, _ in senders.most_common(TOP_SENDER_CAP)]
            print(f"Mode {CLASSIFY_MODE}: fetching body excerpts for "
                  f"{len(top_for_body)} top senders ({BODY_LINES} lines each)...")
            for j, sender in enumerate(top_for_body):
                uids_for_sender = sender_uids.get(sender, [])
                if not uids_for_sender:
                    continue
                excerpts = []
                for uid in uids_for_sender:
                    typ, body_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                    if typ != "OK":
                        continue
                    for _u, body_bytes in parse_fetch_response(body_data):
                        excerpt = extract_text_excerpt(body_bytes, BODY_LINES)
                        if excerpt:
                            excerpts.append(excerpt)
                if excerpts:
                    sample_bodies[sender] = excerpts
                if (j + 1) % 25 == 0:
                    print(f"  body fetch: {j + 1}/{len(top_for_body)} senders done")
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    out_dir = DATA_DIR / email_addr
    out_dir.mkdir(parents=True, exist_ok=True)

    top_set = dict(senders.most_common(TOP_SENDER_CAP))
    inventory = {
        "account": email_addr,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_mails": total,
        "unique_senders": len(senders),
        "unique_domains": len(domains),
        "has_list_unsubscribe": has_unsubscribe,
        "classify_mode": CLASSIFY_MODE,
        "body_lines": BODY_LINES if CLASSIFY_MODE == "sender_subject_body" else 0,
        "top_senders": senders.most_common(TOP_SENDER_CAP),
        "top_domains": domains.most_common(50),
        "sample_subjects": {s: subjs for s, subjs in samples.items() if s in top_set},
        "sample_bodies": {s: bodies for s, bodies in sample_bodies.items() if s in top_set},
    }
    (out_dir / "inventory.json").write_text(json.dumps(inventory, indent=2, default=str))

    pct = (has_unsubscribe * 100 // total) if total else 0
    report_lines = [
        f"# Inventory Report: {email_addr}",
        "",
        f"Generated: {inventory['generated_at']}",
        "",
        "## Totals",
        f"- Total mails: {total}",
        f"- Unique senders: {len(senders)}",
        f"- Unique domains: {len(domains)}",
        f"- Has List-Unsubscribe header: {has_unsubscribe} ({pct}%)",
        "",
        "## Top 50 senders",
        "",
        "| Count | Sender |",
        "|---|---|",
    ]
    for sender, count in senders.most_common(50):
        report_lines.append(f"| {count} | {sender} |")
    report_lines += ["", "## Top 25 domains", "", "| Count | Domain |", "|---|---|"]
    for domain, count in domains.most_common(25):
        report_lines.append(f"| {count} | {domain} |")
    (out_dir / "report.md").write_text("\n".join(report_lines) + "\n")

    print(f"\nInventory: {out_dir}/inventory.json")
    print(f"Report:    {out_dir}/report.md")


# -------------------- Analyze -------------------------------------------------

def build_classification_prompt(batch_pairs, samples, mode="sender_subject"):
    """Build the classification prompt for one batch.

    mode controls how much evidence per sender goes to the LLM:
      - sender_only: just sender email + mail count
      - sender_subject: sender + count + 3 sample subjects (default)
      - sender_subject_body: sender + count + 3 sample subjects + body excerpts
        (excerpts must already exist in samples under the 'body' key per sender;
        body fetch happens in the inventory step.)
    """
    items = []
    for sender, count in batch_pairs:
        item = {"sender": sender, "count": count}
        if mode in ("sender_subject", "sender_subject_body"):
            item["sample_subjects"] = samples.get(sender, [])[:3]
        if mode == "sender_subject_body":
            body = samples.get(sender + "::body", [])
            if body:
                item["body_excerpts"] = body[:3]
        items.append(item)

    if mode == "sender_only":
        evidence_line = "Senders to classify (with mail count only, no subjects):"
    elif mode == "sender_subject_body":
        evidence_line = "Senders to classify (with mail count, sample subjects, and body excerpts):"
    else:
        evidence_line = "Senders to classify (with mail count and sample subjects):"

    return textwrap.dedent("""\
        You are classifying email senders for a personal Gmail organization system.

        For each sender below, decide:
        - category: one of keep_personal, keep_work, keep_security, keep_transactional, keep_calendar, keep_newsletter, keep_other, junk_promo, junk_spam, junk_low_newsletter, junk_notification, junk_other.
        - sublabel: a descriptive sub-label like "Personal/Family", "Work/<company>", "Newsletter/Tech", "Junk/Promo".
        - confidence: integer 0-100.
        - reasoning: one short sentence.

        Rules:
        - keep_security covers 2FA, password resets, security alerts, bank security, government auth.
        - keep_transactional covers receipts, invoices, shipping confirmations, order confirmations.
        - junk_promo is marketing, sales, discount campaigns, list-unsubscribable bulk mail with no sign of personal value.
        - If sender is a noreply automated address with no clear value, junk_notification.
        - If newsletter-shaped but might be useful, keep_newsletter.
        - When in doubt, lean keep_* over junk_*. Better to keep one extra than wrongly trash important.
        - If confidence below 70 on a junk_* category, fallback to keep_other.

        Output strictly as a JSON object with sender as key. Example:
        {"foo@bar.com": {"category": "keep_work", "sublabel": "Work/Acme", "confidence": 85, "reasoning": "Recurring sender with personalized subject lines."}}

        """) + evidence_line + "\n" + json.dumps(items, indent=2) + "\n\nReturn the JSON object only, no surrounding text."


def cmd_analyze(account_email):
    out_dir = DATA_DIR / account_email
    inv_path = out_dir / "inventory.json"
    if not inv_path.exists():
        raise SystemExit(f"No inventory at {inv_path}. Run `inventory` first.")
    inventory = json.loads(inv_path.read_text())
    top_senders = inventory["top_senders"]
    samples = dict(inventory.get("sample_subjects", {}))
    # Body excerpts for mode 3 are stored separately in inventory.json under
    # 'sample_bodies'. Merge them into samples with a '::body' suffix so the
    # prompt builder picks them up via the convention defined in
    # build_classification_prompt above.
    for _sender, _bodies in inventory.get("sample_bodies", {}).items():
        samples[_sender + "::body"] = _bodies

    # SENDERS env var triggers hybrid re-classify: only the listed senders
    # get sent to the LLM, results merge into existing proposed_categories
    # so previously-classified senders survive untouched. Empty value means
    # full classify (default). Comma-separated emails, lowercased.
    selected_env = os.environ.get("SENDERS", "").strip()
    selected_set = set(s.strip().lower() for s in selected_env.split(",") if s.strip())
    if selected_set:
        top_senders = [(s, c) for s, c in top_senders if s.lower() in selected_set]
        print(f"Hybrid re-classify: {len(top_senders)} selected sender(s).")
        if not top_senders:
            print("None of the selected senders were found in inventory. Aborting.")
            return

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    from lib.classifier import get_classifier
    classifier = get_classifier()
    api_base_note = f" via {classifier.api_base}" if classifier.api_base else ""
    print(f"Using model: {classifier.model}{api_base_note}")

    all_classifications = {}
    n_batches = (len(top_senders) + SENDER_BATCH_SIZE - 1) // SENDER_BATCH_SIZE
    print(f"Mode: {CLASSIFY_MODE}")
    for i in range(0, len(top_senders), SENDER_BATCH_SIZE):
        batch = top_senders[i:i + SENDER_BATCH_SIZE]
        print(f"Classifying batch {i // SENDER_BATCH_SIZE + 1}/{n_batches} "
              f"({len(batch)} senders)...")
        prompt = build_classification_prompt(batch, samples, mode=CLASSIFY_MODE)
        try:
            classifications = classifier.classify_batch(prompt)
        except Exception as e:
            print(f"  Classifier error: {e}")
            continue
        all_classifications.update(classifications)

    # Hybrid merge: load existing assignments and overlay new ones so senders
    # not in this run keep their prior classification.
    if selected_set:
        cats_path = out_dir / "proposed_categories.json"
        if cats_path.exists():
            try:
                prior = json.loads(cats_path.read_text()).get("sender_assignments", {})
                merged = dict(prior)
                merged.update(all_classifications)
                all_classifications = merged
                print(f"Merged with {len(prior)} prior assignments.")
            except Exception as e:
                print(f"Could not merge prior assignments: {e}")

    by_category = defaultdict(list)
    allowed = []
    disallowed = []
    for sender, info in all_classifications.items():
        cat = info.get("category", "keep_other")
        by_category[cat].append(sender)
        line = (sender, info.get("sublabel", ""), info.get("reasoning", ""))
        if cat.startswith("junk_"):
            disallowed.append(line)
        else:
            allowed.append(line)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "proposed_categories.json").write_text(json.dumps({
        "categories": dict(by_category),
        "sender_assignments": all_classifications,
    }, indent=2))

    def write_list(path, header, rows):
        lines = [
            f"# {header}",
            "# Format: sender@domain | sublabel | reasoning",
            "# Edit before running `apply`. Lines starting with # are ignored.",
            "",
        ]
        for sender, sublabel, reasoning in sorted(rows):
            lines.append(f"{sender} | {sublabel} | {reasoning}")
        path.write_text("\n".join(lines) + "\n")

    write_list(out_dir / "allowed.txt", "Allowed senders (keep)", allowed)
    write_list(out_dir / "disallowed.txt", "Disallowed senders (move to Trash)", disallowed)

    print(f"\nProposed categories: {out_dir}/proposed_categories.json")
    print(f"Allowed list ({len(allowed)} senders): {out_dir}/allowed.txt")
    print(f"Disallowed list ({len(disallowed)} senders): {out_dir}/disallowed.txt")
    print("\nReview and edit allowed.txt and disallowed.txt before running `apply`.")


# -------------------- Apply ---------------------------------------------------

def parse_list_file(path):
    """Parse list file. Returns dict sender -> sublabel."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        sender = parts[0].lower()
        sublabel = parts[1] if len(parts) > 1 else ""
        if sender:
            out[sender] = sublabel
    return out


def build_filter_xml(assignments, account_email):
    """Build a Gmail filter export XML from per-sender classifications."""
    from xml.sax.saxutils import escape
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts = int(datetime.now(timezone.utc).timestamp())

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:apps="http://schemas.google.com/apps/2006">',
        f'  <title>Mail Filters from gmail-cleaner-ai for {escape(account_email)}</title>',
        f'  <id>tag:mail.google.com,2008:filters:{ts}</id>',
        f'  <updated>{now_iso}</updated>',
        '  <author><name>gmail-cleaner-ai</name></author>',
    ]

    for i, (sender, info) in enumerate(sorted(assignments.items())):
        sublabel = info.get("sublabel", "")
        category = info.get("category", "keep_other")
        if not sublabel:
            continue
        is_junk = category.startswith("junk_")
        properties = [
            f'    <apps:property name="from" value="{escape(sender)}"/>',
            f'    <apps:property name="label" value="{escape(sublabel)}"/>',
        ]
        if is_junk:
            properties.append('    <apps:property name="shouldArchive" value="true"/>')
        parts.extend([
            '  <entry>',
            '    <category term="filter"></category>',
            '    <title>Mail Filter</title>',
            f'    <id>tag:mail.google.com,2008:filter:{ts}-{i}</id>',
            f'    <updated>{now_iso}</updated>',
            '    <content></content>',
            *properties,
            '  </entry>',
        ])

    parts.append('</feed>')
    return "\n".join(parts) + "\n"


def cmd_export_filters(account_email):
    """Emit Gmail filter XML from the proposed_categories.json file."""
    out_dir = DATA_DIR / account_email
    cats_path = out_dir / "proposed_categories.json"
    if not cats_path.exists():
        raise SystemExit(f"No analysis at {cats_path}. Run `analyze` first.")
    cats = json.loads(cats_path.read_text())
    assignments = cats.get("sender_assignments", {})
    if not assignments:
        raise SystemExit("No sender assignments to export.")
    xml = build_filter_xml(assignments, account_email)
    out_path = out_dir / "filters.xml"
    out_path.write_text(xml)
    junk_count = sum(1 for a in assignments.values()
                     if a.get("category", "").startswith("junk_"))
    print(f"Wrote {out_path}")
    print(f"  {len(assignments)} filters total, {junk_count} junk (skip-inbox)")
    print("\nImport in Gmail: Settings -> See all settings -> Filters and Blocked Addresses ->")
    print("Import filters -> select this file -> check 'Apply new filters to existing email'.")


def cmd_apply(account_email, dry_run):
    out_dir = DATA_DIR / account_email
    allowed = parse_list_file(out_dir / "allowed.txt")
    disallowed = parse_list_file(out_dir / "disallowed.txt")
    if not allowed and not disallowed:
        raise SystemExit("Run `analyze` first or populate allowed.txt and disallowed.txt.")

    print(f"Allowed senders: {len(allowed)}")
    print(f"Disallowed senders: {len(disallowed)}")
    if dry_run:
        print("DRY RUN: no IMAP changes will be made.\n")
    else:
        print()

    email_addr, password = load_account(account_email)
    conn = imap_connect(email_addr, password)
    log_lines = []
    log_lines.append(f"# Apply log: {email_addr}")
    log_lines.append(f"# {datetime.now(timezone.utc).isoformat()}")
    log_lines.append(f"# dry_run: {dry_run}")
    log_lines.append("")

    try:
        typ, _ = conn.select(ALL_MAIL_FOLDER)
        if typ != "OK":
            raise SystemExit(f"Could not select {ALL_MAIL_FOLDER}: {typ}")

        # Apply labels for allowed senders
        for sender, sublabel in sorted(allowed.items()):
            if not sublabel:
                continue
            typ, data = conn.uid("SEARCH", None, "FROM", f'"{sender}"')
            if typ != "OK":
                continue
            uids = data[0].split()
            if not uids:
                continue
            uid_set = b",".join(uids).decode()
            msg = f"  KEEP {sender} ({len(uids)} mails) -> label '{sublabel}'"
            print(msg)
            log_lines.append(msg)
            if not dry_run:
                conn.uid("STORE", uid_set, "+X-GM-LABELS", f'("{sublabel}")')

        # Move disallowed senders to Trash
        for sender, sublabel in sorted(disallowed.items()):
            typ, data = conn.uid("SEARCH", None, "FROM", f'"{sender}"')
            if typ != "OK":
                continue
            uids = data[0].split()
            if not uids:
                continue
            uid_set = b",".join(uids).decode()
            label_to_apply = sublabel or "Junk/Other"
            msg = f"  TRASH {sender} ({len(uids)} mails) -> label '{label_to_apply}', move to Trash"
            print(msg)
            log_lines.append(msg)
            if not dry_run:
                conn.uid("STORE", uid_set, "+X-GM-LABELS", f'("{label_to_apply}")')
                conn.uid("MOVE", uid_set, TRASH_FOLDER)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    log_path = out_dir / "applied.log"
    if log_path.exists():
        existing = log_path.read_text()
        log_path.write_text(existing + "\n" + "\n".join(log_lines) + "\n")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(log_lines) + "\n")

    print(f"\n{'Dry run complete' if dry_run else 'Apply complete'}. Log: {log_path}")


# -------------------- Entrypoint ----------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Gmail triage tool. Inventory, analyze, apply per account."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inv = sub.add_parser("inventory", help="Read mail metadata, compute stats")
    p_inv.add_argument("account", help="Gmail account email")

    p_an = sub.add_parser("analyze", help="Classify top senders via Anthropic API")
    p_an.add_argument("account", help="Gmail account email")

    p_ap = sub.add_parser("apply", help="Apply labels and Trash via IMAP")
    p_ap.add_argument("account", help="Gmail account email")
    p_ap.add_argument("--dry-run", action="store_true", help="Show actions, do not modify")

    p_ex = sub.add_parser("export-filters", help="Emit Gmail filter XML for one-time import")
    p_ex.add_argument("account", help="Gmail account email")

    args = parser.parse_args()
    if args.cmd == "inventory":
        cmd_inventory(args.account)
    elif args.cmd == "analyze":
        cmd_analyze(args.account)
    elif args.cmd == "apply":
        cmd_apply(args.account, dry_run=args.dry_run)
    elif args.cmd == "export-filters":
        cmd_export_filters(args.account)


if __name__ == "__main__":
    main()
