"""
Streamlit UI for gmail-cleaner-ai.

Run: streamlit run app.py

Sidebar selects account and provider. Tabs show inventory, analyze progress,
editable allowed/disallowed lists, and the apply audit log.
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
load_dotenv(ROOT / ".env")


def list_accounts():
    accounts = []
    for i in range(1, 21):
        email = os.environ.get(f"GMAIL_ACCOUNT_{i}")
        if email:
            accounts.append(email)
    return accounts


def run_subcommand(cmd, args, status_placeholder):
    """Stream a `python3 triage.py <cmd>` invocation into a Streamlit container.

    Passes UI-configured settings to the subprocess via environment variables.
    """
    env = os.environ.copy()
    passthrough = [
        "LLM_MODEL", "LLM_BASE_URL", "OLLAMA_HOST",
        "SENDER_BATCH_SIZE", "TOP_SENDER_CAP", "FETCH_BATCH_SIZE",
    ]
    for key in passthrough:
        if key in st.session_state and st.session_state[key]:
            env[key] = str(st.session_state[key])
        elif key in env and not env.get(key):
            env.pop(key, None)
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


PRESETS = {
    "Anthropic (Claude)": {
        "models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "base_url": None,
        "key_var": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com",
    },
    "OpenAI (GPT)": {
        "models": ["gpt-4o", "gpt-4o-mini"],
        "base_url": None,
        "key_var": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com",
    },
    "Gemini (Google)": {
        "models": ["gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash"],
        "base_url": None,
        "key_var": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "Groq (fast OSS inference)": {
        "models": [
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.1-8b-instant",
            "groq/gemma2-9b-it",
        ],
        "base_url": None,
        "key_var": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
    },
    "Together AI (OSS hosted)": {
        "models": [
            "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "together_ai/mistralai/Mixtral-8x7B-Instruct-v0.1",
            "together_ai/google/gemma-2-27b-it",
        ],
        "base_url": None,
        "key_var": "TOGETHERAI_API_KEY",
        "key_url": "https://api.together.xyz/settings/api-keys",
    },
    "OpenRouter (catalog)": {
        "models": [
            "openrouter/anthropic/claude-opus-4-7",
            "openrouter/openai/gpt-4o",
            "openrouter/meta-llama/llama-3.3-70b-instruct",
            "openrouter/google/gemma-2-27b-it",
        ],
        "base_url": None,
        "key_var": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys",
    },
    "Mistral La Plateforme": {
        "models": ["mistral/mistral-large-latest", "mistral/mistral-medium-latest"],
        "base_url": None,
        "key_var": "MISTRAL_API_KEY",
        "key_url": "https://console.mistral.ai/api-keys",
    },
    "Ollama (local)": {
        "models": [
            "ollama/llama3.3", "ollama/llama3.1", "ollama/gemma3",
            "ollama/mistral", "ollama/qwen2.5", "ollama/phi4",
        ],
        "base_url": "http://localhost:11434",
        "key_var": None,
        "key_url": "https://ollama.com",
    },
    "LM Studio (local)": {
        "models": [],
        "base_url": "http://localhost:1234/v1",
        "key_var": "OPENAI_API_KEY",
        "key_url": "https://lmstudio.ai",
        "model_hint": "Prefix with `openai/` (e.g., `openai/qwen2.5-coder:32b`)",
    },
    "llama.cpp server (local)": {
        "models": [],
        "base_url": "http://localhost:8080/v1",
        "key_var": "OPENAI_API_KEY",
        "key_url": None,
        "model_hint": "Prefix with `openai/` (e.g., `openai/llama-3.3-70b`)",
    },
    "Custom (any LiteLLM model)": {
        "models": [],
        "base_url": "",
        "key_var": None,
        "key_url": "https://docs.litellm.ai/docs/providers",
        "model_hint": "Use any LiteLLM-supported model. See docs for the prefix format.",
    },
}


def parse_list_file(path):
    rows = []
    if not path.exists():
        return pd.DataFrame(columns=["sender", "sublabel", "reasoning"])
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        sender = parts[0] if parts else ""
        sublabel = parts[1] if len(parts) > 1 else ""
        reasoning = parts[2] if len(parts) > 2 else ""
        rows.append({"sender": sender, "sublabel": sublabel, "reasoning": reasoning})
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


# ============== UI ==============

st.set_page_config(page_title="gmail-cleaner-ai", page_icon=":mailbox:", layout="wide")

# Header
st.title(":mailbox: gmail-cleaner-ai")
st.markdown(
    "**Clean up multiple Gmail accounts with whichever LLM you trust.** "
    "Open source, MIT licensed. "
    "[GitHub](https://github.com/mertkayacs/gmail-cleaner-ai)"
)

# Setup status (always visible; expanded when nothing is configured)
accounts = list_accounts()
provider_keys = {
    "Anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
    "OpenAI": bool(os.environ.get("OPENAI_API_KEY")),
    "Gemini": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    "Groq": bool(os.environ.get("GROQ_API_KEY")),
    "Together AI": bool(os.environ.get("TOGETHERAI_API_KEY")),
    "OpenRouter": bool(os.environ.get("OPENROUTER_API_KEY")),
    "Mistral": bool(os.environ.get("MISTRAL_API_KEY")),
}

with st.expander("Setup status", expanded=not accounts):
    col_a, col_b = st.columns([1, 1])
    with col_a:
        st.markdown("**Gmail accounts**")
        if accounts:
            for a in accounts:
                st.markdown(f"- :white_check_mark: `{a}`")
        else:
            st.markdown("- :x: none configured")
    with col_b:
        st.markdown("**LLM provider keys**")
        for name, present in provider_keys.items():
            mark = ":white_check_mark:" if present else ":x:"
            st.markdown(f"- {mark} {name}")
        st.markdown("- :information_source: Ollama (local, no key required)")

# First-time setup view, shown only when no accounts are configured.
if not accounts:
    st.markdown("---")
    st.subheader("First-time setup")
    st.markdown(
        """
