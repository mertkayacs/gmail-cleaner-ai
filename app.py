"""
Streamlit UI for gmail-cleaner-ai.

Run: streamlit run app.py

Single-page vertical card flow. No sidebar, no tabs. Settings forms write
to .env so users never touch a terminal.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Import the actual prompt builder triage.py uses so the preview pane shows
# what really gets sent, not a stale copy. triage.py is in the same directory.
from triage import build_classification_prompt

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
        "CLASSIFY_MODE", "BODY_LINES",
        "SENDERS", "CATEGORY_SOURCE",
        "APPLY_CATEGORIES",
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


def file_age(path):
    """Human-readable age of a file's last-modified time. None if missing."""
    if not path.exists():
        return None
    elapsed = time.time() - path.stat().st_mtime
    if elapsed < 60:
        return "just now"
    if elapsed < 3600:
        return f"{int(elapsed // 60)}m ago"
    if elapsed < 86400:
        return f"{int(elapsed // 3600)}h ago"
    return f"{int(elapsed // 86400)}d ago"


def parse_list_file(path):
    """Read a sender list file, split the sublabel into category + tag columns.

    File format on disk stays 'sender | sublabel | reasoning' for backward
    compat with existing allowed.txt / disallowed.txt files. The sublabel
    is conventionally 'Category/Tag' (e.g., 'Newsletter/TechDigest'), so
    we split on the first slash. Files that pre-date this convention will
    have an empty tag, which is fine.
    """
    if not path.exists():
        return pd.DataFrame(columns=["sender", "category", "tag", "reasoning"])
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        sender = parts[0] if parts else ""
        sublabel = parts[1] if len(parts) > 1 else ""
        reasoning = parts[2] if len(parts) > 2 else ""
        if "/" in sublabel:
            cat, tag = sublabel.split("/", 1)
        else:
            cat, tag = sublabel, ""
        rows.append({
            "sender": sender,
            "category": cat.strip(),
            "tag": tag.strip(),
            "reasoning": reasoning,
        })
    return pd.DataFrame(rows, columns=["sender", "category", "tag", "reasoning"])


def write_list_file(path, header, df):
    """Recombine category + tag back into the on-disk 'Category/Tag' sublabel
    so existing tooling (triage.py apply step, filters export) keeps working
    with the same file format."""
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
        cat = str(row.get("category", "")).strip()
        tag = str(row.get("tag", "")).strip()
        if cat and tag:
            sublabel = f"{cat}/{tag}"
        else:
            sublabel = cat or tag
        reasoning = str(row.get("reasoning", "")).strip()
        lines.append(f"{sender} | {sublabel} | {reasoning}")
    path.write_text("\n".join(lines) + "\n")


def section_heading(text: str):
    """Lowercase monospace H2 used for each card. Matches the brand voice
    declared in PRODUCT.md (lowercase, monospace) which Streamlit's default
    st.subheader cannot deliver."""
    st.markdown(
        f"<h2 style='font-family: monospace; font-weight: 600; "
        f"font-size: 1.2rem; margin: 0 0 12px 0;'>{text.lower()}</h2>",
        unsafe_allow_html=True,
    )


def estimate_classify_cost(model: str, sample_prompt: str, n_batches: int) -> str:
    """Best-effort $ estimate for a classify run, rendered as a caption.

    Uses LiteLLM's token_counter and model_cost. Returns "" when the model
    has no known pricing (Ollama, LM Studio, custom local servers) so the
    caller can suppress the line entirely."""
    try:
        from litellm import token_counter, model_cost
    except Exception:
        return ""
    try:
        in_per = token_counter(model=model, text=sample_prompt)
    except Exception:
        return ""
    in_total = in_per * n_batches
    # Output JSON is short relative to input. ~800 tokens per batch is a
    # generous upper bound for the schema we ask for.
    out_total = 800 * n_batches
    info = model_cost.get(model) or {}
    in_rate = info.get("input_cost_per_token")
    out_rate = info.get("output_cost_per_token")
    if in_rate is None or out_rate is None:
        return (
            f"≈ {in_total:,} input tokens across {n_batches} call"
            f"{'s' if n_batches != 1 else ''}; cost estimate unavailable "
            f"for `{model}`."
        )
    total = in_total * in_rate + out_total * out_rate
    return (
        f"≈ ${total:.4f} estimated "
        f"({in_total:,} input + ~{out_total:,} output tokens)."
    )


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

st.set_page_config(page_title="gmail cleaner ai", page_icon=":mailbox:", layout="wide")

