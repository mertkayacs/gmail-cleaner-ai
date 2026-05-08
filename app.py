"""
Streamlit UI for gmail-cleaner-ai.

Run: streamlit run app.py

Single-page vertical card flow. No sidebar, no tabs. Mobile-first. Settings
forms write to .env so users never touch a terminal.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH, override=True)


# ============== Helpers: .env read/write ==============

def list_accounts():
    accounts = []
    for i in range(1, 21):
        email = os.environ.get(f"GMAIL_ACCOUNT_{i}")
        if email:
            accounts.append((i, email))
    return accounts


def next_account_slot():
    used = {i for i, _ in list_accounts()}
    for i in range(1, 21):
        if i not in used:
            return i
    return None


def update_env(updates: dict):
    """Append/update key=value lines in the .env file. Updates os.environ too."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    existing = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        existing[s.split("=", 1)[0].strip()] = i
    for k, v in updates.items():
        new_line = f"{k}={v}"
        if k in existing:
            lines[existing[k]] = new_line
        else:
            lines.append(new_line)
    ENV_PATH.write_text("\n".join(lines) + "\n")
    for k, v in updates.items():
        os.environ[k] = v


def remove_env_keys(keys):
    if not ENV_PATH.exists():
        return
    keys_set = set(keys)
    out = []
    for line in ENV_PATH.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            out.append(line)
            continue
        k = s.split("=", 1)[0].strip()
        if k not in keys_set:
            out.append(line)
    ENV_PATH.write_text("\n".join(out) + "\n")
    for k in keys:
        os.environ.pop(k, None)