Two things to set up. Both go in a `.env` file in the project root.

**1. Gmail App Password** (per account, ~30 sec each)
- Visit [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (requires 2-Step Verification on the Gmail account)
- Generate one named "gmail-cleaner-ai" and copy the 16-character password
- Add to `.env` as `GMAIL_ACCOUNT_n` and `GMAIL_APPPASS_n` (n=1, 2, 3...)

**2. LLM API key** (pick any one provider, set its key in `.env`)
- **Anthropic** (Claude): [console.anthropic.com](https://console.anthropic.com) — `ANTHROPIC_API_KEY`
- **OpenAI** (GPT): [platform.openai.com](https://platform.openai.com) — `OPENAI_API_KEY`
- **Gemini** (Google): [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — `GEMINI_API_KEY`
- **Groq** (fast OSS): [console.groq.com](https://console.groq.com/keys) — `GROQ_API_KEY`
- **Together AI**: [together.xyz](https://api.together.xyz/settings/api-keys) — `TOGETHERAI_API_KEY`
- **OpenRouter**: [openrouter.ai](https://openrouter.ai/keys) — `OPENROUTER_API_KEY`
- **Mistral**: [console.mistral.ai](https://console.mistral.ai/api-keys) — `MISTRAL_API_KEY`
- **Ollama** (local, no key): [ollama.com](https://ollama.com)
- **Anything else**: see [LiteLLM provider docs](https://docs.litellm.ai/docs/providers)

After saving `.env`, refresh this page.
        """
    )
    st.markdown("Source: [github.com/mertkayacs/gmail-cleaner-ai](https://github.com/mertkayacs/gmail-cleaner-ai)")
    st.stop()

# Sidebar (only reached when at least one account is configured)
account = st.sidebar.selectbox("Account", accounts)

st.sidebar.markdown("---")
st.sidebar.subheader("LLM provider")

preset_names = list(PRESETS.keys())
preset_name = st.sidebar.selectbox(
    "Provider preset",
    preset_names,
    help="Pick a preset to auto-configure provider, base URL, and suggested models.",
)
preset = PRESETS[preset_name]

# Model
preset_models = preset["models"]
if preset_models:
    selected_model = st.sidebar.selectbox("Suggested model", preset_models)
else:
    selected_model = ""
custom_model = st.sidebar.text_input(
    "Custom model name (overrides above)",
    "",
    help="Type any model name your provider supports. Newer models work even if not in the suggested list.",
)
model = custom_model.strip() or selected_model

# Base URL handling
base_url = preset.get("base_url") or ""
if preset_name == "Custom OpenAI-compatible":
    base_url = st.sidebar.text_input(
        "Base URL",
        base_url,
        placeholder="https://your-provider.com/v1",
        help="OpenAI-compatible chat completions endpoint.",
    )
elif base_url:
    st.sidebar.caption(f"Base URL: `{base_url}`")

is_ollama = preset_name.startswith("Ollama")

# Ollama host
ollama_host = ""
if is_ollama:
    ollama_host = st.sidebar.text_input(
        "Ollama host",
        os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    )

# Key status
key_var = preset.get("key_var")
if key_var:
    if os.environ.get(key_var):
        st.sidebar.caption(f":white_check_mark: `{key_var}` is set in .env")
    else:
        url = preset.get("key_url")
        msg = f":x: `{key_var}` missing in .env"
        if url:
            msg += f" — get one at [{url}]({url})"
        st.sidebar.caption(msg)
elif is_ollama:
    url = preset.get("key_url")
    note = "Ollama runs locally, no API key needed"
    if url:
        note += f" — install from [{url}]({url})"
    st.sidebar.caption(f":information_source: {note}")

# Advanced settings
with st.sidebar.expander("Advanced settings"):
    sender_batch_size = st.number_input(
        "Sender batch size",
        min_value=1, max_value=500, value=50, step=10,
        help="Senders per LLM call. Smaller = more calls but more responsive.",
    )
    top_sender_cap = st.number_input(
        "Top sender cap",
        min_value=10, max_value=2000, value=200, step=50,
        help="Process only the top N senders by mail volume. Larger inboxes can use more.",
    )
    fetch_batch_size = st.number_input(
        "IMAP fetch batch size",
        min_value=50, max_value=2000, value=500, step=50,
        help="Mails per IMAP FETCH call. Don't change unless you hit timeouts.",
    )

# Persist settings to session state. LiteLLM derives the provider from the model
# prefix, so we don't store a separate LLM_PROVIDER value.
st.session_state["LLM_MODEL"] = model
st.session_state["LLM_BASE_URL"] = base_url
st.session_state["OLLAMA_HOST"] = ollama_host
st.session_state["SENDER_BATCH_SIZE"] = str(sender_batch_size)
st.session_state["TOP_SENDER_CAP"] = str(top_sender_cap)
st.session_state["FETCH_BATCH_SIZE"] = str(fetch_batch_size)

st.sidebar.markdown("---")
st.sidebar.subheader("Run")
run_inv = st.sidebar.button("Run inventory", use_container_width=True)
run_an = st.sidebar.button("Run analyze", use_container_width=True)
run_dry = st.sidebar.button("Run apply (dry-run)", use_container_width=True)
run_live = st.sidebar.button("Run apply (LIVE)", use_container_width=True, type="primary")

# ============== Main ==============

st.title(f":mailbox: {account}")

tab_inv, tab_an, tab_lists, tab_apply = st.tabs(
    ["Inventory", "Analyze", "Lists", "Apply log"]
)

acc_dir = DATA_DIR / account

with tab_inv:
    if run_inv:
        st.info(f"Running inventory on {account}...")
        rc, _ = run_subcommand("inventory", [account], st.empty())
        if rc == 0:
            st.success("Inventory done.")
        else:
            st.error(f"Inventory failed (exit {rc}).")
    inv_path = acc_dir / "inventory.json"
    if inv_path.exists():
        inv = json.loads(inv_path.read_text())
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total mails", f"{inv['total_mails']:,}")
        col2.metric("Unique senders", f"{inv['unique_senders']:,}")
        col3.metric("Unique domains", f"{inv['unique_domains']:,}")
        col4.metric("With unsubscribe", f"{inv['has_list_unsubscribe']:,}")

        st.subheader("Top 50 senders")
        df_sen = pd.DataFrame(inv["top_senders"][:50], columns=["sender", "count"])
        st.dataframe(df_sen, use_container_width=True, hide_index=True)

        st.subheader("Top 25 domains")
        df_dom = pd.DataFrame(inv["top_domains"][:25], columns=["domain", "count"])
        st.dataframe(df_dom, use_container_width=True, hide_index=True)
    else:
        st.info("No inventory yet. Click 'Run inventory' in the sidebar.")

with tab_an:
    if run_an:
        st.info(f"Running analyze on {account} (model={model or 'default'})...")
        rc, _ = run_subcommand("analyze", [account], st.empty())
        if rc == 0:
            st.success("Analyze done. Review the Lists tab.")
        else:
            st.error(f"Analyze failed (exit {rc}).")
    cats_path = acc_dir / "proposed_categories.json"
    if cats_path.exists():
        cats = json.loads(cats_path.read_text())
        st.subheader("Categories proposed")
        cat_summary = [
            {"category": c, "senders": len(s)}
            for c, s in cats.get("categories", {}).items()
        ]
        st.dataframe(
            pd.DataFrame(cat_summary).sort_values("senders", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

with tab_lists:
    st.markdown(
        "Edit either list and click **Save**. The `apply` step reads these files. "
        "Move a sender between lists or change its sublabel anytime."
    )
    allowed_path = acc_dir / "allowed.txt"
    disallowed_path = acc_dir / "disallowed.txt"

    col_a, col_d = st.columns(2)
    with col_a:
        st.subheader("Allowed (keep)")
        df_a = parse_list_file(allowed_path)
        edited_a = st.data_editor(
            df_a, num_rows="dynamic", use_container_width=True, key="ed_allowed"
        )
        if st.button("Save allowed"):
            write_list_file(allowed_path, "Allowed senders (keep)", edited_a)
            st.success("Saved.")
    with col_d:
        st.subheader("Disallowed (move to Trash)")
        df_d = parse_list_file(disallowed_path)
        edited_d = st.data_editor(
            df_d, num_rows="dynamic", use_container_width=True, key="ed_disallowed"
        )
        if st.button("Save disallowed"):
            write_list_file(disallowed_path, "Disallowed senders (move to Trash)", edited_d)
            st.success("Saved.")

with tab_apply:
    if run_dry:
        st.info(f"Dry-run apply on {account}...")
        rc, _ = run_subcommand("apply", [account, "--dry-run"], st.empty())
        if rc == 0:
            st.success("Dry-run done.")
        else:
            st.error(f"Dry-run failed (exit {rc}).")
    if run_live:
        confirm = st.checkbox(
            "I understand this will modify Gmail (apply labels, move to Trash). "
            "Mail in Trash is recoverable for 30 days, then auto-purged."
        )
        if confirm and st.button("Confirm and apply LIVE", type="primary"):
            rc, _ = run_subcommand("apply", [account], st.empty())
            if rc == 0:
                st.success("Apply done.")
            else:
                st.error(f"Apply failed (exit {rc}).")
    log_path = acc_dir / "applied.log"
    if log_path.exists():
        st.subheader("Audit log")
        st.code(log_path.read_text(), language="text")
    else:
        st.info("No apply has been run yet.")

    st.markdown("---")
    st.subheader("Export Gmail filter XML")
    st.markdown(
        "Generate `filters.xml` from your finalized lists. Import once per account "
        "(Gmail Settings -> See all settings -> Filters and Blocked Addresses -> "
        "Import filters -> check 'Apply new filters to existing email'). "
        "After that, NEW incoming mail auto-routes by sender, no LLM calls."
    )
    if st.button("Generate filters.xml"):
        rc, _ = run_subcommand("export-filters", [account], st.empty())
        if rc != 0:
            st.error(f"Export failed (exit {rc}).")
    xml_path = acc_dir / "filters.xml"
    if xml_path.exists():
        st.download_button(
            "Download filters.xml",
            xml_path.read_bytes(),
            file_name=f"{account.replace('@', '-at-')}-filters.xml",
            mime="application/xml",
        )
