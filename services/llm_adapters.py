# services/llm_adapters.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


# -------------------------
# Canonical request schema
# -------------------------
@dataclass
class CanonicalLLMInput:
    engine: str
    prompt: Optional[str]
    answer: str
    messages: List[Dict[str, Any]]
    meta: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LLMAdapterError(ValueError):
    pass


# -------------------------
# Helpers
# -------------------------
def _first_non_empty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _ensure_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    return str(x)


def _coerce_messages(messages: Any) -> List[Dict[str, Any]]:
    """
    Normaliza mensajes a lista de {role, content}.
    Acepta formatos típicos: [{"role":"user","content":"..."}, ...]
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(messages, list):
        return out
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = _ensure_str(m.get("role") or m.get("author") or "")
        content = m.get("content")
        # content puede venir como string o como array (gemini-like)
        if isinstance(content, str):
            txt = content
        elif isinstance(content, list):
            # ej: [{"type":"text","text":"..."}]
            parts = []
            for p in content:
                if isinstance(p, dict):
                    parts.append(_ensure_str(p.get("text") or p.get("content") or ""))
                else:
                    parts.append(_ensure_str(p))
            txt = "\n".join([t for t in parts if t.strip()])
        elif isinstance(content, dict):
            txt = _ensure_str(content.get("text") or content.get("content") or "")
        else:
            txt = _ensure_str(content)
        if role and txt.strip():
            out.append({"role": role, "content": txt.strip()})
    return out


# -------------------------
# Adapters (per engine)
# -------------------------
def _adapt_openai(payload: Dict[str, Any]) -> CanonicalLLMInput:
    """
    Soporta:
    - middleware propio: {"prompt":..., "llm_response":...}
    - Chat Completions style: {"messages":[...], "choices":[{"message":{"content":...}}]}
    - Responses API style (algunas variantes): {"output":[...]} (best effort)
    """
    messages = _coerce_messages(payload.get("messages"))

    prompt = _first_non_empty(
        payload.get("prompt"),
        payload.get("input"),
        # si no hay prompt, intenta del último user message
        next((m["content"] for m in reversed(messages) if m.get("role") in ("user", "human")), None),
    )

    # 1) tu wrapper
    answer = _first_non_empty(payload.get("llm_response"), payload.get("answer"))

    # 2) chat completions
    if not answer and isinstance(payload.get("choices"), list) and payload["choices"]:
        ch0 = payload["choices"][0] if isinstance(payload["choices"][0], dict) else {}
        msg = ch0.get("message") if isinstance(ch0.get("message"), dict) else {}
        answer = _first_non_empty(msg.get("content"), ch0.get("text"))

    # 3) responses API (best effort)
    if not answer and isinstance(payload.get("output"), list):
        # output: [{type:"message", content:[{type:"output_text", text:"..."}]}]
        texts: List[str] = []
        for item in payload["output"]:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict):
                        texts.append(_ensure_str(c.get("text") or c.get("output_text") or ""))
        answer = "\n".join([t for t in texts if t.strip()]) or None

    if not answer:
        raise LLMAdapterError("openai: no pude extraer 'answer' desde el payload.")

    meta = {
        "model": payload.get("model"),
        "id": payload.get("id"),
        "usage": payload.get("usage"),
    }
    return CanonicalLLMInput(engine="openai", prompt=prompt, answer=answer, messages=messages, meta=meta)


def _adapt_gemini(payload: Dict[str, Any]) -> CanonicalLLMInput:
    """
    Soporta formatos típicos Gemini:
    - {"contents":[{"role":"user","parts":[{"text":"..."}]}], "candidates":[{"content":{"parts":[{"text":"..."}]}}]}
    - wrapper propio: {"prompt":..., "llm_response":...}
    """
    # wrapper
    prompt = _first_non_empty(payload.get("prompt"))
    answer = _first_non_empty(payload.get("llm_response"), payload.get("answer"))

    messages: List[Dict[str, Any]] = []
    contents = payload.get("contents")
    if isinstance(contents, list):
        for c in contents:
            if not isinstance(c, dict):
                continue
            role = _ensure_str(c.get("role") or "")
            parts = c.get("parts")
            txts: List[str] = []
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict):
                        txts.append(_ensure_str(p.get("text") or ""))
            msg_txt = "\n".join([t for t in txts if t.strip()]).strip()
            if role and msg_txt:
                messages.append({"role": role, "content": msg_txt})
        if not prompt:
            prompt = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), None)

    # candidates -> answer
    if not answer and isinstance(payload.get("candidates"), list) and payload["candidates"]:
        c0 = payload["candidates"][0] if isinstance(payload["candidates"][0], dict) else {}
        content = c0.get("content") if isinstance(c0.get("content"), dict) else {}
        parts = content.get("parts")
        txts: List[str] = []
        if isinstance(parts, list):
            for p in parts:
                if isinstance(p, dict):
                    txts.append(_ensure_str(p.get("text") or ""))
        answer = "\n".join([t for t in txts if t.strip()]) or None

    if not answer:
        raise LLMAdapterError("gemini: no pude extraer 'answer' desde el payload.")

    meta = {
        "model": payload.get("model"),
        "usage": payload.get("usageMetadata") or payload.get("usage"),
    }
    return CanonicalLLMInput(engine="gemini", prompt=prompt, answer=answer, messages=messages, meta=meta)


def _adapt_ollama(payload: Dict[str, Any]) -> CanonicalLLMInput:
    """
    Soporta payload de respuesta Ollama típico:
    - {"model":"...", "prompt":"...", "response":"..."}
    o wrapper: {"prompt":..., "llm_response":...}
    """
    prompt = _first_non_empty(payload.get("prompt"))
    answer = _first_non_empty(payload.get("llm_response"), payload.get("answer"), payload.get("response"))

    if not answer:
        raise LLMAdapterError("ollama: no pude extraer 'answer' desde el payload.")

    meta = {
        "model": payload.get("model"),
        "created_at": payload.get("created_at"),
        "eval_count": payload.get("eval_count"),
        "eval_duration": payload.get("eval_duration"),
    }
    return CanonicalLLMInput(engine="ollama", prompt=prompt, answer=answer, messages=[], meta=meta)


def _adapt_custom(payload: Dict[str, Any]) -> CanonicalLLMInput:
    """
    Formato canónico recomendado para integraciones propias:
    {
      "prompt": "...",
      "answer": "...",  // o llm_response
      "messages": [...]
    }
    """
    messages = _coerce_messages(payload.get("messages"))
    prompt = _first_non_empty(payload.get("prompt"), next((m["content"] for m in reversed(messages) if m.get("role") == "user"), None))
    answer = _first_non_empty(payload.get("answer"), payload.get("llm_response"))

    if not answer:
        raise LLMAdapterError("custom: debes enviar 'answer' o 'llm_response'.")

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return CanonicalLLMInput(engine="custom", prompt=prompt, answer=answer, messages=messages, meta=meta)


# -------------------------
# Public API
# -------------------------
def normalize_llm_payload(engine: str, payload: Dict[str, Any]) -> CanonicalLLMInput:
    """
    Normaliza payloads por engine a CanonicalLLMInput.
    """
    if not isinstance(payload, dict):
        raise LLMAdapterError("payload debe ser dict (JSON object).")

    e = (engine or "").strip().lower()
    if e in ("openai", "gpt", "chatgpt"):
        return _adapt_openai(payload)
    if e in ("gemini", "google"):
        return _adapt_gemini(payload)
    if e in ("ollama",):
        return _adapt_ollama(payload)
    if e in ("custom", "generic"):
        return _adapt_custom(payload)

    raise LLMAdapterError(f"engine '{engine}' no soportado. Usa: openai|gemini|ollama|custom")