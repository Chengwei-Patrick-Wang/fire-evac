"""LLM client (spec 7.5): one call, JSON-schema output, a timeout, None on failure.

    complete(prompt, *, image=None, image_mime="image/png", schema=None, timeout=30.0,
             thinking=None, models=None, role="report") -> dict | str | None   (a dict when schema is given)
    chain() -> list[str]                                         the Gemini models, in order
    spend_usd() -> float                                         what this process has spent on Claude, in dollars
    stats() -> dict                                              Claude calls, tokens and spend of this process

LLM_PROVIDER, read on every call (from the environment, else .env):
    gemini (default)  google-genai with GEMINI_API_KEY; the model chain below
    claude            anthropic with APP_ANTHROPIC_API_KEY (never ANTHROPIC_API_KEY, which would bill the
                      Claude Code plan); see Claude below
    off               no network, every call returns None (smoke tests, check_all, the offline demo)

Claude. `role` says what the call is for, and with it the model and how hard that model thinks:
    report  claude-opus-5-5   effort medium   report cards and their AI summary (CLAUDE_MODEL overrides the model)
    tracer  claude-opus-5-5   effort high     the tracer's first pass on a floor-plan image (CLAUDE_MODEL)
    agent   claude-haiku-5-5  effort low      evacuee decisions of the sim's llm and mixed brains (CLAUDE_AGENT_MODEL)
Each call asks for the answer as structured output (output_config format json_schema), so the first text block
is JSON: no tool use is forced (tool_choice any/tool is a 400 on Opus 5.5). Opus always thinks and its thinking
tokens are billed as output, so depth is set by `effort` only; the call sends no thinking, temperature, top_p or
top_k, and no prefill (each is a 400 there). Opus calls go through the beta endpoint with the server-side
fallback ("server-side-fallback-2026-07-01", fallbacks "default"); Haiku calls are plain. The SDK retries 429 and
5xx twice (max_retries=2). A refusal (stop_reason "refusal"), a cut-off answer, a bad request, an error that
outlasts the retries or a timeout gives None, so report cards fall back to the template, the tracer to nothing
and the agents to the rules. The caller's `timeout` is raised to the role's own least time (an Opus call
thinks for a while: 90 s for a report card, 150 s for the tracer), except the agent role's, which is exactly 15 s so
that a stalled Haiku request is retried by the SDK soon; the retries can multiply a timeout by three for a call that
keeps timing out.
Agent calls come in a loop (one batch per simulated second), so after one fails at the network (a timeout, a
connection error, a 429 or a 5xx that the retries did not fix) the agent role is paused for AGENT_PAUSE seconds and
answers None at once: the sim carries on with its rules instead of waiting out every call.
Spend: every answered call adds usage x price (PRICES, $ per million tokens) to a per-process total, read with
spend_usd(). When the total passes CLAUDE_BUDGET_USD (default 25) one stderr line says so and every later call
returns None. The total is per process: an API run is simulated in a pool worker, which counts its own calls.

Gemini is slow and busy at times. Measured Sat 3 AM: gemini-3.5-flash took 1-13 s for a one-line
JSON ping at its default thinking, 1-5 s at thinking "minimal", once a 504 after 44 s, and for a
while only 503 "high demand" (0.3-13 s each); 3.6, 3.7 and 3.8-flash also answered 503;
gemini-2.5-flash answered in under 1 s. Vision calls take 5-20 s, once 57 s. The team key is on
the free tier: 20 requests a day per model (429 RESOURCE_EXHAUSTED, quota
GenerateRequestsPerDayPerProjectPerModel-FreeTier), so the client walks a chain of models:
    GEMINI_MODEL, then GEMINI_FALLBACK_MODEL (default gemini-2.5-flash), then CHAIN_TAIL
    (gemini-3.6-flash, gemini-3.7-flash, gemini-3.1-flash-lite); both variables may list several
    models, comma-separated; a model is tried once per call. A caller may pass its own order
    (`models`): the tracer's first pass puts Gemini 2.x last (much worse at geometry).
Each call goes:
    429 (a used-up quota or a rate limit) or 503 (busy): straight to the next model in the chain;
    500, 502 or a dropped connection: retry the same model (3 tries, backoff 1 s, 2 s), then next;
    a timeout or 504, a 400, 403 or 404 (model or feature missing), invalid JSON or an empty
        answer: straight to the next model;
    401, or an invalid key: give up.
Each model gets `timeout` seconds, retries included, and the whole call stops after 2 x timeout +
10 s. A model that ends busy (429, 5xx, timeout) or missing (404) is skipped for COOLDOWN (120 s),
or for the server's retry delay up to an hour (a used-up daily quota), so the calls after it go
straight to the next model. Every answer logs one stderr line naming the model that gave it.
Requests use API version v1beta: v1 rejects JSON mode on gemini-2.5-flash (measured).
google-genai is imported on the first call, so importing this module is cheap. A failure prints
one stderr line (never a key) and returns None, so callers fall back.

    python -m backend.llm.client [report|tracer|agent]   # ping with a JSON schema; prints {'ok': True}
"""
from __future__ import annotations

