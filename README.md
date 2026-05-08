# gmail-cleaner-ai

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
Using AnthropicClassifier (model=claude-opus-4-7)
Classifying batch 1/4 (50 senders)...
Allowed list (132 senders):    data/primary@gmail.com/allowed.txt
Disallowed list (68 senders):  data/primary@gmail.com/disallowed.txt

$ streamlit run app.py
# Open http://localhost:8501, review the lists, click Apply.
```

Streamlit screenshot lives in `demos/screenshot-streamlit.png` (drop yours after first run).

## How it works

```
.env (App Passwords + LLM key)
   |
   v
inventory   ->  IMAP read all mail  ->  inventory.json + report.md
   |
   v
analyze     ->  LLM classifies top senders  ->  allowed.txt + disallowed.txt
   |              (Anthropic / OpenAI / Gemini / Ollama)
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
# edit .env: pick LLM_PROVIDER, add the matching API key, add Gmail accounts
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

**Add an LLM provider** in 10 lines. Implement a class extending `Classifier` in `lib/classifier.py`, register it in `PROVIDERS`, document the env vars in `.env.example`.

```python
# lib/classifier.py
class MyProviderClassifier(Classifier):
    DEFAULT_MODEL = "your-model"
    def __init__(self, model=None, api_key=None):
        # init your client
        ...
    def classify_batch(self, prompt):
        # call your API, return parsed JSON dict
        ...

PROVIDERS["myprovider"] = MyProviderClassifier
```

Then `LLM_PROVIDER=myprovider` in `.env` switches the whole pipeline.

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

## Roadmap

- Sample data in `demos/` after the first sanitized run.
- Optional Gmail filter export from learned classifications, so filters do the ongoing work and the LLM only runs periodically.
- Per-account configurable taxonomies.
- Resume support for partial runs.

## Contributing

Open an issue with a clear repro before sending a PR. Provider additions welcome — see the customization section above.
