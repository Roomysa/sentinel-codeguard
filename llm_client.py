import hashlib
import os
import threading

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Order matters: the first one is tried first, the next ones are backups.
# A name given as provider= (like "groq") uses ONLY that entry, with no fallback.
PROVIDERS = [
    {
        "name": "groq",
        "key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
    },
    {
        "name": "groq-20b",
        "key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-20b",
    },
    {
        "name": "gemini",
        "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.6-flash",
    },
    {
        "name": "openrouter",
        "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "cohere/north-mini-code:free",
    },
]

CACHE_DIR = ".cache"
last_used = None
_state = threading.local()


def reset_used():
    _state.used = []


def models_used():
    return list(getattr(_state, "used", []))


def _note(model):
    if not hasattr(_state, "used"):
        _state.used = []
    if model not in _state.used:
        _state.used.append(model)


def ask_llm(prompt, provider=None):
    global last_used
    chain = [p for p in PROVIDERS if provider is None or p["name"] == provider]
    errors = []

    for p in chain:
        api_key = os.getenv(p["key_env"])
        if not api_key:
            errors.append(p["name"] + ": key missing")
            continue

        key = hashlib.sha256((p["model"] + prompt).encode("utf-8")).hexdigest()
        path = os.path.join(CACHE_DIR, key + ".txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                last_used = p["name"]
                _note(p["model"])
                return f.read()

        try:
            client = OpenAI(
                base_url=p["base_url"],
                api_key=api_key,
                timeout=60,
                max_retries=0,
            )
            response = client.chat.completions.create(
                model=p["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            text = response.choices[0].message.content or ""
        except Exception as e:
            errors.append(p["name"] + ": " + str(e)[:100])
            continue

        if text:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            last_used = p["name"]
            _note(p["model"])
            return text
        errors.append(p["name"] + ": empty reply")

    raise RuntimeError("All providers failed: " + "; ".join(errors))