# CONTEXT

## Stack

- Python 3.10+ (stdlib `imaplib`, `email`, `argparse`)
- Streamlit (UI)
- LiteLLM (one interface to 100+ provider APIs; replaces per-provider SDKs)
- python-dotenv, pandas

## Goal

Clean up multiple Gmail accounts via LLM-classified sender lists. Per-account, editable, debuggable, multi-provider.

## Constraints

- Default mode sends sender + sample subjects only. Mode 3 (sender + subject + first N body lines) is opt-in and skips bodies for security-pattern senders.
- Trash is the terminal action. No permanent delete.
- One account at a time.
- App Password for IMAP (no OAuth, no GCP setup).
- Provider-agnostic via LiteLLM. Adding a provider = setting `LLM_MODEL` to any LiteLLM-supported model name (and a matching key var). The Streamlit UI ships with eleven presets in `app.py:PRESETS`.
- `.env` holds all credentials. Gitignored.
- IMAP search uses Gmail's `X-GM-RAW from:exact@addr` for token-exact match. Plain IMAP `FROM` is substring and unsafe for the destructive Trash path.
