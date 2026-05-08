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
    """Stream a `python3 triage.py <cmd>` invocation into a Streamlit container."""
    full = [sys.executable, str(ROOT / "triage.py"), cmd] + args
    proc = subprocess.Popen(
        full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    output = []
    with status_placeholder:
        for line in proc.stdout:
            output.append(line.rstrip())
            st.code("\n".join(output[-200:]), language="text")
    rc = proc.wait()
    return rc, "\n".join(output)


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
    "OpenAI / OpenAI-compatible": bool(os.environ.get("OPENAI_API_KEY")),
    "Gemini": bool(os.environ.get("GOOGLE_API_KEY")),
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

**2. LLM API key** (pick any one)
- **Anthropic** (Claude): [console.anthropic.com](https://console.anthropic.com), set `ANTHROPIC_API_KEY`
- **OpenAI** (GPT): [platform.openai.com](https://platform.openai.com), set `OPENAI_API_KEY`
- **Gemini** (Google): [aistudio.google.com/apikey](https://aistudio.google.com/apikey), set `GOOGLE_API_KEY`
- **Ollama** (open-source models, local): install from [ollama.com](https://ollama.com), no key
- **Any OpenAI-compatible API** (OpenRouter, Together AI, Groq, Mistral, vLLM, LM Studio, llama.cpp): set `LLM_PROVIDER=openai` plus `LLM_BASE_URL=<endpoint>` and put that provider's key in `OPENAI_API_KEY`

After saving `.env`, refresh this page.
        """
    )
    st.markdown("Source: [github.com/mertkayacs/gmail-cleaner-ai](https://github.com/mertkayacs/gmail-cleaner-ai)")
    st.stop()

# Sidebar (only reached when at least one account is configured)
account = st.sidebar.selectbox("Account", accounts)

st.sidebar.markdown("---")
st.sidebar.subheader("LLM Provider")
provider = st.sidebar.selectbox(
    "Provider",
    ["anthropic", "openai", "gemini", "ollama"],
    index=["anthropic", "openai", "gemini", "ollama"].index(
        os.environ.get("LLM_PROVIDER", "anthropic")
    ),
)
model_override = st.sidebar.text_input("Model (blank = provider default)", "")
if model_override:
    os.environ["LLM_MODEL"] = model_override
elif "LLM_MODEL" in os.environ:
    del os.environ["LLM_MODEL"]
os.environ["LLM_PROVIDER"] = provider

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
        st.info(f"Running analyze on {account} (provider={provider})...")
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
