# Changelog

All notable changes to this project. Versions follow semver (MAJOR.MINOR.PATCH).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-05-11

First public version. The four-card Streamlit flow plus the CLI is feature-complete enough to run end-to-end on a real Gmail account: scan, classify, review, apply, undo, snapshot.

### Added

- Single-page Streamlit UI: setup, scan + classify, review, apply, history.
- `triage.py` CLI with subcommands `inventory`, `analyze`, `apply`, `export-filters`, `propose-categories`, `undo`, `history-save`, `history-list`, `history-restore`, `history-delete`.
- LiteLLM-backed classifier supporting Anthropic, OpenAI, Gemini, Groq, Together AI, OpenRouter, Mistral, Ollama, LM Studio, llama.cpp, and any other LiteLLM-supported model.
- Three privacy modes: sender-only, sender + sample subjects (default), sender + subject + first N body lines (opt-in, skips security-pattern senders).
- Three category sources: 12-category preset, LLM-drafted schema per inbox, binary keep/trash.
- Hybrid re-classify: re-run classify on a subset of selected senders while everything else keeps its prior classification.
- Per-category scope filter at apply time.
- Gmail filter XML export so future mail auto-routes without further LLM calls.
- Settings XML export and import to bundle classify config across machines.
- `undo` command (CLI + UI) that restores last apply's trashed senders from Trash to All Mail.
- History snapshots under `data/<account>/history/<timestamp>/`: save, list, restore, delete (CLI + UI).
- Cost preview before classify using `litellm.token_counter` and `model_cost`.
- 33 pytest tests covering apply, classifier retry, export-filters, helpers, undo, history.

### Safety

- IMAP search uses `X-GM-RAW "from:exact@addr"` for token-exact matching. Plain IMAP `FROM` is substring and could match near-collision senders.
- `STORE` and `MOVE` return codes checked per sender. Failures surface as `ERR` log lines and a final failure count.
- Apply log opens in append mode and flushes per sender, so a Ctrl-C or crash mid-loop preserves an accurate record on disk.
- `imap_connect` sets a 60s socket timeout so a network hang fails fast.
- `classify_batch` retries three times with exponential backoff on transient API errors.
- Mode 3 body excerpts skip senders matching security patterns (`noreply`, `security`, `verify`, `verification`, `auth`, `2fa`, `otp`, `mfa`, `password`, `accounts.google.com`).
- Apply scope filter uses `__NONE__` sentinel for "user unchecked every category", to distinguish from "no filter at all".
- `export-filters` reads from the edited `allowed.txt` / `disallowed.txt` rather than the static `proposed_categories.json` that the analyze step writes once and doesn't regenerate.

### Privacy

- Mail body content is never sent to the LLM unless mode 3 is explicitly chosen.
- App Passwords are stored locally in `.env`; the tool sends them only to Gmail's IMAP endpoint.
- Trash is the terminal action. Gmail's 30-day auto-purge handles permanent removal.
