"""
Provider-agnostic email classifier.

Selects the LLM provider via LLM_PROVIDER env var. Each provider implements
classify_batch(prompt: str) -> dict[sender, classification].

Adding a new provider:
1. Implement a class extending Classifier.
2. Register in PROVIDERS dict at the bottom.
3. Document required env vars in .env.example.
"""

import json
import os
import re
from abc import ABC, abstractmethod


class Classifier(ABC):
    @abstractmethod
    def classify_batch(self, prompt: str) -> dict:
        """Run a classification batch. Return parsed JSON dict."""
        ...


def _extract_json(text: str) -> dict:
    """Tolerate JSON wrapped in prose or code fences."""
    text = text.strip()
    if text.startswith("```"):
        # strip code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Could not parse JSON from response: {text[:300]}")


class AnthropicClassifier(Classifier):
    """Claude via Anthropic API. Requires ANTHROPIC_API_KEY."""

    DEFAULT_MODEL = "claude-opus-4-7"

    def __init__(self, model=None, api_key=None):
        import anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY missing")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model or self.DEFAULT_MODEL

    def classify_batch(self, prompt):
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        return _extract_json(text)


class OpenAIClassifier(Classifier):
    """GPT via OpenAI API. Requires OPENAI_API_KEY."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, model=None, api_key=None):
        from openai import OpenAI
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY missing")
        self.client = OpenAI(api_key=key)
        self.model = model or self.DEFAULT_MODEL

    def classify_batch(self, prompt):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return _extract_json(resp.choices[0].message.content or "")


class GeminiClassifier(Classifier):
    """Gemini via Google AI API. Requires GOOGLE_API_KEY."""

    DEFAULT_MODEL = "gemini-2.5-pro"

    def __init__(self, model=None, api_key=None):
        import google.generativeai as genai
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GOOGLE_API_KEY missing")
        genai.configure(api_key=key)
        self.client = genai.GenerativeModel(model or self.DEFAULT_MODEL)

    def classify_batch(self, prompt):
        resp = self.client.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        return _extract_json(resp.text)


class OllamaClassifier(Classifier):
    """Local or remote open-source models via Ollama. No API key required."""

    DEFAULT_MODEL = "llama3.1:70b"

    def __init__(self, model=None, host=None):
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.model = model or self.DEFAULT_MODEL

    def classify_batch(self, prompt):
        import requests
        resp = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            },
            timeout=600,
        )
        resp.raise_for_status()
        return _extract_json(resp.json().get("response", ""))


PROVIDERS = {
    "anthropic": AnthropicClassifier,
    "openai": OpenAIClassifier,
    "gemini": GeminiClassifier,
    "ollama": OllamaClassifier,
}


def get_classifier(provider=None, model=None) -> Classifier:
    """
    Build a classifier from env or explicit args.

    LLM_PROVIDER  one of: anthropic, openai, gemini, ollama
    LLM_MODEL     overrides the provider's default model
    """
    provider = (provider or os.environ.get("LLM_PROVIDER") or "anthropic").lower()
    model = model or os.environ.get("LLM_MODEL")
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. "
            f"Choose one of: {', '.join(PROVIDERS.keys())}"
        )
    cls = PROVIDERS[provider]
    return cls(model=model) if model else cls()
