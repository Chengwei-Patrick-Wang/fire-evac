"""LLM client and features (spec 7.5): callers write llm.report(...), llm.decide(obs),
llm.propose_plan(image, hints).

The names below load on first use (PEP 562), so `import backend.llm` stays cheap and
`python -m backend.llm.features` does not import the module twice. google-genai and anthropic are
imported on the first model call (anthropic takes seconds to import: client.warm_up() does it ahead of time).
"""
_FROM = {
    "complete": "client", "provider": "client", "spend_usd": "client", "stats": "client",
    "decide": "features", "decide_batch": "features", "report": "features", "report_card": "features",
    "propose_plan": "features", "sanitize_floor": "features",
}
__all__ = sorted(_FROM)


def __getattr__(name: str):
    if name in _FROM:
        from importlib import import_module

        return getattr(import_module(f".{_FROM[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