import base64
import json
import math
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
# Tried after GEMINI_MODEL and GEMINI_FALLBACK_MODEL: each model has its own free-tier quota.
CHAIN_TAIL = ("gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite")
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"  # report and tracer roles; CLAUDE_MODEL overrides it
DEFAULT_AGENT_MODEL = "claude-haiku-5-5"  # the agent role; CLAUDE_AGENT_MODEL overrides it
# role -> the environment variable that overrides its model, the default model, the output_config effort, max_tokens
# (Opus's thinking tokens count against it), whether the call asks for the server-side fallback, and the timeout in
# seconds of one request: at least this for a caller that asked for less, except where "exact" says it is this and no
# other. Measured Sat evening: a report card took 28-37 s (900 output tokens: Opus 5.5 writes about 30 tokens a
# second), the tracer 34 s for 12 rooms (a 60-room plan is about 4 times the output), Haiku 1.5-2 s for 5 decisions and
# 4-5 s for 20 (once 9.6 s, a first call). The agent's is short and exact because a request that stalls (one did, for over
# 30 s, in the first all-Claude run: its 8 first decisions fell back to the rules) should be given up and sent again by
# the SDK's retry after 15 s, not 30, while the sim is still waiting for the round.
CLAUDE_ROLES = {
    "report": {"env": "CLAUDE_MODEL", "model": DEFAULT_CLAUDE_MODEL, "effort": "medium", "max_tokens": 16000,
               "fallbacks": True, "timeout": 90.0},
    "tracer": {"env": "CLAUDE_MODEL", "model": DEFAULT_CLAUDE_MODEL, "effort": "high", "max_tokens": 32000,
               "fallbacks": True, "timeout": 150.0},
    "agent": {"env": "CLAUDE_AGENT_MODEL", "model": DEFAULT_AGENT_MODEL, "effort": "low", "max_tokens": 8000,
              "fallbacks": False, "timeout": 15.0, "exact": True},
}
CLAUDE_RETRIES = 2  # the SDK's own retries of 429, 5xx and dropped connections
CLAUDE_CONNECT_S = 10.0  # s to open a connection before the call gives up on it (a dead network costs this, not the timeout)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
AGENT_PAUSE = 20.0  # s the agent role answers None at once after a network failure
DEFAULT_BUDGET_USD = 25.0  # CLAUDE_BUDGET_USD
# $ per million tokens, (input, output); a model id is matched by its longest known prefix. Anthropic's list prices.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5-2": (8.0, 40.0),
    "claude-fable-5": (10.0, 50.0),
}
UNKNOWN_PRICE = (10.0, 50.0)  # a model that is not above (a CLAUDE_MODEL override): priced high, so the budget errs early
API_VERSION = "v1beta"
NEXT_CODES = (429, 503)  # quota, rate limit or busy: the next model in the chain, at once
RETRY_CODES = (500, 502)  # a hiccup: the same model again
BUSY_CODES = (*NEXT_CODES, *RETRY_CODES)
TRIES = 3  # per model, for RETRY_CODES and dropped connections
BACKOFF = 1.0  # s before the first retry, doubled for each next one (the smoke test sets 0)
COOLDOWN = 120.0  # s a busy or missing model is skipped for, while another model is configured
MAX_COOLDOWN = 3600.0  # s; a used-up daily quota is checked again hourly (one quick 429)
KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "APP_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")

last_model: str | None = None  # the model behind the latest successful call (for logs only)

_clients: dict[str, object] = {}
_clients_lock = threading.Lock()
_cooldown: dict[str, float] = {}  # model -> time.monotonic() until which it is skipped

_claude_clients: dict[tuple[str, float], object] = {}  # (key, timeout) -> anthropic.Anthropic, under _clients_lock
_spend_lock = threading.Lock()
_spent = 0.0  # dollars, this process
_calls = {"calls": 0, "answered": 0, "inputTokens": 0, "outputTokens": 0}
_by_role: dict[str, int] = {}
_budget_noted = False
_agent_paused_until = 0.0  # time.monotonic(); see AGENT_PAUSE


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


