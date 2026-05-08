#!/usr/bin/env bash
# install.sh - one-command setup for gmail-triage
# Usage: bash install.sh

set -e

echo "gmail-triage installer"
echo "----------------------"

# Python check
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    echo "Install Python 3.10 or newer from https://www.python.org/"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found Python $PYTHON_VERSION"

# Install deps via uv (preferred) or pip
if command -v uv &>/dev/null; then
    echo "Using uv to install dependencies..."
    uv pip install -r requirements.txt
elif command -v pip3 &>/dev/null; then
    echo "Using pip3 to install dependencies..."
    pip3 install -r requirements.txt
else
    echo "ERROR: neither uv nor pip3 found."
    echo "  uv:  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  pip: bundled with Python"
    exit 1
fi

# .env bootstrap
if [ ! -f .env ]; then
    cp .env.example .env
    echo ".env created from .env.example. Edit before running anything."
else
    echo ".env already exists. Leaving it alone."
fi

# CLI smoke test
if python3 triage.py --help &>/dev/null; then
    echo "triage.py CLI: OK"
else
    echo "WARNING: triage.py --help failed. Check Python dependencies."
fi

cat <<'EOF'

Ready. Next steps:
  1. Generate a Gmail App Password per account at:
     https://myaccount.google.com/apppasswords
     (Requires 2-Step Verification on the account.)
  2. Get your LLM API key:
     - Anthropic: https://console.anthropic.com
     - OpenAI:    https://platform.openai.com
     - Google:    https://aistudio.google.com/apikey
     - Ollama:    install locally from https://ollama.com (no key)
  3. Edit .env to set LLM_PROVIDER plus the matching key, plus one or more
     GMAIL_ACCOUNT_n / GMAIL_APPPASS_n pairs.
  4. python3 triage.py inventory <account-email>
  5. python3 triage.py analyze <account-email>
  6. streamlit run app.py    # review the lists, click apply

EOF
