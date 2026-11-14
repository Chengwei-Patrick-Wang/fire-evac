"""LLM client (spec 7.5): one call, JSON-schema output, a timeout, None on failure.

    complete(prompt, *, image=None, image_mime="image/png", schema=None, timeout=30.0,
             thinking=None) -> dict | str | None      (a dict when schema is given)

LLM_PROVIDER, read on every call (from the environment, else .env):
    gemini (default)  google-genai with GEMINI_API_KEY; model GEMINI_MODEL, gemini-2.5-flash if empty
    claude            anthropic (imported lazily, not in requirements.txt) with APP_ANTHROPIC_API_KEY,
                      never ANTHROPIC_API_KEY; model CLAUDE_MODEL, claude-sonnet-4-5 if empty
    off               no network, every call returns None (smoke tests, check_all, the offline demo)

Gemini is slow and busy at times. Measured Sat 3 AM: gemini-3.5-flash took 1-13 s for a one-line
JSON ping at its default thinking, 1-5 s at thinking "minimal", once a 504 after 44 s, and for a
while only 503 "high demand" (0.3-13 s each); 3.6, 3.7 and 3.8-flash also answered 503;
gemini-2.5-flash answered in under 1 s. The team key is on the free tier: 20 requests a day per
model (429 RESOURCE_EXHAUSTED, quota GenerateRequestsPerDayPerProjectPerModel-FreeTier). So each
call goes:
    429, 500, 502, 503 or a dropped connection: retry the same model (3 tries, backoff 1 s, 2 s);
    a 429 whose retry delay is over 5 s (a used-up quota), a timeout or 504, a 400, 403 or 404
        (model or feature missing), invalid JSON or an empty answer: straight to the next model;
    401, or an invalid key: give up.
The models are GEMINI_MODEL, then GEMINI_FALLBACK_MODEL (comma-separated; default
gemini-2.5-flash). Each model gets `timeout` seconds, retries included, and the whole call stops
after 2 x timeout + 10 s. A model that ends busy (429, 5xx, timeout) or missing (404) is skipped
for COOLDOWN (120 s), or for the server's retry delay up to an hour, while another model is
configured, so the calls after it go straight to the next model. Requests use API version v1beta:
v1 rejects JSON mode on gemini-2.5-flash (measured). google-genai is imported on the first call,
so importing this module is cheap. A failure prints one stderr line (never a key) and returns
None, so callers fall back.

    python -m backend.llm.client      # ping with a JSON schema; prints {'ok': True}
"""
from __future__ import annotations

import base64
import json
import os
import random
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# Never overrides a variable that is already set: check_all's LLM_PROVIDER=off wins over .env.
load_dotenv(ROOT / ".env")

PROVIDERS = ("gemini", "claude", "off")
DEFAULT_TIMEOUT = 30.0  # s per model call; the brief said 20, measured latency says at least 30
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_FALLBACK_MODEL = "gemini-2.5-flash"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5"
API_VERSION = "v1beta"
RETRY_CODES = (429, 500, 502, 503)
TRIES = 3  # per model, for RETRY_CODES and dropped connections
BACKOFF = 1.0  # s before the first retry, doubled for each next one (the smoke test sets 0)
COOLDOWN = 120.0  # s a busy or missing model is skipped for, while another model is configured
MAX_COOLDOWN = 3600.0  # s; a used-up daily quota is checked again hourly (one quick 429)
LONG_WAIT = 5.0  # s; a 429 asking to wait longer than this goes straight to the next model
KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "APP_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")

last_model: str | None = None  # the model behind the latest successful call (for logs only)

_clients: dict[str, object] = {}
_clients_lock = threading.Lock()
_cooldown: dict[str, float] = {}  # model -> time.monotonic() until which it is skipped


class _Retry(Exception):
    """Internal: an answer that was no good (empty, or not JSON): try the next model."""


