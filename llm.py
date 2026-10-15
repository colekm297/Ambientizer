"""One door for every Claude call in the app (2026-10-14, Cole: "update the models to the most recent
frontier ... and its opus 5.5").

Why a helper instead of swapping model strings: Claude Opus 5.5 always thinks (thinking can't be
disabled), so a response can begin with thinking blocks, and thinking counts against max_tokens.
The old call sites read `response.content[0].text` with max_tokens sized for a bare answer; on
Opus 5.5 that would read a thinking block or truncate the reply. Here:
  - the model is pinned to MODEL,
  - effort is set explicitly (Opus 5.5 defaults to medium; small JSON jobs run at "low"),
  - max_tokens gets room for thinking,
  - text is read by block type, never by position,
  - server-side fallbacks are on, so a safety-classifier false positive retries on the model
    Anthropic recommends for that category instead of failing the request.
"""
MODEL = "claude-opus-5-5"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_MIN_MAX_TOKENS = 16000


class LLMRefusal(RuntimeError):
    """The model (and its fallback) declined. Callers that already catch Exception degrade as before."""


def llm_create(client, *, effort: str = "low", **kw):
    kw["model"] = MODEL
    kw["max_tokens"] = max(int(kw.get("max_tokens") or 0), _MIN_MAX_TOKENS)
    for k in ("temperature", "top_p", "top_k", "thinking"):
        kw.pop(k, None)
    extra = dict(kw.pop("extra_body", None) or {})
    oc = dict(extra.get("output_config") or {})
    oc.setdefault("effort", effort)
    extra["output_config"] = oc
    extra.setdefault("fallbacks", "default")
    headers = dict(kw.pop("extra_headers", None) or {})
    beta = headers.get("anthropic-beta")
    headers["anthropic-beta"] = f"{beta},{_FALLBACK_BETA}" if beta else _FALLBACK_BETA
    return client.messages.create(extra_body=extra, extra_headers=headers, **kw)


def llm_text(resp) -> str:
    if getattr(resp, "stop_reason", None) == "refusal":
        raise LLMRefusal(f"Claude declined ({getattr(getattr(resp, 'stop_details', None), 'category', None)})")
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
