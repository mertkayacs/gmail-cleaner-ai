"""
LLM-agnostic email classifier built on LiteLLM.

LiteLLM gives one Python interface to 100+ LLM providers. Pick the model with
a provider prefix and LiteLLM routes to the right backend.

Examples of LLM_MODEL values:
    claude-opus-4-7                                     -> Anthropic
    gpt-4o                                              -> OpenAI
    gemini/gemini-2.5-pro                               -> Google Gemini
    groq/llama-3.3-70b-versatile                        -> Groq
    together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo -> Together AI
    openrouter/anthropic/claude-opus-4-7                -> OpenRouter
    mistral/mistral-large-latest                        -> Mistral
    ollama/llama3.3                                     -> Ollama (local)
    openai/<your-model> + LLM_BASE_URL=http://...       -> LM Studio, llama.cpp,
                                                           any OpenAI-compatible

Provider env vars (LiteLLM reads them automatically):
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY,
    TOGETHERAI_API_KEY, OPENROUTER_API_KEY, MISTRAL_API_KEY

LiteLLM docs: https://docs.litellm.ai/docs/providers
"""

import json
import os
import re

# Disable LiteLLM's anonymous telemetry by default. Privacy preference.
os.environ.setdefault("LITELLM_TELEMETRY", "False")


def _extract_json(text):
    """Tolerate JSON wrapped in prose or code fences."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Could not parse JSON from response: {text[:300]}")


class Classifier:
    """Unified classifier over any LiteLLM-supported provider."""

    DEFAULT_MODEL = "claude-opus-4-7"

    def __init__(self, model=None, api_base=None):
        from litellm import completion
        self._completion = completion
        self.model = model or os.environ.get("LLM_MODEL") or self.DEFAULT_MODEL
        self.api_base = api_base or os.environ.get("LLM_BASE_URL") or None

    def classify_batch(self, prompt):
        kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        resp = self._completion(**kwargs)
        text = resp.choices[0].message.content or ""
        return _extract_json(text)


def get_classifier(model=None, api_base=None) -> Classifier:
    """Build a classifier from explicit args or env vars."""
    return Classifier(model=model, api_base=api_base)
