# PRODUCT.md

## Register
product

It is a tool. Design serves the function. The interface gets out of the way; the user runs through inventory → classify → review → apply and shuts the laptop.

## Users

- **Open-source evaluators**: arrive from GitHub, decide in under two minutes whether to clone. Need to see what it does, that it can be run today, and that it is worth their time.
- **Power users with multiple Gmail accounts**: 5+ accounts, 10k+ mails each, fed up with marketing noise. Want to run the tool monthly, review the lists, click apply, move on.
- **Mert Kaya**: AI engineer, owns the project. Runs from his Mac. Mobile-first habit from Termius, but uses the Streamlit UI from the desktop.

## Product purpose

Clean up multiple Gmail accounts using whichever LLM the user trusts. Read mail metadata via IMAP (App Password, no OAuth and no Google Cloud project), classify senders via LiteLLM (100+ providers), apply labels and Trash via IMAP. Single-page Streamlit UI, no terminal required.

The whole tool is BYOK: the user provides their Gmail App Password, their LLM key. Nothing leaves the user's machine except the metadata sent to their chosen LLM (subject + sender + sample subjects, never the body). Trash is recoverable for 30 days, then Gmail auto-purges.

## Brand voice / tone

- Direct. No fluff. No marketing words.
- Lower-case, monospace-friendly. The product header is `:mailbox: gmail-cleaner-ai`, not a polished logotype.
- Honest about limits: "not for inboxes under 500 mails", "not for real-time per-mail classification".
- Plain English. Banned phrases: "leverage", "robust", "comprehensive", "powerful", "seamless", "cutting-edge", "game-changer", "dive into", "at the end of the day".
- No em dashes anywhere.

## Anti-references

The interface should NOT look like:

- A SaaS landing page with hero-metric tiles and a gradient CTA.
- A polished consumer product. This is a tool for people who already know what they want.
- A finance app (no navy + gold).
- A medtech app (no white + teal).
- A crypto / observability dashboard (no neon-on-black, no "monitor for SREs at 2 a.m." palette).
- A general-purpose AI chat product (no center-stage chat bubbles).
- An onboarding flow that hides the data behind a wizard. The user can always see where they are in the four-step flow.

Aesthetic family to AVOID: dark-mode-tech-product. We are not that.

## Strategic principles

- **Single-page, vertical card flow.** No sidebar (mobile collapses it). No tabs (fragments first-time use). Cards stack top to bottom; later cards stay disabled or hidden until prereqs are met.
- **BYOK.** Every credential is the user's. The tool never embeds keys.
- **Trash, never permanent delete.** All destructive paths leave a 30-day recovery window.
- **Provider-agnostic via LiteLLM.** Switching providers is one dropdown, not a rewrite.
- **Terminal-replaceable.** Anything in the UI can also be done via `triage.py` from a shell. The UI is the friendly path, not the only path.
- **Audit-everything.** Every apply writes to `applied.log`; every classification writes to `proposed_categories.json`. The user can always see what the AI decided and why.

## Out of scope

- Real-time per-mail classification (this is batch).
- Composing or sending mail.
- Permanent delete on demand (Gmail's 30-day auto-purge handles it).
- Cross-account unified view.
