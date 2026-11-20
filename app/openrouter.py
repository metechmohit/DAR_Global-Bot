"""Backend-only OpenRouter client with explicit free-only routing and safe errors."""
import json
import os
import urllib.error
import urllib.request


class ModelError(Exception):
    pass


def configured():
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


def completion(messages, max_tokens=1400, model=None):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ModelError("Add OPENROUTER_API_KEY to .env and restart the app to enable AI answers.")
    models = [model or os.getenv("OPENROUTER_MODEL", "openrouter/free")]
    fallback = os.getenv("OPENROUTER_FALLBACK_MODEL", "").strip()
    if fallback and fallback not in models:
        models.append(fallback)
    for candidate in models:
        if candidate != "openrouter/free" and not candidate.endswith(":free"):
            raise ModelError("Only openrouter/free or an explicit :free model is allowed. Set OPENROUTER_MODEL in .env.")
    payload = {"model": models[0], "messages": messages, "temperature": 0.15, "max_tokens": max_tokens}
    if len(models) > 1:
        payload["models"] = models
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "X-Title": "Dar & Wasalt Property Atlas"}, method="POST")
    try:
        timeout = max(5, min(float(os.getenv("OPENROUTER_TIMEOUT", "45")), 90))
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        messages = {401: "OpenRouter rejected the API key. Check .env and restart.", 402: "OpenRouter account credit policy blocked the request. Check your account and free-model access.", 403: "OpenRouter or its provider rejected this request. Check model access and provider settings.", 404: "The configured free model is unavailable. Try OPENROUTER_MODEL=openrouter/free.", 429: "OpenRouter's free-model quota or capacity is exhausted. Try again later."}
        raise ModelError(messages.get(e.code, f"OpenRouter returned HTTP {e.code}. Please try again.")) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ModelError("Cannot reach OpenRouter or the request timed out. Check internet access; source-based search still works.") from None
    if data.get("error"):
        raise ModelError("OpenRouter could not complete this request. Check model availability and account limits.")
    try:
        answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError
    except (KeyError, IndexError, ValueError, TypeError):
        raise ModelError("The model returned no usable answer. Please try another free model.") from None
    return answer, data.get("model", models[0])