def provider() -> str:
    """LLM_PROVIDER, lower-cased: gemini (the default), claude or off; anything else as given."""
    return (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower() or "gemini"


def _scrub(text: str) -> str:
    """One line, at most 300 characters, with any key we know of blanked out."""
    for name in KEY_NAMES:
        value = os.environ.get(name) or ""
        if len(value) >= 8:
            text = text.replace(value, "***")
    return " ".join(str(text).split())[:300]


def _warn(message: str) -> None:
    print(f"LLM: {_scrub(message)}", file=sys.stderr, flush=True)


def _describe(e: BaseException) -> str:
    code = getattr(e, "code", None)
    status = getattr(e, "status", None)
    if isinstance(code, int):
        detail = getattr(e, "message", None) or str(e)
        return f"{code} {status or ''} {detail}".strip()
    return f"{type(e).__name__}: {e}"


def _is_timeout(e: BaseException) -> bool:
    for x in (e, e.__cause__, e.__context__):
        if x is not None and (isinstance(x, TimeoutError) or "timeout" in type(x).__name__.lower()):
            return True
    return False


def _is_connection(e: BaseException) -> bool:
    name = type(e).__name__.lower()
    return isinstance(e, ConnectionError) or any(w in name for w in ("connect", "network", "protocol"))


def _retry_delay(e: BaseException) -> float | None:
    """The server's RetryInfo delay in seconds (a 429 carries one), else None."""
    details = getattr(e, "details", None)
    error = details.get("error") if isinstance(details, dict) else None
    items = error.get("details") if isinstance(error, dict) else None
    for d in items if isinstance(items, list) else []:
        if isinstance(d, dict) and "RetryInfo" in str(d.get("@type", "")):
            try:
                return float(str(d.get("retryDelay", "")).strip().rstrip("s"))
            except ValueError:
                return None
    return None


def _classify(e: BaseException) -> str:
    """'retry' (same model again), 'next' (the next model) or 'stop' (give up)."""
    if isinstance(e, _Retry):
        return "next"
    code = getattr(e, "code", None)
    text = str(e)
    if code == 401 or "API_KEY_INVALID" in text or "API key not valid" in text:
        return "stop"
    if code == 429 and (_retry_delay(e) or 0) > LONG_WAIT:
        return "next"  # a quota (free tier: 20 requests a day per model) that a backoff won't outlast
    if code in RETRY_CODES:
        return "retry"
    if code == 504 or _is_timeout(e):
        return "next"  # the time is spent: retrying a slow model would spend it again
    if isinstance(code, int):
        return "next"  # 400, 403, 404: this model or feature is not available to us
    if _is_connection(e):
        return "retry"
    return "next"


def _json_schema(schema):
    """A dict schema with every "type" lower-cased (JSON Schema spelling; Gemini's OpenAPI dialect
    writes them upper-case). Other schemas pass through unchanged."""
    if isinstance(schema, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _json_schema(v)) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_json_schema(v) for v in schema]
    return schema


def _parse(text: str | None, schema) -> dict | list | str:
    if schema is None:
        if not text or not text.strip():
            raise _Retry("empty answer")
        return text
    if not text or not text.strip():
        raise _Retry("empty answer")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise _Retry(f"invalid JSON: {e}") from None
    if not isinstance(data, (dict, list)):
        raise _Retry(f"JSON answer is a {type(data).__name__}, not an object")
    return data


# ------------------------------------------------------------------- gemini


def _gemini_client(key: str):
    with _clients_lock:
        c = _clients.get(key)
        if c is None:
            from google import genai
            from google.genai import types

            c = genai.Client(api_key=key, http_options=types.HttpOptions(api_version=API_VERSION))
            _clients[key] = c
        return c


def _thinking(model: str, level: str | None):
    """A ThinkingConfig for `level` (minimal, low, medium, high), or None for the model's default.
    Gemini 2.x has no thinking levels: "minimal" there means a thinking budget of 0."""
    if not level:
        return None
    from google.genai import types

    if model.startswith("gemini-2"):
        return types.ThinkingConfig(thinking_budget=0) if level == "minimal" else None
    return types.ThinkingConfig(thinking_level=level)


def _gemini_once(model: str, prompt: str, image: bytes | None, image_mime: str, schema,
                 timeout: float, thinking: str | None) -> str | None:
    """One generate_content call; returns the answer's text. Raises on any failure."""
    from google.genai import types

    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    contents = [prompt] if image is None else [types.Part.from_bytes(data=image, mime_type=image_mime), prompt]
    config: dict = {"http_options": types.HttpOptions(timeout=max(1000, int(timeout * 1000)))}
    if schema is not None:
        config["response_mime_type"] = "application/json"
        if isinstance(schema, dict):
            config["response_json_schema"] = _json_schema(schema)
        else:
            config["response_schema"] = schema  # a pydantic model or another type the SDK takes
    thinking_config = _thinking(model, thinking)
    if thinking_config is not None:
        config["thinking_config"] = thinking_config
    response = _gemini_client(key).models.generate_content(
        model=model, contents=contents, config=types.GenerateContentConfig(**config)
    )
    return response.text


def _cools(e: BaseException) -> bool:
    """A failure that says the model is busy or gone, not that the request was bad."""
    return getattr(e, "code", None) in (*RETRY_CODES, 404, 504) or _is_timeout(e)


def _cooldown_for(e: BaseException) -> float:
    """COOLDOWN, or the server's own retry delay when longer (a used-up daily quota), at most an hour."""
    return max(COOLDOWN, min(_retry_delay(e) or 0.0, MAX_COOLDOWN))


def _models() -> list[str]:
    """GEMINI_MODEL, then each GEMINI_FALLBACK_MODEL (comma-separated), without repeats."""
    primary = (os.environ.get("GEMINI_MODEL") or "").strip() or DEFAULT_GEMINI_MODEL
    fallbacks = [m.strip() for m in (os.environ.get("GEMINI_FALLBACK_MODEL") or "").split(",") if m.strip()]
    models = []
    for m in [primary] + (fallbacks or [DEFAULT_FALLBACK_MODEL]):
        if m not in models:
            models.append(m)
    return models


