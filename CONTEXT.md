# CONTEXT

## Stack

- Python 3.10+ (stdlib `imaplib`, `email`, `argparse`)
- Streamlit (UI)
- Provider SDKs: anthropic, openai, google-generativeai, requests (Ollama)
- python-dotenv

## Goal

Clean up multiple Gmail accounts via LLM-classified sender lists. Per-account, editable, debuggable, multi-provider.

## Constraints

- Mail body never sent to the LLM. Subject + sender + sample subjects only.
- Trash is the terminal action. No permanent delete.
- One account at a time.
- App Password for IMAP (no OAuth, no GCP setup).
- Provider-agnostic via the abstraction in `lib/classifier.py`. Adding a provider = one class + one PROVIDERS entry + one .env block.
- `.env` holds all credentials. Gitignored.
- No body-content sent to providers. No mail sent or composed. Read-and-organize only.
