# gmail-cleaner-ai

[![tests](https://github.com/mertkayacs/gmail-cleaner-ai/actions/workflows/test.yml/badge.svg)](https://github.com/mertkayacs/gmail-cleaner-ai/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> Clean up multiple Gmail accounts with whichever LLM you trust.

You have several Gmail accounts. Each holds thousands of mails. Most of it is marketing, automated notifications, or newsletters you stopped reading. Manually triaging each account takes hours and never finishes.

`gmail-cleaner-ai` reads your accounts via IMAP, classifies senders with an LLM you pick (Anthropic, OpenAI, Gemini, or any open-source model via Ollama), and either keeps them with a sublabel or moves them to Trash. One account at a time, debuggable, with a Streamlit UI for review.

## What it does

- Connects to Gmail via IMAP using App Passwords (no OAuth, no Google Cloud project).
- Reads metadata for every mail across an account: sender, subject, headers.
- Sends top senders to your chosen LLM for classification. Sender plus 3 sample subjects, no body.
- Outputs editable allowed and disallowed lists per account.
- Applies labels and moves disallowed mail to Trash via IMAP. Gmail auto-purges after 30 days.
- Exports a Gmail filter XML you import once per account so future mail auto-routes without further LLM calls.

## What it looks like

CLI:

```
$ python3 triage.py inventory primary@gmail.com
Connecting to IMAP for primary@gmail.com...
Total mail: 12,847
  Fetching batch 1/26 (500 mails)...
  ...
Inventory: data/primary@gmail.com/inventory.json
Report:    data/primary@gmail.com/report.md

$ python3 triage.py analyze primary@gmail.com
Using model: claude-opus-4-7
Mode: sender_subject, category source: preset
Classifying batch 1/4 (50 senders)...
Allowed list (132 senders):    data/primary@gmail.com/allowed.txt
Disallowed list (68 senders):  data/primary@gmail.com/disallowed.txt

$ python3 triage.py apply primary@gmail.com --dry-run
# Preview: prints every KEEP/TRASH action without touching Gmail.

$ python3 triage.py apply primary@gmail.com
# Live: applies labels, moves disallowed mail to Trash.

$ python3 triage.py undo primary@gmail.com
# Restores last apply's trashed senders from Trash back to All Mail.

$ python3 triage.py export-filters primary@gmail.com
# Writes filters.xml for one-time import in Gmail settings.

$ streamlit run app.py
# Or open http://localhost:8501 and do all of the above in the UI.
```

A Streamlit screenshot will live in `demos/screenshot-streamlit.png` once a sanitized run has been done. See [`demos/README.md`](demos/README.md) for what to drop there.

## How it works

```
.env (App Passwords + LLM key)
   |
   v
inventory   ->  IMAP read all mail  ->  inventory.json + report.md
   |
   v
analyze     ->  LLM classifies top senders  ->  allowed.txt + disallowed.txt
   |              (any LiteLLM-supported provider, see customize section)
   v
(you review the lists, edit if needed)
   |
   v
apply       ->  IMAP applies labels and moves disallowed to Trash
                     |
                     v
              Gmail auto-purges Trash after 30 days
```

Sender-centric: a typical inbox has a few hundred unique senders covering 90%+ of mail volume. Classify the senders once, apply the decision to all their mail. Only the top 200 senders are classified by default; the long tail stays untouched until you re-run.

## Quick start

```bash
git clone https://github.com/mertkayacs/gmail-cleaner-ai
cd gmail-cleaner-ai
bash install.sh                    # checks deps, copies .env.example, installs requirements
# edit .env: pick LLM_MODEL, add the matching API key, add Gmail accounts
python3 triage.py inventory <first-account>
python3 triage.py analyze <first-account>
streamlit run app.py
```

Prereqs: Python 3.10+, an LLM provider key (or Ollama locally), and Gmail App Passwords (`myaccount.google.com/apppasswords`, requires 2-Step Verification).

## Real examples

**Personal inbox with 8,000 mails.** 89% of mail came from 47 senders. Half were newsletters you forgot about. analyze proposes 23 keep / 24 trash. apply moves 4,200 mails to Trash. Inbox now usable.

**Work inbox with vendor noise.** Procurement vendors, marketing pings, and recruiter outreach drowning real PR replies. analyze tags `from:noreply@<vendor>` as junk_promo, keeps GitHub PR comments and direct sender mail. apply removes 1,800 noise mails.

**Old account about to be retired.** Bulk archive everything older than a year, label by category for posterity, leave Important/Starred mail alone.

## How to customize

### Built-in providers (via LiteLLM)

The classifier sits on top of [LiteLLM](https://github.com/BerriAI/litellm), which speaks 100+ provider APIs through one unified call. You pick a provider by setting `LLM_MODEL` to a model name with the right prefix.

| Provider | `LLM_MODEL` example | Env var |
|---|---|---|
| Anthropic | `claude-opus-4-7` | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Gemini | `gemini/gemini-2.5-pro` | `GEMINI_API_KEY` |
| Groq | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Together AI | `together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo` | `TOGETHERAI_API_KEY` |
| OpenRouter | `openrouter/anthropic/claude-opus-4-7` | `OPENROUTER_API_KEY` |
| Mistral | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` |
| Ollama (local) | `ollama/llama3.3` | none, `OLLAMA_HOST` for remote |
| LM Studio / llama.cpp | `openai/<your-model>` + `LLM_BASE_URL=http://localhost:...` | `OPENAI_API_KEY` (any string for fully local) |
| Anything else | See [LiteLLM provider docs](https://docs.litellm.ai/docs/providers) | |

The Streamlit UI ships with eleven provider presets (Anthropic, OpenAI, Gemini, Groq, Together AI, OpenRouter, Mistral, Ollama, LM Studio, llama.cpp server, Custom). Each preset auto-fills the model prefix, a starter list of models, and the relevant key var. A free-text override lets you type any LiteLLM-supported model.

Sidebar also exposes batch sizes (sender batch, top-sender cap, IMAP fetch size) under "Advanced settings" so you can tune for very large or very small inboxes without editing code.

### Use a different model or a custom endpoint

You don't subclass anything. LiteLLM already speaks the provider; you just point it.

**Cloud provider:** set `LLM_MODEL` to any [LiteLLM-supported model name](https://docs.litellm.ai/docs/providers) and the matching key var. Example:

```bash
# .env
LLM_MODEL=groq/llama-3.3-70b-versatile
GROQ_API_KEY=gsk_...
```

**Local OpenAI-compatible server (LM Studio, llama.cpp, vLLM):** prefix your model with `openai/` and set `LLM_BASE_URL`.

```bash
# .env
LLM_MODEL=openai/your-model-name
LLM_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=any-non-empty-string
```

**Ollama:** prefix with `ollama/`, no key needed.

```bash
# .env
LLM_MODEL=ollama/llama3.3
# OLLAMA_HOST=http://localhost:11434   # only if Ollama is remote
```

**Edit the taxonomy** by changing the prompt in `triage.py:build_classification_prompt`. Categories are JSON strings the LLM emits, and the apply step uses them as Gmail labels.

**Hard-rule safelist.** Add senders directly to `data/<account>/allowed.txt`. Bypasses the LLM and gets a guaranteed label.

## Why it works

- **Sender-centric, not per-mail.** Top 200 senders typically cover 90% of mail volume. Classify the senders once, apply the decision to all their mail.
- **Mail body never leaves your machine.** Sender, subject, and sample subjects go to the LLM. The body stays in Gmail.
- **Trash is recoverable.** Gmail keeps Trash for 30 days. Anything mis-classified can be restored within that window.
- **Provider-agnostic.** You pick the model. Switch providers in `.env` without touching code.

## Compared to alternatives

| Tool | Self-hosted | Multi-account | LLM-driven | Cost | Where mail flows |
|---|---|---|---|---|---|
| **gmail-cleaner-ai** | Yes | Yes | Yes (your provider) | API usage only (~$0.05–0.20 per account on Anthropic) | Your machine + chosen LLM |
| SaneBox | No | Yes | Heuristics | $60+/yr | Their servers |
| Gmail filters (built-in) | Yes | Per account, manual | No (rules only) | Free | Google |
| Cleanfox / Unroll.me | No | Yes | Heuristics | Free (resells data) | Their servers |
| Hey by Basecamp | No | Single | Manual curation | $99/yr | Their servers |

What gmail-cleaner-ai is **not** good for:

- Real-time per-mail classification on incoming mail. This is a batch tool.
- Composing or sending mail. Read-and-organize only.
- Setups where you cannot run Python locally.
- Inboxes under ~500 mails. The setup overhead outweighs the cleanup.

## Running tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/
```

23 tests in `tests/` cover the apply path (X-GM-RAW search, scope filter, STORE/MOVE error handling, crash-mid-loop log persistence), classifier retry/backoff, filters export from edited lists, header parsing, security-pattern sender skip, and undo. Add a regression test when you change behavior in `triage.py` or `lib/classifier.py`.

## Roadmap

- Sample data in `demos/` after the first sanitized run.
- Optional Gmail filter export from learned classifications, so filters do the ongoing work and the LLM only runs periodically.
- Per-account configurable taxonomies.
- Resume support for partial runs.

## Contributing

Open an issue with a clear repro before sending a PR. Provider additions welcome — see the customization section above.