def _failure(model: str, e: BaseException) -> str:
    """One failed try for the log, short enough that a whole chain fits on the line: "m: timeout",
    "m: 429 RESOURCE_EXHAUSTED", "m: 400 INVALID_ARGUMENT <message>". Keys are blanked before
    anything is cut, so a cut can never leave half a key."""
    if _is_timeout(e):
        return f"{model}: timeout"
    code = getattr(e, "code", None)
    if isinstance(code, int):
        status = getattr(e, "status", None) or ""
        detail = "" if code in NEXT_CODES else " " + _scrub(getattr(e, "message", None) or str(e))[:60]
        return f"{model}: {code} {status}".rstrip() + detail
    return f"{model}: {_scrub(_describe(e))[:80]}"


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
    if code in NEXT_CODES or "RESOURCE_EXHAUSTED" in text:
        return "next"  # a quota (free tier: 20 requests a day per model) or a busy model
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
    return getattr(e, "code", None) in (*BUSY_CODES, 404, 504) or _is_timeout(e)


def _cooldown_for(e: BaseException) -> float:
    """COOLDOWN, or the server's own retry delay when longer (a used-up daily quota), at most an hour."""
    return max(COOLDOWN, min(_retry_delay(e) or 0.0, MAX_COOLDOWN))


def _names(variable: str) -> list[str]:
    return [m.strip() for m in (os.environ.get(variable) or "").split(",") if m.strip()]


def chain() -> list[str]:
    """The Gemini models a call tries, in order (see the module docstring)."""
    return _models()


def _models() -> list[str]:
    """The chain: GEMINI_MODEL, then GEMINI_FALLBACK_MODEL (each comma-separated, with defaults),
    then CHAIN_TAIL, without repeats."""
    models: list[str] = []
    named = (_names("GEMINI_MODEL") or [DEFAULT_GEMINI_MODEL]) + (_names("GEMINI_FALLBACK_MODEL") or [DEFAULT_FALLBACK_MODEL])
    for m in named + list(CHAIN_TAIL):
        if m not in models:
            models.append(m)
    return models


def _gemini(prompt: str, image: bytes | None, image_mime: str, schema, timeout: float,
            thinking: str | None, chain_override: list[str] | None = None):
    global last_model
    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        _warn("GEMINI_API_KEY is not set (put it in .env); no answer")
        return None
    models = list(dict.fromkeys(m for m in chain_override or [] if m)) or _models()
    start = now = time.monotonic()
    order = [m for m in models if _cooldown.get(m, 0.0) <= now] or models  # all cooling: try anyway
    deadline = now + 2 * timeout + 10
    failures: list[str] = []
    for model in order:
        if deadline - time.monotonic() < 2:
            failures.append(f"out of time before {model}")
            break
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
                failures.append(_failure(model, e))
                if kind == "stop":
                    _warn(f"gemini refused the request: {failures[-1]}")
                    return None
                if kind == "next" or attempt == TRIES - 1:
                    if _cools(e) and len(models) > 1:
                        rest = _cooldown_for(e)
                        _cooldown[model] = time.monotonic() + rest
                        failures[-1] = f"{failures[-1]} (skipped for {rest:.0f} s)"
                    break
                pause = BACKOFF * 2 ** attempt + (random.uniform(0, 0.5) if BACKOFF else 0)
                time.sleep(max(0.0, min(pause, model_deadline - time.monotonic() - 2)))
                continue
            last_model = model
            _cooldown.pop(model, None)
            after = f" after: {'; '.join(failures)}" if failures else ""
            _warn(f"answered by {model} in {time.monotonic() - start:.1f} s{after}")
            return result
    _warn(f"gemini gave no answer: {'; '.join(failures)}")
    return None


# ------------------------------------------------------------------- claude


def spend_usd() -> float:
    """Dollars this process has spent on Claude so far: each answered call's usage x its model's price."""
    with _spend_lock:
        return _spent


def stats() -> dict:
    """This process's Claude counters: calls (made), answered (usable), inputTokens, outputTokens, spendUsd and the
    calls by role."""
    with _spend_lock:
        return {**_calls, "spendUsd": round(_spent, 6), "byRole": dict(_by_role)}


def reset_stats() -> None:
    """Zero the counters, the budget note and the agent pause (the smoke test, or a process that wants a fresh total)."""
    global _spent, _budget_noted, _agent_paused_until
    with _spend_lock:
        _spent = 0.0
        _budget_noted = False
        _agent_paused_until = 0.0
        for name in _calls:
            _calls[name] = 0
        _by_role.clear()


