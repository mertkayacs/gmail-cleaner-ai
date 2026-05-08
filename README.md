# Gmail Triage

Single-file Python program to inventory, classify, and clean up multiple Gmail accounts.

Three subcommands per account: `inventory`, `analyze`, `apply`. IMAP via Gmail App Passwords (no OAuth, no GCP). Classification via Anthropic API.

## Setup

1. **App Password per account**
   Open https://myaccount.google.com/apppasswords (requires 2-Step Verification on the account). Generate one named "gmail-triage" or similar. Save the 16-character password.

2. **Anthropic API key**
   Get from https://console.anthropic.com/. Used only by the `analyze` command.

3. **.env**
   ```bash
   cp .env.example .env
   # edit .env, fill in keys + per-account App Passwords
   ```

4. **Dependencies**
   ```bash
   uv pip install -r requirements.txt
   # or: pip install -r requirements.txt
   ```

## Usage (per account)

```bash
# 1. Inventory: IMAP read, compute stats, no LLM
python3 triage.py inventory primary@gmail.com

# 2. Analyze: classify top senders via Claude, generate proposed lists
python3 triage.py analyze primary@gmail.com

# 3. Review the lists
cat data/primary@gmail.com/allowed.txt
cat data/primary@gmail.com/disallowed.txt
# Edit if needed (move senders between, delete lines, etc.)

# 4. Dry-run apply
python3 triage.py apply primary@gmail.com --dry-run

# 5. Live apply
python3 triage.py apply primary@gmail.com
```

Repeat for each account.

## Output (per account)

Located at `data/<account-email>/`:

- `inventory.json` — raw stats (top senders, top domains, list-unsubscribe count)
- `report.md` — human-readable summary
- `proposed_categories.json` — Claude's full classification per sender
- `allowed.txt` — keep-list (editable)
- `disallowed.txt` — trash-list (editable)
- `applied.log` — append-only audit of what was applied

## How it works

- **inventory**: connects via IMAP using App Password, walks `[Gmail]/All Mail`, fetches headers (`From`, `Subject`, `List-Unsubscribe`) in batches of 500, counts unique senders and domains, samples up to 5 subject lines per sender.

- **analyze**: takes the top 200 senders by volume, batches them through Claude (50 per call, ~4 calls per account). Each sender gets a category, sublabel, confidence, and one-line reasoning. Output split into `allowed.txt` (keep) and `disallowed.txt` (trash) for human review.

- **apply**: re-reads the lists, IMAP `STORE +X-GM-LABELS` to apply Gmail labels, IMAP `MOVE` to `[Gmail]/Trash` for disallowed senders. Trash is recoverable for 30 days; Gmail auto-purges after.

## Safety

- Mail body is never sent to Claude. Subject + sender + sample subjects only.
- Trash is the terminal action. No permanent delete.
- `--dry-run` on apply shows actions without executing.
- `allowed.txt` and `disallowed.txt` are plain text, editable. You decide before each apply.
- App Password gives full mailbox access. Treat `.env` carefully (gitignored, not committed).

## Limits

- Top-200-senders covers roughly 80–95% of typical mail volume. Senders with one or two messages are not classified by `analyze` — they stay untouched.
- Claude API calls cost real money; batch size is tuned to keep cost low (~$0.05–$0.20 per account at current Opus pricing).
- IMAP search by `FROM` is exact-match on the header value; senders with multiple display names per address are still grouped by address (the part inside `<>`).
