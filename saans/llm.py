"""Small LLM client: Gemini first, Groq as the fallback, every answer cached on disk.

Caching matters twice: re-running a notebook costs no API calls, and the dashboard reads the
cached advisories, so it needs no API key at all.
"""
import hashlib
import json
import os
import re
import time

import requests

from saans.config import DATA

# Free-tier quotas differ per model (gemini-3.5-flash allows only 20 requests a day; the flash-lite models
# allow far more), so the client walks a chain and moves on as soon as a model's daily quota is spent.
# gemini-2.5-flash is closed to new API keys.
GEMINI_MODELS = os.getenv("GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
CACHE = DATA / "llm_cache"


class QuotaExhausted(RuntimeError):
    pass


_exhausted: set[str] = set()


def _gemini(model: str, prompt: str, temperature: float, as_json: bool) -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is empty")
    config = {"temperature": temperature}
    if as_json:
        config["responseMimeType"] = "application/json"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for attempt in range(4):
        try:  # key in a header, never in the URL, so it cannot leak into error messages or notebook output
            r = requests.post(url, headers={"x-goog-api-key": key}, timeout=180,
                              json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config})
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(30)
            continue
        if r.status_code == 429 and "per day" in r.text:
            raise QuotaExhausted(f"{model}: daily free-tier quota used up")
        if r.status_code in (429, 500, 503):
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))  # skip thinking parts
    raise RuntimeError("Gemini kept failing (network or rate limit)")


def _groq(prompt: str, temperature: float, as_json: bool) -> str:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY is empty")
    body = {"model": GROQ_MODEL, "temperature": temperature, "messages": [{"role": "user", "content": prompt}]}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(4):
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=180,
                              headers={"Authorization": f"Bearer {key}"})
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(30)
            continue
        if r.status_code in (429, 500, 503):
            time.sleep(20 * (attempt + 1))
            continue
        if r.status_code == 400 and "response_format" in body:
            body.pop("response_format")  # Groq rejects answers that fail its JSON check; ask again and parse ourselves
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("Groq kept failing (network or rate limit)")


def ask(prompt: str, temperature: float = 0.0, as_json: bool = False) -> tuple[str, str]:
    """Return (answer, provider). Cached by prompt + settings; Gemini first, then Groq."""
    CACHE.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(f"{prompt}|{temperature}|{as_json}".encode()).hexdigest()[:24]
    path = CACHE / f"{h}.json"
    if path.exists():
        hit = json.loads(path.read_text(encoding="utf-8"))
        return hit["answer"], hit["provider"]
    errors = []
    chain = [(f"gemini:{m}", lambda p, t, j, m=m: _gemini(m, p, t, j)) for m in GEMINI_MODELS]
    chain.append((f"groq:{GROQ_MODEL}", _groq))
    for name, fn in chain:
        if name in _exhausted:
            continue
        try:
            answer = fn(prompt, temperature, as_json)
            path.write_text(json.dumps({"provider": name, "answer": answer}, ensure_ascii=False), encoding="utf-8")
            return answer, name
        except QuotaExhausted as e:  # skip this model for the rest of the session
            _exhausted.add(name)
            errors.append(str(e))
        except Exception as e:  # fall through to the next provider
            errors.append(f"{name}: {e}")
    raise RuntimeError("All LLM providers failed: " + " | ".join(errors))


def parse_json(text: str):
    """Parse a JSON answer, tolerating a ```json fence around it."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text)