def budget_usd() -> float:
    """CLAUDE_BUDGET_USD in dollars; an empty, bad or negative value means the default (25)."""
    text = (os.environ.get("CLAUDE_BUDGET_USD") or "").strip()
    try:
        value = float(text) if text else DEFAULT_BUDGET_USD
    except ValueError:
        return DEFAULT_BUDGET_USD
    return value if math.isfinite(value) and value >= 0 else DEFAULT_BUDGET_USD


def _price(model: str) -> tuple[float, float]:
    known = [m for m in PRICES if model.startswith(m)]
    return PRICES[max(known, key=len)] if known else UNKNOWN_PRICE


def _budget_note(total: float) -> None:
    _warn(f"Claude budget passed: ${total:.2f} spent in this process, CLAUDE_BUDGET_USD is ${budget_usd():.2f}; "
          "no more Claude calls here (report cards use the template, agents the rules)")


def _over_budget() -> bool:
    """True once the process total has passed the budget; the first time, one stderr line says so."""
    global _budget_noted
    with _spend_lock:
        over, total = _spent > budget_usd(), _spent
        say = over and not _budget_noted
        _budget_noted = _budget_noted or over
    if say:
        _budget_note(total)
    return over


def _charge(model: str, usage) -> None:
    """Add one answered call's usage x price to the process total (and the budget note, the first time it is passed)."""
    global _spent, _budget_noted
    tokens_in = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    tokens_out = max(0, int(getattr(usage, "output_tokens", 0) or 0))
    price_in, price_out = _price(model)
    with _spend_lock:
        _spent += (tokens_in * price_in + tokens_out * price_out) / 1e6
        _calls["inputTokens"] += tokens_in
        _calls["outputTokens"] += tokens_out
        say, total = _spent > budget_usd() and not _budget_noted, _spent
        _budget_noted = _budget_noted or say
    if say:
        _budget_note(total)


def _claude_client(key: str, timeout: float):
    """The anthropic client for this key and timeout: one per pair, so the connections are reused. The SDK retries
    429 and 5xx (and a dropped connection) CLAUDE_RETRIES times by itself."""
    with _clients_lock:
        c = _claude_clients.get((key, timeout))
        if c is None:
            import anthropic

            c = anthropic.Anthropic(api_key=key, max_retries=CLAUDE_RETRIES,
                                    timeout=anthropic.Timeout(timeout, connect=min(CLAUDE_CONNECT_S, timeout)))
            _claude_clients[(key, timeout)] = c
        return c


def _strict(schema):
    """The schema with additionalProperties false and a required list on every object, which structured outputs
    insist on (the shared schemas stay as Gemini takes them)."""
    if isinstance(schema, dict):
        out = {k: _strict(v) for k, v in schema.items()}
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
            if isinstance(out.get("properties"), dict):
                out.setdefault("required", list(out["properties"]))
        return out
    if isinstance(schema, list):
        return [_strict(v) for v in schema]
    return schema


def _claude_text(message, want_json: bool) -> str:
    """The answer's text: the first text block for JSON (structured output), all of them joined for plain text. After
    a server-side fallback only the fallback model's blocks, which follow its `fallback` block, count."""
    blocks = list(getattr(message, "content", None) or [])
    for k in range(len(blocks) - 1, -1, -1):
        if getattr(blocks[k], "type", None) == "fallback":
            blocks = blocks[k + 1:]
            break
    texts = [getattr(b, "text", None) or "" for b in blocks if getattr(b, "type", None) == "text"]
    return (texts[0] if texts else "") if want_json else "".join(texts)


def _claude_failure(model: str, role: str, e: BaseException, timeout: float) -> str:
    if _is_timeout(e):
        what = f"timeout ({timeout:.0f} s)"
    elif isinstance(getattr(e, "status_code", None), int):
        what = f"{e.status_code} {_scrub(str(getattr(e, 'message', None) or e))[:120]}"
    else:
        what = f"{type(e).__name__}: {_scrub(str(e))[:120]}"
    return f"claude ({model}, {role}) gave no answer: {what}"