def run_subcommand(cmd, args, status_placeholder):
    """Run python3 triage.py <cmd> in a subprocess and stream output."""
    env = os.environ.copy()
    passthrough = [
        "LLM_MODEL", "LLM_BASE_URL", "OLLAMA_HOST",
        "SENDER_BATCH_SIZE", "TOP_SENDER_CAP", "FETCH_BATCH_SIZE",
    ]
    for key in passthrough:
        if key in st.session_state and st.session_state[key]:
            env[key] = str(st.session_state[key])
    full = [sys.executable, str(ROOT / "triage.py"), cmd] + args
    proc = subprocess.Popen(
        full, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    output = []
    with status_placeholder:
        for line in proc.stdout:
            output.append(line.rstrip())
            st.code("\n".join(output[-200:]), language="text")
    rc = proc.wait()
    return rc, "\n".join(output)


def parse_list_file(path):
    if not path.exists():
        return pd.DataFrame(columns=["sender", "sublabel", "reasoning"])
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        rows.append({
            "sender": parts[0] if parts else "",
            "sublabel": parts[1] if len(parts) > 1 else "",
            "reasoning": parts[2] if len(parts) > 2 else "",
        })
    return pd.DataFrame(rows)


def write_list_file(path, header, df):
    lines = [
        f"# {header}",
        "# Format: sender@domain | sublabel | reasoning",
        "# Edit before running `apply`. Lines starting with # are ignored.",
        "",
    ]
    for _, row in df.iterrows():
        sender = str(row.get("sender", "")).strip()
        if not sender:
            continue
        sublabel = str(row.get("sublabel", "")).strip()
        reasoning = str(row.get("reasoning", "")).strip()
        lines.append(f"{sender} | {sublabel} | {reasoning}")
    path.write_text("\n".join(lines) + "\n")


PRESETS = {
    "Anthropic (Claude)": {
        "models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "base_url": None, "key_var": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com",
    },
    "OpenAI (GPT)": {
        "models": ["gpt-4o", "gpt-4o-mini"],
        "base_url": None, "key_var": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com",
    },
    "Gemini (Google)": {
        "models": ["gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash"],
        "base_url": None, "key_var": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "Groq (fast OSS inference)": {
        "models": ["groq/llama-3.3-70b-versatile", "groq/llama-3.1-8b-instant", "groq/gemma2-9b-it"],
        "base_url": None, "key_var": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
    },
    "Together AI (OSS hosted)": {
        "models": [
            "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "together_ai/mistralai/Mixtral-8x7B-Instruct-v0.1",
            "together_ai/google/gemma-2-27b-it",
        ],
        "base_url": None, "key_var": "TOGETHERAI_API_KEY",
        "key_url": "https://api.together.xyz/settings/api-keys",
    },
    "OpenRouter (catalog)": {
        "models": [
            "openrouter/anthropic/claude-opus-4-7",
            "openrouter/openai/gpt-4o",
            "openrouter/meta-llama/llama-3.3-70b-instruct",
            "openrouter/google/gemma-2-27b-it",
        ],
        "base_url": None, "key_var": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys",
    },
    "Mistral La Plateforme": {
        "models": ["mistral/mistral-large-latest", "mistral/mistral-medium-latest"],
        "base_url": None, "key_var": "MISTRAL_API_KEY",
        "key_url": "https://console.mistral.ai/api-keys",
    },
    "Ollama (local)": {
        "models": ["ollama/llama3.3", "ollama/llama3.1", "ollama/gemma3", "ollama/mistral", "ollama/qwen2.5", "ollama/phi4"],
        "base_url": "http://localhost:11434",
        "key_var": None, "key_url": "https://ollama.com",
    },
    "LM Studio (local)": {
        "models": [], "base_url": "http://localhost:1234/v1",
        "key_var": "OPENAI_API_KEY", "key_url": "https://lmstudio.ai",
    },
    "llama.cpp server (local)": {
        "models": [], "base_url": "http://localhost:8080/v1",
        "key_var": "OPENAI_API_KEY", "key_url": None,
    },
    "Custom (any LiteLLM model)": {
        "models": [], "base_url": "",
        "key_var": None, "key_url": "https://docs.litellm.ai/docs/providers",
    },
}


# ============== Page header ==============

st.set_page_config(page_title="gmail-cleaner-ai", page_icon=":mailbox:", layout="wide")

st.markdown(
    "<h1 style='font-family: monospace; font-weight: 600; margin-bottom: 0;'>"
    "gmail-cleaner-ai"
    "</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='color: #6b6357; margin-top: 4px;'>"
    "Sender-level Gmail cleanup. IMAP read, LLM classify, label, trash. "
    "BYOK, MIT, "
    "<a href='https://github.com/mertkayacs/gmail-cleaner-ai' style='color: #b85c00;'>github</a>."
    "</p>",
    unsafe_allow_html=True,
)

accounts_full = list_accounts()
accounts = [email for _, email in accounts_full]
ALL_KEY_VARS = [
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "GOOGLE_API_KEY", "GROQ_API_KEY", "TOGETHERAI_API_KEY",
    "OPENROUTER_API_KEY", "MISTRAL_API_KEY",
]
keys_count = sum(1 for v in ALL_KEY_VARS if os.environ.get(v))

# Compact status sentence. No emoji, no metric tiles.
if accounts and keys_count:
    status_msg = f"{len(accounts)} account{'s' if len(accounts) != 1 else ''} configured. {keys_count} provider key{'s' if keys_count != 1 else ''} set. Ready."
elif accounts:
    status_msg = f"{len(accounts)} account{'s' if len(accounts) != 1 else ''} configured. No provider key yet."
elif keys_count:
    status_msg = f"No Gmail account yet. {keys_count} provider key{'s' if keys_count != 1 else ''} set."
else:
    status_msg = "Add a Gmail App Password and an LLM key below to begin."
st.caption(status_msg)


# ============== Card 1: Setup ==============

with st.container(border=True):
    st.subheader("Setup")
    setup_col_acc, setup_col_llm = st.columns(2)

    # ---- Gmail accounts ----
    with setup_col_acc:
        st.markdown("**Gmail accounts**")

        if accounts_full:
            for slot, email in accounts_full:
                cols = st.columns([5, 1])
                cols[0].markdown(f"`{email}`")
                if cols[1].button("Remove", key=f"rm_acc_{slot}"):
                    remove_env_keys([f"GMAIL_ACCOUNT_{slot}", f"GMAIL_APPPASS_{slot}"])
                    st.rerun()

        with st.form("add_acc_form", clear_on_submit=True):
            st.caption(
                "Generate an App Password at [myaccount.google.com/apppasswords]"
                "(https://myaccount.google.com/apppasswords). Requires 2-Step Verification. "
                "Saved to your local `.env` (gitignored)."
            )
            new_email = st.text_input("Gmail address", placeholder="you@gmail.com")
            new_pass = st.text_input(
                "App Password",
                type="password",
                placeholder="16-char password from Google",
            )
            if st.form_submit_button("Add account", use_container_width=True, type="primary"):
                if not new_email or not new_pass:
                    st.error("Email and App Password both required.")
                else:
                    slot = next_account_slot()
                    if slot is None:
                        st.error("Account limit reached (20).")
                    else:
                        update_env({
                            f"GMAIL_ACCOUNT_{slot}": new_email.strip(),
                            f"GMAIL_APPPASS_{slot}": new_pass.strip(),
                        })
                        st.success(f"Saved {new_email.strip()}.")
                        st.rerun()

    # ---- LLM provider ----
    with setup_col_llm:
        st.markdown("**LLM provider**")
        preset_name = st.selectbox(
            "Provider",
            list(PRESETS.keys()),
            label_visibility="collapsed",
        )
        preset = PRESETS[preset_name]

        if preset["models"]:
            selected_model = st.selectbox("Model", preset["models"])
        else:
            selected_model = ""
        custom_model = st.text_input(
            "Custom model (overrides above)",
            "",
            placeholder="any LiteLLM-supported model name",
        )
        model = custom_model.strip() or selected_model

        base_url = preset.get("base_url") or ""
        if preset_name == "Custom (any LiteLLM model)":
            base_url = st.text_input("Base URL", base_url, placeholder="https://your-provider.com/v1")
        elif base_url:
            st.caption(f"Base URL: `{base_url}`")

        is_ollama = preset_name.startswith("Ollama")
        ollama_host = ""
        if is_ollama:
            ollama_host = st.text_input("Ollama host", os.environ.get("OLLAMA_HOST", "http://localhost:11434"))

        key_var = preset.get("key_var")
        if key_var:
            existing_key = os.environ.get(key_var, "")
            if existing_key:
                masked = (existing_key[:6] + "…" + existing_key[-4:]) if len(existing_key) > 12 else "set"
                st.markdown(f"`{key_var}` set ({masked})")
            else:
                url = preset.get("key_url")
                msg = f"`{key_var}` not set"
                if url:
                    msg += f". Get one at [{url}]({url})."
                st.markdown(msg)
            with st.form(f"set_key_form_{key_var}", clear_on_submit=True):
                new_key = st.text_input(
                    f"Paste {key_var}",
                    type="password",
                    label_visibility="collapsed",
                    placeholder=f"paste {key_var} here",
                )
                if st.form_submit_button("Save key", use_container_width=True, type="primary"):
                    if not new_key:
                        st.error("Key required.")
                    else:
                        update_env({key_var: new_key.strip()})
                        st.success(f"Saved {key_var}.")
                        st.rerun()
        elif is_ollama:
            url = preset.get("key_url")
            note = "Ollama runs locally, no API key needed"
            if url:
                note += f". Install from [{url}]({url})"
            st.caption(note)

    # Advanced (small expander, full-width within the card)
    with st.expander("Advanced (batch sizes)"):
        adv1, adv2, adv3 = st.columns(3)
        with adv1:
            sender_batch_size = st.number_input("Sender batch size", min_value=1, max_value=500, value=50, step=10)
        with adv2:
            top_sender_cap = st.number_input("Top sender cap", min_value=10, max_value=2000, value=200, step=50)
        with adv3:
            fetch_batch_size = st.number_input("IMAP fetch batch size", min_value=50, max_value=2000, value=500, step=50)


# Persist runtime settings to session
st.session_state["LLM_MODEL"] = model
st.session_state["LLM_BASE_URL"] = base_url
st.session_state["OLLAMA_HOST"] = ollama_host
try:
    st.session_state["SENDER_BATCH_SIZE"] = str(sender_batch_size)
    st.session_state["TOP_SENDER_CAP"] = str(top_sender_cap)
    st.session_state["FETCH_BATCH_SIZE"] = str(fetch_batch_size)
except NameError:
    pass


# ============== Gating: must have at least one account before continuing ==============

if not accounts:
    st.stop()


# ============== Account picker (between cards 1 and 2 if multiple) ==============

if len(accounts) == 1:
    account = accounts[0]
else:
    account = st.selectbox(
        "Pick which account to work on",
        accounts,
        key="account_picker",
    )

acc_dir = DATA_DIR / account
inv_path = acc_dir / "inventory.json"
cats_path = acc_dir / "proposed_categories.json"
allowed_path = acc_dir / "allowed.txt"
disallowed_path = acc_dir / "disallowed.txt"
log_path = acc_dir / "applied.log"
xml_path = acc_dir / "filters.xml"


# ============== Card 2: Run (Inventory + Classify) ==============

with st.container(border=True):
    st.subheader("Scan and classify")

    # ---- Scan inbox (inventory) ----
    st.markdown("**Scan inbox.** IMAP-only. Reads sender, subject, headers. Body stays in Gmail.")
    if st.button("Scan inbox", type="primary", use_container_width=True, key="btn_inv"):
        with st.status(
            f"Scanning {account} (a few minutes for big mailboxes)...",
            expanded=True,
        ) as status:
            rc, _ = run_subcommand("inventory", [account], st.empty())
            status.update(
                label="Scan done." if rc == 0 else f"Scan failed (exit {rc}).",
                state="complete" if rc == 0 else "error",
            )
    if inv_path.exists():
        inv = json.loads(inv_path.read_text())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", f"{inv['total_mails']:,}")
        c2.metric("Senders", f"{inv['unique_senders']:,}")
        c3.metric("Domains", f"{inv['unique_domains']:,}")
        c4.metric("Unsubscribable", f"{inv['has_list_unsubscribe']:,}")

    st.markdown("")

    # ---- Classify (analyze) ----
    classify_disabled = not inv_path.exists()
    st.markdown(f"**Classify.** Top senders sent to `{model or 'default model'}`. Sender plus three sample subjects, no body.")
    if st.button(
        "Classify",
        type="primary",
        use_container_width=True,
        disabled=classify_disabled,
        key="btn_an",
    ):
        with st.status(f"Classifying senders for {account}...", expanded=True) as status:
            rc, _ = run_subcommand("analyze", [account], st.empty())
            status.update(
                label="Classification done." if rc == 0 else f"Failed (exit {rc}).",
                state="complete" if rc == 0 else "error",
            )
    if classify_disabled:
        st.caption("Run the scan first.")
    if cats_path.exists():
        cats = json.loads(cats_path.read_text())
        cat_summary = [
            {"category": c, "senders": len(s)}
            for c, s in cats.get("categories", {}).items()
        ]
        st.dataframe(
            pd.DataFrame(cat_summary).sort_values("senders", ascending=False),
            use_container_width=True,
            hide_index=True,
        )


# ============== Card 3: Review ==============

with st.container(border=True):
    st.subheader("Review")
    review_ready = allowed_path.exists() or disallowed_path.exists()
    if not review_ready:
        st.caption("Run Classify first. Tables below populate from the model's output.")
    st.markdown(
        "Edit each table and **Save**. Move a sender between Allowed and Disallowed by editing it. "
        "The Apply step reads these files."
    )

    df_a = parse_list_file(allowed_path)
    df_d = parse_list_file(disallowed_path)

    rev_col_a, rev_col_d = st.columns(2)
    with rev_col_a:
        st.markdown(f"**Allowed (keep) — {len(df_a)} senders**")
        edited_a = st.data_editor(
            df_a, num_rows="dynamic", use_container_width=True, key="ed_allowed"
        )
        if st.button("Save allowed", use_container_width=True, key="btn_save_a"):
            write_list_file(allowed_path, "Allowed senders (keep)", edited_a)
            st.success("Saved.")
    with rev_col_d:
        st.markdown(f"**Disallowed (Trash) — {len(df_d)} senders**")
        edited_d = st.data_editor(
            df_d, num_rows="dynamic", use_container_width=True, key="ed_disallowed"
        )
        if st.button("Save disallowed", use_container_width=True, key="btn_save_d"):
            write_list_file(disallowed_path, "Disallowed senders (move to Trash)", edited_d)
            st.success("Saved.")


# ============== Card 4: Apply ==============

with st.container(border=True):
    st.subheader("Apply")
    apply_disabled = not (allowed_path.exists() or disallowed_path.exists())
    if apply_disabled:
        st.caption("Save reviewed lists first.")
    st.markdown(
        "Apply your reviewed lists. Allowed senders get sublabels; Disallowed senders' mail moves to Trash. "
        "**Trash is recoverable for 30 days**, then Gmail auto-purges."
    )

    apply_col_dry, apply_col_live = st.columns(2)
    with apply_col_dry:
        if st.button(
            "Dry-run (preview only)",
            use_container_width=True,
            disabled=apply_disabled,
            key="btn_dry",
        ):
            with st.status(f"Dry-run on {account}...", expanded=True) as status:
                rc, _ = run_subcommand("apply", [account, "--dry-run"], st.empty())
                status.update(
                    label="Dry-run done." if rc == 0 else f"Failed (exit {rc}).",
                    state="complete" if rc == 0 else "error",
                )
    with apply_col_live:
        confirm_live = st.checkbox(
            "I understand: this writes to Gmail (Trash recoverable 30 days)",
            key="confirm_live",
        )
        if st.button(
            "Apply LIVE",
            type="primary",
            use_container_width=True,
            disabled=apply_disabled or not confirm_live,
            key="btn_live",
        ):
            with st.status(f"Applying on {account}...", expanded=True) as status:
                rc, _ = run_subcommand("apply", [account], st.empty())
                status.update(
                    label="Apply done." if rc == 0 else f"Failed (exit {rc}).",
                    state="complete" if rc == 0 else "error",
                )

    if log_path.exists():
        with st.expander("Audit log"):
            st.code(log_path.read_text(), language="text")

    st.markdown("---")
    st.markdown(
        "**Generate Gmail filter XML** — import once per account in Gmail Settings → Filters → Import filters. "
        "Future mail then auto-routes by sender, no LLM calls."
    )
    if st.button(
        "Generate filters.xml",
        use_container_width=True,
        disabled=apply_disabled,
        key="btn_filters",
    ):
        with st.status("Generating XML...", expanded=False) as status:
            rc, _ = run_subcommand("export-filters", [account], st.empty())
            status.update(
                label="Generated." if rc == 0 else f"Failed (exit {rc}).",
                state="complete" if rc == 0 else "error",
            )
    if xml_path.exists():
        st.download_button(
            "Download filters.xml",
            xml_path.read_bytes(),
            file_name=f"{account.replace('@', '-at-')}-filters.xml",
            mime="application/xml",
            use_container_width=True,
        )
