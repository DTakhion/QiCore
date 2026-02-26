# # api/main.py
# from __future__ import annotations

# from typing import Any, Dict

# from dotenv import load_dotenv
# load_dotenv()

# from fastapi import FastAPI, HTTPException, Depends
# from fastapi.security.api_key import APIKeyHeader
# from pydantic import BaseModel, Field

# from services.llm_adapters import normalize_llm_payload, LLMAdapterError
# from services.qicore_evaluator import evaluate_llm_answer
# from services.auth_api_key import authenticate_api_key_value, ClientAuth


# app = FastAPI(title="QiCore API", version="0.2.0")


# # --- Swagger Auth: muestra "Authorize" y usa header X-API-Key ---
# api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# class GateRequest(BaseModel):
#     engine: str = Field(..., description="openai|gemini|ollama|custom (según adaptador)")
#     payload: Dict[str, Any] = Field(..., description="Payload nativo del proveedor (Opción A)")


# @app.get("/health")
# def health() -> Dict[str, Any]:
#     return {"ok": True}


# def require_client_auth(api_key: str | None = Depends(api_key_header)) -> ClientAuth:
#     """
#     Dependency única: Swagger 'Authorize' provee el header, y aquí lo validamos contra Mongo/ENV.
#     """
#     return authenticate_api_key_value(api_key)


# @app.post("/v1/qicore/gate")
# def qicore_gate(
#     req: GateRequest,
#     auth: ClientAuth = Depends(require_client_auth),
# ) -> Dict[str, Any]:
#     try:
#         canonical = normalize_llm_payload(req.engine, req.payload)
#     except LLMAdapterError as e:
#         raise HTTPException(status_code=400, detail=str(e))
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=f"normalize_error: {type(e).__name__}: {e}")

#     try:
#         out = evaluate_llm_answer(
#             answer=canonical.answer,
#             prompt=canonical.prompt,
#             engine_name=canonical.engine,
#             provider_meta=canonical.meta,
#         )

#         out.setdefault("qicore", {}).setdefault("input", {})
#         out["qicore"]["input"]["client_id"] = auth.client_id
#         out["qicore"]["input"]["plan"] = auth.plan
#         out["qicore"]["input"]["key_id"] = auth.key_id
#         out["qicore"]["input"]["key_last4"] = auth.last4

#         return out
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"qicore_eval_error: {type(e).__name__}: {e}")

# api/main.py
from __future__ import annotations

from typing import Any, Dict
import time

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

from services.llm_adapters import normalize_llm_payload, LLMAdapterError
from services.qicore_evaluator import evaluate_llm_answer
from services.auth_api_key import (
    authenticate_api_key_value,
    ClientAuth,
    get_db,
)

from utils.usage_quota import quota_precheck, commit_usage, get_quota_state


app = FastAPI(title="QiCore API", version="0.2.0")


# --- Swagger Auth ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# --- Plan limits (puedes mover luego a config o Mongo) ---
PLAN_LIMITS = {
    "community": 10_000,
    "hobby": 10_000,
    "pro": 500_000,
}


class GateRequest(BaseModel):
    engine: str = Field(..., description="openai|gemini|ollama|custom (según adaptador)")
    payload: Dict[str, Any] = Field(..., description="Payload nativo del proveedor (Opción A)")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


def require_client_auth(api_key: str | None = Depends(api_key_header)) -> ClientAuth:
    return authenticate_api_key_value(api_key)


def estimate_tokens(text: str) -> int:
    """
    Estimación simple: ~1 token cada 3.5 caracteres (aprox español).
    Se puede reemplazar por tokenizador real más adelante.
    """
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


@app.post("/v1/qicore/gate")
def qicore_gate(
    req: GateRequest,
    auth: ClientAuth = Depends(require_client_auth),
) -> Dict[str, Any]:

    db = get_db()

    # ---- límite por plan ----
    limit_tokens = PLAN_LIMITS.get(auth.plan, 10_000)

    # ---- PRECHECK CUOTA ----
    state = quota_precheck(db, auth.client_id, limit_tokens)
    if state.exceeded:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "MONTHLY_TOKEN_QUOTA_EXCEEDED",
                "period": state.period,
                "used": state.used_tokens,
                "limit": state.limit_tokens,
            },
        )

    # ---- Normalización ----
    try:
        canonical = normalize_llm_payload(req.engine, req.payload)
    except LLMAdapterError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"normalize_error: {type(e).__name__}: {e}")

    # ---- Evaluación QiCore ----
    start_time = time.time()

    try:
        out = evaluate_llm_answer(
            answer=canonical.answer,
            prompt=canonical.prompt,
            engine_name=canonical.engine,
            provider_meta=canonical.meta,
        )

        latency_ms = int((time.time() - start_time) * 1000)

        # ---- Token estimation (temporal) ----
        tokens_in = estimate_tokens(canonical.prompt)
        tokens_out = estimate_tokens(canonical.answer)

        _, state_after = commit_usage(
            db,
            client_id=auth.client_id,
            plan=auth.plan,
            limit_tokens=limit_tokens,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            route="/v1/qicore/gate",
            engine=canonical.engine,
            status=200,
            latency_ms=latency_ms,
            meta={
                "key_id": auth.key_id,
                "engine": canonical.engine,
            },
        )

        # ---- Metadata QiCore ----
        out.setdefault("qicore", {}).setdefault("input", {})
        out["qicore"]["input"]["client_id"] = auth.client_id
        out["qicore"]["input"]["plan"] = auth.plan
        out["qicore"]["input"]["key_id"] = auth.key_id
        out["qicore"]["input"]["key_last4"] = auth.last4

        # ---- Agregamos estado de cuota en respuesta ----
        out["quota"] = {
            "period": state_after.period,
            "used": state_after.used_tokens,
            "limit": state_after.limit_tokens,
            "remaining": state_after.remaining_tokens,
            "exceeded": state_after.exceeded,
        }

        return out

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"qicore_eval_error: {type(e).__name__}: {e}")
    

@app.get("/v1/qicore/usage")
def qicore_usage(
    auth: ClientAuth = Depends(require_client_auth),
) -> Dict[str, Any]:
    """
    Retorna el consumo mensual del cliente autenticado (usage_monthly).
    """
    db = get_db()

    # mismo mapeo de límites por plan que usas en /gate
    limit_tokens = PLAN_LIMITS.get(auth.plan, 10_000)

    state = get_quota_state(db, auth.client_id, limit_tokens)

    return {
        "ok": True,
        "client_id": auth.client_id,
        "plan": auth.plan,
        "quota": {
            "period": state.period,
            "used": state.used_tokens,
            "limit": state.limit_tokens,
            "remaining": state.remaining_tokens,
            "exceeded": state.exceeded,
        },
    }