def _claude(prompt: str, image: bytes | None, image_mime: str, schema, timeout: float, role: str = "report"):
    """Anthropic: structured output, the role's model and effort, server-side fallback for Opus (module docstring).
    Reads APP_ANTHROPIC_API_KEY only. None on a refusal, a cut-off or empty answer, any API error or the budget."""
    global last_model, _agent_paused_until
    key = (os.environ.get("APP_ANTHROPIC_API_KEY") or "").strip()
    if not key:
        _warn("APP_ANTHROPIC_API_KEY is not set (LLM_PROVIDER=claude); no answer")
        return None
    try:
        import anthropic
    except ImportError:
        _warn("LLM_PROVIDER=claude needs the anthropic package (pip install anthropic==2.8.0); no answer")
        return None
    spec = CLAUDE_ROLES.get(role) or CLAUDE_ROLES["report"]
    model = (os.environ.get(spec["env"]) or "").strip() or spec["model"]
    if _over_budget() or (role == "agent" and time.monotonic() < _agent_paused_until):
        return None
    timeout = spec["timeout"] if spec.get("exact") else max(timeout, spec["timeout"])
    with _spend_lock:
        _calls["calls"] += 1
        _by_role[role] = _by_role.get(role, 0) + 1
    try:
        content: list[dict] = []
        if image is not None:
            data = base64.b64encode(image).decode("ascii")
            content.append({"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": data}})
        content.append({"type": "text", "text": prompt})
        output_config: dict = {"effort": spec["effort"]}
        if schema is not None:
            wanted = schema if isinstance(schema, dict) else schema.model_json_schema()
            output_config["format"] = {"type": "json_schema", "schema": _strict(_json_schema(wanted))}
        kwargs: dict = {"model": model, "max_tokens": spec["max_tokens"], "output_config": output_config,
                        "messages": [{"role": "user", "content": content}]}
        client = _claude_client(key, timeout)
        if spec["fallbacks"]:
            message = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            message = client.messages.create(**kwargs)
        served = getattr(message, "model", None) or model
        _charge(served, getattr(message, "usage", None))
        reason = getattr(message, "stop_reason", None)
        if reason == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            _warn(f"claude ({model}, {role}) refused{f' ({category})' if category else ''}; no answer")
            return None
        if reason not in (None, "end_turn", "stop_sequence"):
            _warn(f"claude ({model}, {role}) stopped with {reason} before it finished; no answer")
            return None
        try:
            answer = _parse(_claude_text(message, schema is not None), schema)
        except _Retry as e:
            _warn(f"claude ({model}, {role}) gave no usable answer: {e}")
            return None
        with _spend_lock:
            _calls["answered"] += 1
        last_model = served
        return answer
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        code = getattr(e, "status_code", None)
        down = isinstance(e, anthropic.APIConnectionError) or (isinstance(code, int) and (code == 429 or code >= 500))
        pause = down and role == "agent"
        if pause:
            _agent_paused_until = time.monotonic() + AGENT_PAUSE
        _warn(_claude_failure(model, role, e, timeout) + (f"; agent calls pause for {AGENT_PAUSE:.0f} s" if pause else ""))
        return None
    except Exception as e:
        _warn(_claude_failure(model, role, e, timeout))
        return None


# ---------------------------------------------------------------------- api


def warm_up() -> None:
    """Import the configured provider's SDK now, not inside its first call: anthropic takes 5 to 20 s to import (measured
    on a busy laptop), which would eat a decision round's wait or the first report card's time. Never raises."""
    try:
        name = provider()
        if name == "claude":
            import anthropic  # noqa: F401
        elif name == "gemini":
            from google import genai  # noqa: F401
    except Exception:  # noqa: BLE001 - the call itself reports a missing package
        pass


def complete(prompt: str, *, image: bytes | None = None, image_mime: str = "image/png",
             schema: dict | type | None = None, timeout: float = DEFAULT_TIMEOUT,
             thinking: str | None = None, models: list[str] | None = None,
             role: str = "report") -> dict | str | None:
    """Ask the configured model once. With `schema` (a JSON Schema dict, or a pydantic model) the
    answer is parsed JSON (a dict, or a list if the schema says so), else plain text. `timeout` is
    per model call in seconds (Claude raises it to the role's own least); `thinking` is minimal, low,
    medium or high (Gemini only; None = the model's default); `models` replaces the Gemini chain for
    this call. `role` (Claude only) is "report" (the default), "tracer" or "agent": it picks the model
    and the effort (module docstring). Never raises: any failure prints one stderr line and returns None."""
    try:
        name = provider()
        if name == "off":
            _warn("LLM_PROVIDER=off; no model call")
            return None
        if name == "gemini":
            return _gemini(prompt, image, image_mime, schema, float(timeout), thinking, models)
        if name == "claude":
            return _claude(prompt, image, image_mime, schema, float(timeout), role if role in CLAUDE_ROLES else "report")
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
        role=sys.argv[1] if len(sys.argv) > 1 else "report",
    )
    print(answer)
    cost = f", ${spend_usd():.4f}" if provider() == "claude" else ""
    print(f"({provider()}, model {last_model}, {time.time() - t0:.1f} s{cost})", file=sys.stderr)
    sys.exit(0 if answer == {"ok": True} else 1)