def _gemini(prompt: str, image: bytes | None, image_mime: str, schema, timeout: float,
            thinking: str | None):
    global last_model
    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        _warn("GEMINI_API_KEY is not set (put it in .env); no answer")
        return None
    models = _models()
    now = time.monotonic()
    order = [m for m in models if _cooldown.get(m, 0.0) <= now] or models  # all cooling: try anyway
    deadline = now + 2 * timeout + 10
    failures: list[str] = []
    for model in order:
        model_deadline = min(deadline, time.monotonic() + timeout)  # retries included
        for attempt in range(TRIES):
            left = model_deadline - time.monotonic()
            if left < 2:
                failures.append(f"{model}: out of time")
                break
            try:
                result = _parse(_gemini_once(model, prompt, image, image_mime, schema, left, thinking), schema)
            except Exception as e:
                kind = _classify(e)
                failures.append(f"{model}: {'timeout' if _is_timeout(e) else _describe(e)}")
                if kind == "stop":
                    _warn(f"gemini refused the request: {failures[-1]}")
                    return None
                if kind == "next" or attempt == TRIES - 1:
                    if _cools(e) and len(models) > 1:
                        rest = _cooldown_for(e)
                        _cooldown[model] = time.monotonic() + rest
                        failures[-1] = f"{failures[-1][:150]} (skipped for {rest:.0f} s)"
                    break
                pause = BACKOFF * 2 ** attempt + (random.uniform(0, 0.5) if BACKOFF else 0)
                time.sleep(max(0.0, min(pause, model_deadline - time.monotonic() - 2)))
                continue
            last_model = model
            _cooldown.pop(model, None)
            if failures:
                _warn(f"answered by {model} after: {'; '.join(failures)}")
            return result
    _warn(f"gemini gave no answer: {'; '.join(failures)}")
    return None


# ------------------------------------------------------------------- claude


def _claude(prompt: str, image: bytes | None, image_mime: str, schema, timeout: float):
    """Anthropic: a forced tool call whose input_schema is the schema. Reads APP_ANTHROPIC_API_KEY
    only; the SDK's own retries (2) cover 429, 5xx and overloaded."""
    global last_model
    key = (os.environ.get("APP_ANTHROPIC_API_KEY") or "").strip()
    if not key:
        _warn("APP_ANTHROPIC_API_KEY is not set (LLM_PROVIDER=claude); no answer")
        return None
    try:
        import anthropic
    except ImportError:
        _warn("LLM_PROVIDER=claude needs the anthropic package (pip install anthropic); no answer")
        return None
    model = (os.environ.get("CLAUDE_MODEL") or "").strip() or DEFAULT_CLAUDE_MODEL
    try:
        content: list[dict] = []
        if image is not None:
            data = base64.b64encode(image).decode("ascii")
            content.append({"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": data}})
        content.append({"type": "text", "text": prompt})
        kwargs: dict = {"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": content}]}
        if schema is not None:
            input_schema = schema if isinstance(schema, dict) else schema.model_json_schema()
            kwargs["tools"] = [{"name": "answer", "description": "Give the answer in this shape.",
                                "input_schema": _json_schema(input_schema)}]
            kwargs["tool_choice"] = {"type": "tool", "name": "answer"}
        message = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=2).messages.create(**kwargs)
        if schema is not None:
            for block in message.content:
                if getattr(block, "type", None) == "tool_use" and isinstance(block.input, dict):
                    last_model = model
                    return dict(block.input)
            _warn(f"claude ({model}) gave no tool call; no answer")
            return None
        text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", None) == "text")
        if not text.strip():
            _warn(f"claude ({model}) gave an empty answer")
            return None
        last_model = model
        return text
    except Exception as e:
        _warn(f"claude ({model}) gave no answer: {'timeout' if _is_timeout(e) else _describe(e)}")
        return None


# ---------------------------------------------------------------------- api


def complete(prompt: str, *, image: bytes | None = None, image_mime: str = "image/png",
             schema: dict | type | None = None, timeout: float = DEFAULT_TIMEOUT,
             thinking: str | None = None) -> dict | str | None:
    """Ask the configured model once. With `schema` (a JSON Schema dict, or a pydantic model) the
    answer is parsed JSON (a dict, or a list if the schema says so), else plain text. `timeout` is
    per model call in seconds; `thinking` is minimal, low, medium or high (Gemini only; None = the
    model's default). Never raises: any failure prints one stderr line and returns None."""
    try:
        name = provider()
        if name == "off":
            _warn("LLM_PROVIDER=off; no model call")
            return None
        if name == "gemini":
            return _gemini(prompt, image, image_mime, schema, float(timeout), thinking)
        if name == "claude":
            return _claude(prompt, image, image_mime, schema, float(timeout))
        _warn(f"unknown LLM_PROVIDER {name!r} (use gemini, claude or off); no model call")
        return None
    except Exception as e:  # a bug of ours, or an SDK import failure: still no exception for callers
        _warn(f"call failed: {_describe(e)}")
        return None


if __name__ == "__main__":
    t0 = time.time()
    answer = complete(
        'This is a connectivity check. Reply with {"ok": true}.',
        schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        thinking="minimal",
    )
    print(answer)
    print(f"({provider()}, model {last_model}, {time.time() - t0:.1f} s)", file=sys.stderr)
    sys.exit(0 if answer == {"ok": True} else 1)