st.markdown(
    "<h1 style='font-family: monospace; font-weight: 600; margin-bottom: 0;'>"
    "gmail cleaner ai"
    "</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='color: #6b6357; margin-top: 4px;'>"
    "Sender-level Gmail cleanup. IMAP read, LLM classify, label, trash. "
    "BYOK, MIT. "
    "<a href='https://github.com/mertkayacs/gmail-cleaner-ai' style='color: #9b4d00;'>"
    "github.com/mertkayacs/gmail-cleaner-ai</a>"
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

# Smart-default preset + early state computation. Lifted above Setup card body
# so layout state (State A vs B per shape brief) and the gate at the bottom
# can both decide before any block renders. Without an LLM, scan-only is
# meaningless; the gate stops the lower cards until both pieces are ready.
PRESET_KEYS_LIST = list(PRESETS.keys())
_default_preset_idx = 0
for _i, _name in enumerate(PRESET_KEYS_LIST):
    _kv = PRESETS[_name].get("key_var")
    if _kv and os.environ.get(_kv):
        _default_preset_idx = _i
        break
current_preset_name = st.session_state.get("preset_picker") or PRESET_KEYS_LIST[_default_preset_idx]
current_preset = PRESETS.get(current_preset_name, PRESETS[PRESET_KEYS_LIST[_default_preset_idx]])
_current_key_var = current_preset.get("key_var")
selected_key_set = (_current_key_var is None) or bool(os.environ.get(_current_key_var))

# Status sentence reflects the SELECTED preset's key (computed below in Setup),
# not a global tally. Set later, render at top via a placeholder.
status_placeholder_top = st.empty()


# ============== Card 1: Setup ==============

with st.container(border=True):
    section_heading("setup")

    # State A (vertical stack, lead-in captions per missing piece): anything missing.
    # State B (2-column compact recap): both Gmail and LLM ready. Per shape brief 2026-05-08.
    use_columns = bool(accounts_full) and selected_key_set
    if use_columns:
        setup_col_acc, setup_col_llm = st.columns(2)
    else:
        setup_col_acc = st.container()
        setup_col_llm = st.container()

    # ---- Gmail accounts ----
    with setup_col_acc:
        if not accounts_full and not use_columns:
            st.caption("start by adding a gmail account.")
        st.markdown("**gmail accounts**")

        if accounts_full:
            for slot, email in accounts_full:
                cols = st.columns([5, 1])
                cols[0].markdown(f"`{email}`")
                if cols[1].button("Remove", key=f"rm_acc_{slot}"):
                    remove_env_keys([f"GMAIL_ACCOUNT_{slot}", f"GMAIL_APPPASS_{slot}"])
                    st.rerun()

        # When accounts exist, hide the add form behind an expander so it doesn't
        # dominate the column. New users (no accounts) see the form immediately.
        add_form_container = (
            st.expander("add another account") if accounts_full else st.container()
        )
        with add_form_container:
            with st.form("add_acc_form", clear_on_submit=True, border=False):
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
        if not selected_key_set and not use_columns:
            st.caption("and an llm key to classify.")
        st.markdown("**llm provider**")
        preset_name = st.selectbox(
            "Provider",
            PRESET_KEYS_LIST,
            index=_default_preset_idx,
            label_visibility="collapsed",
            key="preset_picker",
        )
        preset = PRESETS[preset_name]

        if preset["models"]:
            selected_model = st.selectbox("model", preset["models"])
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
            ollama_host = st.text_input("ollama host", os.environ.get("OLLAMA_HOST", "http://localhost:11434"))

        # LM Studio and llama.cpp use OPENAI_API_KEY by LiteLLM convention. The
        # key field below shows that var name, which can read as "is this
        # uploading my real OpenAI key to my local server?" — clarifier removes
        # the doubt before the field appears.
        if preset_name in ("LM Studio (local)", "llama.cpp server (local)"):
            st.caption(
                "Local OpenAI-compatible server. The key field below uses "
                "`OPENAI_API_KEY` by LiteLLM convention, but any non-empty value "
                "works — your local server normally ignores it. Your real OpenAI "
                "key isn't required."
            )

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
            with st.form(f"set_key_form_{key_var}", clear_on_submit=True, border=False):
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
    # Auto-determine sender batch default from the first scanned account's inventory
    # (aim for ~5 batches). Falls back to 50 when no scans exist yet. Manual override
    # via the number_input sticks via Streamlit session_state.
    _auto_batch_default = 50
    for _slot, _acc_email in accounts_full:
        _inv_p = DATA_DIR / _acc_email / "inventory.json"
        if _inv_p.exists():
            try:
                _inv_data = json.loads(_inv_p.read_text())
                _target = min(_inv_data.get("unique_senders", 200), 200)
                _auto_batch_default = max(1, min(500, _target // 5))
                break
            except Exception:
                pass

    with st.expander("advanced (batch sizes)"):
        adv1, adv2, adv3 = st.columns(3)
        with adv1:
            sender_batch_size = st.number_input("sender batch size", min_value=1, max_value=500, value=_auto_batch_default, step=10)
        with adv2:
            top_sender_cap = st.number_input("top sender cap", min_value=10, max_value=2000, value=200, step=50)
        with adv3:
            fetch_batch_size = st.number_input("IMAP fetch batch size", min_value=50, max_value=2000, value=500, step=50)


# Status reflects what's needed for the SELECTED preset, not a global tally.
# selected_key_set already computed before Setup card body so layout state and
# this status block share the same source of truth.
if accounts and selected_key_set:
    top_status = f"{len(accounts)} account{'s' if len(accounts) != 1 else ''}, {preset_name} ready."
elif accounts and key_var:
    top_status = f"{len(accounts)} account{'s' if len(accounts) != 1 else ''}, {key_var} not set yet."
elif accounts:
    top_status = f"{len(accounts)} account{'s' if len(accounts) != 1 else ''}, no provider key yet."
elif selected_key_set:
    top_status = f"{preset_name} ready. Add a Gmail account below to begin."
else:
    top_status = "Add a Gmail App Password and an LLM key below to begin."

# When fully configured, a quiet caption is right; users glance and move on.
# When something's missing, the banner needs to actually catch the eye —
# this is the line that tells them what to do next.
if accounts and selected_key_set:
    status_placeholder_top.caption(top_status)
else:
    status_placeholder_top.markdown(
        f"<div style='font-family: monospace; padding: 10px 14px; "
        f"background: #efe9dd; border-radius: 4px; color: #9b4d00; "
        f"margin: 8px 0; font-size: 0.95rem;'>{top_status}</div>",
        unsafe_allow_html=True,
    )

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


# ============== Gating: BOTH a Gmail account AND an LLM key must be ready ==============
# Without an LLM, scan-only would produce data the user can't classify or act on.

if not (accounts and selected_key_set):
    st.stop()


# ============== Account picker (between cards 1 and 2 if multiple) ==============

if len(accounts) == 1:
    account = accounts[0]
    st.markdown(
        f"<p style='margin: 16px 0 8px 0; color: #6b6357;'>"
        f"Working on <code>{account}</code>"
        f"</p>",
        unsafe_allow_html=True,
    )
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
    section_heading("scan and classify")

    # ---- Scan inbox (inventory) ----
    st.markdown("**scan inbox.** IMAP-only. Reads sender, subject, headers. Body stays in Gmail.")
    if st.button("Scan inbox", type="primary", use_container_width=True, key="btn_inv"):
        with st.status(
            f"Scanning {account} (a few minutes for big mailboxes)...",
            expanded=True,
        ) as status:
            rc, _ = run_subcommand("inventory", [account], st.empty())
            status.update(
                label="Scan done." if rc == 0 else f"Scan failed (exit {rc}). Check log above.",
                state="complete" if rc == 0 else "error",
                expanded=rc != 0,  # keep open on error so user sees why
            )
    if inv_path.exists():
        inv = json.loads(inv_path.read_text())
        st.caption(f"Last scanned {file_age(inv_path)}.")
        st.markdown(
            f"`{inv['total_mails']:,}` mails  ·  "
            f"`{inv['unique_senders']:,}` senders  ·  "
            f"`{inv['unique_domains']:,}` domains  ·  "
            f"`{inv['has_list_unsubscribe']:,}` unsubscribable"
        )

    st.markdown("")

    # ---- Classify (analyze) ----
    classify_disabled = not inv_path.exists()
    st.markdown(f"**classify.** Top senders sent to `{model or 'default model'}`.")

    # Category source selector. Determines the schema the LLM classifies into.
    _src_labels = {
        "preset": "preset (built-in 12 categories, fast)",
        "llm_generated": "llm-generated (one extra LLM call drafts categories for this inbox)",
        "none": "none (binary keep / trash, simplest)",
    }
    _src_keys = list(_src_labels.keys())
    category_source = st.selectbox(
        "category source",
        _src_keys,
        index=_src_keys.index(st.session_state.get("CATEGORY_SOURCE", "preset")
                              if st.session_state.get("CATEGORY_SOURCE") in _src_keys
                              else "preset"),
        format_func=lambda k: _src_labels[k],
        key="CATEGORY_SOURCE",
    )

    # llm_generated needs an extra step: draft categories from top senders,
    # save to data/<account>/categories.json, then classify uses those.
    _cats_file = acc_dir / "categories.json"
    if category_source == "llm_generated":
        if _cats_file.exists():
            try:
                _cats_data = json.loads(_cats_file.read_text())
                _cat_names = ", ".join(c.get("name", "?") for c in _cats_data.get("categories", []))
                st.caption(f"Custom categories: {_cat_names} (drafted {file_age(_cats_file)})")
            except Exception:
                st.caption("categories.json present but unreadable.")
        else:
            st.caption("No custom categories yet. Click 'draft categories' to generate them from your top senders.")
        if st.button("draft categories", disabled=not inv_path.exists(), key="btn_draft_cats"):
            with st.status("Drafting categories from top 50 senders...", expanded=True) as status:
                rc, _ = run_subcommand("propose-categories", [account], st.empty())
                status.update(
                    label="Categories drafted." if rc == 0 else f"Drafting failed (exit {rc}).",
                    state="complete" if rc == 0 else "error",
                    expanded=rc != 0,
                )
            st.rerun()

    # Mode selector. Determines what evidence per sender goes to the LLM.
    _mode_labels = {
        "sender_subject": "sender + sample subjects (default, balanced)",
        "sender_only": "sender only (most private, lowest cost, less accurate)",
        "sender_subject_body": "sender + subject + first N body lines (most accurate, opt-in privacy tradeoff)",
    }
    _mode_keys = list(_mode_labels.keys())
    _default_mode_idx = _mode_keys.index(
        st.session_state.get("CLASSIFY_MODE", "sender_subject")
        if st.session_state.get("CLASSIFY_MODE") in _mode_keys
        else "sender_subject"
    )
    classify_mode = st.radio(
        "what to send to the LLM",
        _mode_keys,
        index=_default_mode_idx,
        format_func=lambda k: _mode_labels[k],
        key="CLASSIFY_MODE",
        horizontal=False,
    )
    if classify_mode == "sender_subject_body":
        body_lines = st.slider(
            "body lines per sample mail",
            min_value=1, max_value=20, value=5, step=1,
            help="First N lines of the message body, per sample mail. Sent to the LLM in addition to subject.",
        )
        st.session_state["BODY_LINES"] = str(body_lines)
        st.caption(
            "Mode 3 fetches body excerpts via IMAP after the header pass. "
            "Adds time to scan; sends partial body text to your chosen LLM."
        )

    # Preview pane: shows batch math + the actual prompt that will be sent.
    # Only rendered after scan, since the math depends on the inventory.
    if inv_path.exists():
        _senders_to_classify = min(inv["unique_senders"], top_sender_cap)
        _n_batches = max(1, (_senders_to_classify + sender_batch_size - 1) // sender_batch_size)
        st.caption(
            f"`{_senders_to_classify}` senders to classify, batch size `{sender_batch_size}`, "
            f"≈ `{_n_batches}` LLM call{'s' if _n_batches != 1 else ''}. "
            f"Adjust batch size in Setup → advanced (batch sizes)."
        )

        # Build sample prompt once; reused for cost estimate and preview.
        _sample_pairs = inv.get("top_senders", [])[:2]
        _sample_subj = inv.get("sample_subjects", {})
        _custom_cats = None
        if category_source == "llm_generated" and _cats_file.exists():
            try:
                _custom_cats = json.loads(_cats_file.read_text()).get("categories", [])
            except Exception:
                pass
        _sample_prompt = ""
        if _sample_pairs:
            _sample_prompt = build_classification_prompt(
                _sample_pairs, _sample_subj,
                mode=classify_mode,
                category_source=category_source,
                custom_categories=_custom_cats,
            )

        if _sample_prompt and model:
            _cost_caption = estimate_classify_cost(model, _sample_prompt, _n_batches)
            if _cost_caption:
                st.caption(_cost_caption)

        with st.expander("preview the prompt"):
            if _sample_prompt:
                st.code(_sample_prompt, language="text")
            else:
                st.caption("No senders in inventory to preview yet.")
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
                label="Classification done." if rc == 0 else f"Classification failed (exit {rc}). Check log above.",
                state="complete" if rc == 0 else "error",
                expanded=rc != 0,
            )
    if classify_disabled:
        st.caption("Run the scan first.")
    if cats_path.exists():
        cats = json.loads(cats_path.read_text())
        st.caption(f"Last classified {file_age(cats_path)}.")
        cat_summary = [
            {"category": c, "senders": len(s)}
            for c, s in cats.get("categories", {}).items()
        ]
        st.dataframe(
            pd.DataFrame(cat_summary).sort_values("senders", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

    # ---- Reset path ----
    # Common operation when re-running classification with a different model
    # or after editing prompts. Leaves applied.log alone so the audit trail
    # survives a reset.
    _data_exists = (
        inv_path.exists()
        or cats_path.exists()
        or allowed_path.exists()
        or disallowed_path.exists()
        or xml_path.exists()
    )
    if _data_exists:
        with st.expander("reset data for this account"):
            st.caption(
                f"Deletes inventory, classification, allowed/disallowed lists, and "
                f"filters.xml for `{account}`. The audit log (applied.log) and "
                f"any LLM-drafted categories (categories.json) are preserved so "
                f"a re-classify with the same schema is one click."
            )
            confirm_reset = st.checkbox(
                "I understand this clears my classification data",
                key=f"confirm_reset_{account}",
            )
            if st.button(
                "Clear data",
                disabled=not confirm_reset,
                key=f"btn_reset_{account}",
            ):
                for _p in (inv_path, cats_path, allowed_path, disallowed_path, xml_path):
                    _p.unlink(missing_ok=True)
                st.success("Cleared.")
                st.rerun()


# ============== Card 3: Review ==============

with st.container(border=True):
    section_heading("review")
    review_ready = allowed_path.exists() or disallowed_path.exists()
    if not review_ready:
        st.markdown(
            "**No senders yet.** Run classify above and the model's output will "
            "split into two editable lists here: allowed (keep, get sublabels) "
            "and disallowed (move to Trash)."
        )
    else:
        st.markdown(
            "Edit each table and click its save button. Move a sender between allowed "
            "and disallowed by editing the row. The apply step reads these files."
        )

        df_a = parse_list_file(allowed_path)
        df_d = parse_list_file(disallowed_path)

        # Filter dropdowns. When a specific category is picked, the editor
        # below renders read-only — saving while filtered would silently drop
        # the rows hidden by the filter, so we forbid edits in filtered view
        # and the user has to switch back to '(all)' to mutate.
        def _category_options(df):
            cats = sorted(c for c in df["category"].unique() if c)
            return ["(all)"] + cats

        # Insert a 'select' boolean column (defaulted False) at the front of
        # each editor's DataFrame. Users tick rows for hybrid re-classify
        # below. The column is stripped before write so it never persists.
        df_a_disp = df_a.copy()
        df_a_disp.insert(0, "select", False)
        df_d_disp = df_d.copy()
        df_d_disp.insert(0, "select", False)

        rev_col_a, rev_col_d = st.columns(2)
        edited_a = None
        edited_d = None
        with rev_col_a:
            st.markdown(f"**allowed (keep), {len(df_a)} senders**")
            filter_a = st.selectbox(
                "filter category", _category_options(df_a), key="filter_allowed",
                label_visibility="collapsed",
            )
            if filter_a != "(all)":
                view_a = df_a[df_a["category"] == filter_a]
                st.caption(f"showing `{filter_a}` only ({len(view_a)} of {len(df_a)}). Read-only — switch to (all) to edit.")
                st.data_editor(
                    view_a, use_container_width=True, key="ed_allowed_view", disabled=True,
                )
            else:
                edited_a = st.data_editor(
                    df_a_disp, num_rows="dynamic", use_container_width=True, key="ed_allowed"
                )
                if st.button("Save allowed", key="btn_save_a"):
                    write_list_file(allowed_path, "Allowed senders (keep)", edited_a.drop(columns=["select"], errors="ignore"))
                    st.success("Saved.")
        with rev_col_d:
            st.markdown(f"**disallowed (trash), {len(df_d)} senders**")
            filter_d = st.selectbox(
                "filter category", _category_options(df_d), key="filter_disallowed",
                label_visibility="collapsed",
            )
            if filter_d != "(all)":
                view_d = df_d[df_d["category"] == filter_d]
                st.caption(f"showing `{filter_d}` only ({len(view_d)} of {len(df_d)}). Read-only — switch to (all) to edit.")
                st.data_editor(
                    view_d, use_container_width=True, key="ed_disallowed_view", disabled=True,
                )
            else:
                edited_d = st.data_editor(
                    df_d_disp, num_rows="dynamic", use_container_width=True, key="ed_disallowed"
                )
                if st.button("Save disallowed", key="btn_save_d"):
                    write_list_file(disallowed_path, "Disallowed senders (move to Trash)", edited_d.drop(columns=["select"], errors="ignore"))
                    st.success("Saved.")

        # Hybrid re-classify: collect ticks from both tables, send to triage
        # with SENDERS env var + chosen mode. Results merge into existing
        # proposed_categories so untouched senders survive.
        _sel_a = edited_a[edited_a["select"]]["sender"].tolist() if edited_a is not None else []
        _sel_d = edited_d[edited_d["select"]]["sender"].tolist() if edited_d is not None else []
        _all_selected = sorted(set(_sel_a + _sel_d))
        if _all_selected:
            st.markdown("---")
            st.markdown(
                f"**hybrid re-classify.** {len(_all_selected)} sender(s) selected. "
                "Re-runs classify on just these senders with the chosen mode below; "
                "untouched senders keep their prior classification."
            )
            _hyb_mode_keys = list(_mode_labels.keys())
            _hyb_default = classify_mode if classify_mode in _hyb_mode_keys else "sender_subject"
            hybrid_mode = st.radio(
                "mode for re-classify",
                _hyb_mode_keys,
                index=_hyb_mode_keys.index(_hyb_default),
                format_func=lambda k: _mode_labels[k],
                key="hybrid_mode",
                horizontal=False,
            )
            if st.button(f"Re-classify {len(_all_selected)} selected", key="btn_hybrid"):
                # Stash overrides for this one subprocess call. CLASSIFY_MODE may
                # differ from the main radio; restore after.
                _prior_mode = st.session_state.get("CLASSIFY_MODE")
                st.session_state["SENDERS"] = ",".join(_all_selected)
                st.session_state["CLASSIFY_MODE"] = hybrid_mode
                with st.status(f"Re-classifying {len(_all_selected)} senders...", expanded=True) as status:
                    rc, _ = run_subcommand("analyze", [account], st.empty())
                    status.update(
                        label="Re-classify done." if rc == 0 else f"Re-classify failed (exit {rc}).",
                        state="complete" if rc == 0 else "error",
                        expanded=rc != 0,
                    )
                # Reset SENDERS so a regular Classify click later doesn't carry over.
                st.session_state["SENDERS"] = ""
                st.session_state["CLASSIFY_MODE"] = _prior_mode or "sender_subject"
                st.rerun()


# ============== Card 4: Apply ==============

with st.container(border=True):
    section_heading("apply")
    apply_disabled = not (allowed_path.exists() or disallowed_path.exists())
    if apply_disabled:
        st.caption("Save reviewed lists first.")
    st.markdown(
        "Apply your reviewed lists. Allowed senders get sublabels; Disallowed senders' mail moves to Trash. "
        "**Trash is recoverable for 30 days**, then Gmail auto-purges."
    )

    # Scope filter: read all categories from saved allowed + disallowed, render
    # one checkbox per category. Default all checked. APPLY_CATEGORIES env var
    # carries the user's selection through to triage's apply step.
    _apply_cats = set()
    if not apply_disabled:
        for _p in (allowed_path, disallowed_path):
            for _row in parse_list_file(_p).itertuples():
                if _row.category:
                    _apply_cats.add(_row.category)
    if _apply_cats:
        with st.expander(f"scope: which categories to act on ({len(_apply_cats)} present)", expanded=False):
            st.caption(
                "Default: all categories run. Uncheck any to skip them this round. "
                "Useful for trashing junk first, leaving newsletters for a separate pass."
            )
            _selected_cats = []
            _cat_cols = st.columns(min(3, max(1, len(_apply_cats))))
            for _i, _cat in enumerate(sorted(_apply_cats)):
                with _cat_cols[_i % len(_cat_cols)]:
                    if st.checkbox(_cat, value=True, key=f"apply_cat_{_cat}"):
                        _selected_cats.append(_cat)
            # Stash for run_subcommand to pick up.
            #   all selected   -> "" (matches triage 'unset = no filter')
            #   none selected  -> "__NONE__" sentinel; without this, "" leaks through
            #                     and triage processes every sender (real footgun
            #                     since the destructive path defaults on)
            #   subset         -> comma list
            if len(_selected_cats) == len(_apply_cats):
                st.session_state["APPLY_CATEGORIES"] = ""
            elif not _selected_cats:
                st.session_state["APPLY_CATEGORIES"] = "__NONE__"
                st.caption("Will act on: nothing. Apply will be a no-op.")
            else:
                st.session_state["APPLY_CATEGORIES"] = ",".join(_selected_cats)
                st.caption(f"Will act on: {', '.join(_selected_cats)}")
    else:
        st.session_state["APPLY_CATEGORIES"] = ""

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
                    label="Dry-run done." if rc == 0 else f"Dry-run failed (exit {rc}). Check log above.",
                    state="complete" if rc == 0 else "error",
                    expanded=rc != 0,
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
                    label="Apply done." if rc == 0 else f"Apply failed (exit {rc}). Check log above.",
                    state="complete" if rc == 0 else "error",
                    expanded=rc != 0,
                )

    if log_path.exists():
        st.caption(f"Last applied {file_age(log_path)}.")
        with st.expander("audit log"):
            st.code(log_path.read_text(), language="text")

    # ---- Undo last apply ----
    # Only the most recent session is restorable. Earlier sessions may have
    # already passed Gmail's 30-day Trash window.
    undo_disabled = not log_path.exists()
    with st.expander("undo last apply"):
        st.caption(
            "Reads the most recent apply session from the audit log and moves "
            "those trashed senders back from Trash to All Mail. Mail older than "
            "Gmail's 30-day Trash window is silently skipped."
        )
        undo_col_dry, undo_col_live = st.columns(2)
        with undo_col_dry:
            if st.button(
                "Undo (preview)",
                use_container_width=True,
                disabled=undo_disabled,
                key="btn_undo_dry",
            ):
                with st.status(f"Previewing undo on {account}...", expanded=True) as status:
                    rc, _ = run_subcommand("undo", [account, "--dry-run"], st.empty())
                    status.update(
                        label="Preview done." if rc == 0 else f"Preview failed (exit {rc}).",
                        state="complete" if rc == 0 else "error",
                        expanded=rc != 0,
                    )
        with undo_col_live:
            confirm_undo = st.checkbox(
                "I understand: this moves mail from Trash back to All Mail",
                key="confirm_undo",
            )
            if st.button(
                "Undo LIVE",
                use_container_width=True,
                disabled=undo_disabled or not confirm_undo,
                key="btn_undo_live",
            ):
                with st.status(f"Restoring on {account}...", expanded=True) as status:
                    rc, _ = run_subcommand("undo", [account], st.empty())
                    status.update(
                        label="Restore done." if rc == 0 else f"Restore failed (exit {rc}).",
                        state="complete" if rc == 0 else "error",
                        expanded=rc != 0,
                    )

    st.markdown(
        "**generate gmail filter xml.** Import once per account in Gmail Settings → Filters → Import filters. "
        "Future mail auto-routes by sender, no LLM calls."
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
                label="Generated." if rc == 0 else f"Generation failed (exit {rc}). Check log above.",
                state="complete" if rc == 0 else "error",
                expanded=rc != 0,
            )
    if xml_path.exists():
        st.download_button(
            "Download filters.xml",
            xml_path.read_bytes(),
            file_name=f"{account.replace('@', '-at-')}-filters.xml",
            mime="application/xml",
            use_container_width=True,
        )

    # ---- settings.xml export + import ----
    st.markdown("")
    st.markdown(
        "**settings.xml.** Bundle your classify config (mode, category source, "
        "batch sizes, custom categories if any) into one file. Re-import on a "
        "new machine to skip re-configuration."
    )

    def _build_settings_xml():
        from xml.sax.saxutils import escape as _xe
        from datetime import datetime as _dt, timezone as _tz
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gmail-cleaner-ai-settings>',
            f'  <generated_at>{_dt.now(_tz.utc).isoformat()}</generated_at>',
            '  <classify>',
            f'    <mode>{_xe(str(st.session_state.get("CLASSIFY_MODE", "sender_subject")))}</mode>',
            f'    <category_source>{_xe(str(st.session_state.get("CATEGORY_SOURCE", "preset")))}</category_source>',
            f'    <body_lines>{_xe(str(st.session_state.get("BODY_LINES", "5")))}</body_lines>',
            f'    <sender_batch_size>{_xe(str(st.session_state.get("SENDER_BATCH_SIZE", "50")))}</sender_batch_size>',
            f'    <top_sender_cap>{_xe(str(st.session_state.get("TOP_SENDER_CAP", "200")))}</top_sender_cap>',
            f'    <fetch_batch_size>{_xe(str(st.session_state.get("FETCH_BATCH_SIZE", "500")))}</fetch_batch_size>',
            '  </classify>',
        ]
        if _cats_file.exists():
            try:
                _cd = json.loads(_cats_file.read_text())
                parts.append('  <categories>')
                for _c in _cd.get("categories", []):
                    parts.append(
                        f'    <category name="{_xe(str(_c.get("name", "")))}"'
                        f' description="{_xe(str(_c.get("description", "")))}"'
                        f' disposition="{_xe(str(_c.get("disposition", "keep")))}"/>'
                    )
                parts.append('  </categories>')
            except Exception:
                pass
        parts.append('</gmail-cleaner-ai-settings>')
        return "\n".join(parts) + "\n"

    set_col_x, set_col_i = st.columns(2)
    with set_col_x:
        st.download_button(
            "Export settings.xml",
            _build_settings_xml(),
            file_name="gmail-cleaner-ai-settings.xml",
            mime="application/xml",
            use_container_width=True,
        )
    with set_col_i:
        _imp = st.file_uploader(
            "Import settings.xml", type=["xml"], label_visibility="collapsed",
            key="settings_uploader",
        )
        if _imp is not None and st.button("Apply imported settings", key="btn_apply_settings"):
            try:
                import xml.etree.ElementTree as ET
                _root = ET.fromstring(_imp.getvalue())
                _classify = _root.find("classify")
                if _classify is not None:
                    for _tag, _key in [
                        ("mode", "CLASSIFY_MODE"),
                        ("category_source", "CATEGORY_SOURCE"),
                        ("body_lines", "BODY_LINES"),
                        ("sender_batch_size", "SENDER_BATCH_SIZE"),
                        ("top_sender_cap", "TOP_SENDER_CAP"),
                        ("fetch_batch_size", "FETCH_BATCH_SIZE"),
                    ]:
                        _el = _classify.find(_tag)
                        if _el is not None and _el.text:
                            st.session_state[_key] = _el.text.strip()
                _cats_xml = _root.find("categories")
                if _cats_xml is not None:
                    _cats_list = []
                    for _c in _cats_xml.findall("category"):
                        _cats_list.append({
                            "name": _c.attrib.get("name", ""),
                            "description": _c.attrib.get("description", ""),
                            "disposition": _c.attrib.get("disposition", "keep"),
                        })
                    if _cats_list:
                        acc_dir.mkdir(parents=True, exist_ok=True)
                        _cats_file.write_text(json.dumps({
                            "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "categories": _cats_list,
                        }, indent=2))
                st.success("Settings applied.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not parse settings.xml: {e}")


# ============== Card 5: History ==============

HISTORY_FILES = ("allowed.txt", "disallowed.txt", "proposed_categories.json", "filters.xml")

with st.container(border=True):
    section_heading("history")
    st.markdown(
        "Snapshots of the current decision files (allowed, disallowed, categories, "
        "filters.xml). Save before re-classifying with a different model so you can "
        "fall back if the new run is worse. Each snapshot is a folder under "
        "`data/<account>/history/`."
    )

    hist_dir = acc_dir / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    snaps = sorted(
        [p for p in hist_dir.iterdir() if p.is_dir()],
        reverse=True,
    )

    # --- Save current ---
    save_disabled = not (allowed_path.exists() or disallowed_path.exists())
    with st.form("history_save_form", clear_on_submit=True, border=False):
        label_in = st.text_input(
            "label (optional)",
            placeholder="e.g. 'opus before sonnet re-classify'",
            label_visibility="collapsed",
        )
        if st.form_submit_button(
            "Save current as snapshot",
            disabled=save_disabled,
            use_container_width=True,
            type="primary",
        ):
            sub_args = [account]
            if label_in.strip():
                sub_args += ["--label", label_in.strip()]
            with st.status("Saving snapshot...", expanded=False) as status:
                rc, _ = run_subcommand("history-save", sub_args, st.empty())
                status.update(
                    label="Saved." if rc == 0 else f"Save failed (exit {rc}).",
                    state="complete" if rc == 0 else "error",
                    expanded=rc != 0,
                )
            st.rerun()
    if save_disabled:
        st.caption("Nothing to save yet. Run classify first.")

    # --- List ---
    if snaps:
        st.markdown("**snapshots**")
        for snap in snaps:
            files = [p.name for p in snap.iterdir() if p.name in HISTORY_FILES]
            label_path = snap / "label.txt"
            label = label_path.read_text().strip() if label_path.exists() else ""
            suffix = f" — {label}" if label else ""
            st.markdown(f"`{snap.name}`  ({len(files)} files){suffix}")
    else:
        st.caption("No snapshots yet.")

    # --- Restore / Delete (behind expanders so the list stays the focus) ---
    if snaps:
        snap_ids = [s.name for s in snaps]

        with st.expander("restore a snapshot"):
            st.caption(
                "Copies the snapshot files back into active position, overwriting "
                "your current allowed / disallowed / categories / filters.xml. "
                "Save the current state first if you want to keep it."
            )
            choice_r = st.selectbox("snapshot to restore", snap_ids, key="restore_pick")
            confirm_r = st.checkbox(
                "I understand this overwrites my current files",
                key="confirm_restore",
            )
            if st.button(
                "Restore",
                disabled=not confirm_r,
                use_container_width=True,
                key="btn_restore_snap",
            ):
                with st.status(f"Restoring {choice_r}...", expanded=False) as status:
                    rc, _ = run_subcommand("history-restore", [account, choice_r], st.empty())
                    status.update(
                        label="Restored." if rc == 0 else f"Restore failed (exit {rc}).",
                        state="complete" if rc == 0 else "error",
                        expanded=rc != 0,
                    )
                st.rerun()

        with st.expander("delete a snapshot"):
            st.caption("Removes the snapshot folder from disk. Cannot be undone.")
            choice_d = st.selectbox("snapshot to delete", snap_ids, key="delete_pick")
            confirm_d = st.checkbox(
                "I understand this is permanent",
                key="confirm_delete_snap",
            )
            if st.button(
                "Delete snapshot",
                disabled=not confirm_d,
                use_container_width=True,
                key="btn_delete_snap",
            ):
                with st.status(f"Deleting {choice_d}...", expanded=False) as status:
                    rc, _ = run_subcommand("history-delete", [account, choice_d], st.empty())
                    status.update(
                        label="Deleted." if rc == 0 else f"Delete failed (exit {rc}).",
                        state="complete" if rc == 0 else "error",
                        expanded=rc != 0,
                    )
                st.rerun()
