# # services/auth_api_key.py
# from __future__ import annotations

# import json
# import os
# from dataclasses import dataclass
# from typing import Any, Dict, Optional, Tuple

# import bcrypt
# from fastapi import Header, HTTPException
# from pymongo import MongoClient
# from pymongo.collection import Collection


# # ----------------------------
# # Models
# # ----------------------------
# @dataclass(frozen=True)
# class ClientAuth:
#     client_id: str
#     api_key: str  # ojo: nunca loguear completa
#     plan: str = "community"
#     rpm: int = 60
#     rpd: int = 5000
#     key_id: str = "key_01"
#     last4: str = "0000"


# # ----------------------------
# # ENV fallback (legacy)
# # ----------------------------
# def _load_keys_from_env() -> Dict[str, str]:
#     """
#     Legacy mapping api_key -> client_id desde ENV.
#     Útil solo como fallback temporal.
#     """
#     raw = (os.getenv("QICORE_API_KEYS") or "").strip()
#     if raw:
#         try:
#             data = json.loads(raw)
#             if isinstance(data, dict):
#                 return {str(k): str(v) for k, v in data.items()}
#         except Exception:
#             pass

#     single_key = (os.getenv("QICORE_API_KEY") or "").strip()
#     single_client = (os.getenv("QICORE_CLIENT_ID") or "").strip()
#     if single_key and single_client:
#         return {single_key: single_client}

#     return {}


# # ----------------------------
# # Mongo (source of truth)
# # ----------------------------
# _MONGO_CLIENT: Optional[MongoClient] = None


# def _get_clients_collection() -> Collection:
#     """
#     Returns Mongo collection for api clients. Uses singleton MongoClient.
#     """
#     global _MONGO_CLIENT

#     mongo_uri = (os.getenv("MONGO_URI") or "").strip()
#     db_name = (os.getenv("DB_NAME") or "").strip() or "clientRecommender"
#     coll_name = (os.getenv("API_CLIENTS_COLLECTION") or "").strip() or "api_clients"

#     if not mongo_uri:
#         raise RuntimeError("Missing MONGO_URI in environment.")

#     if _MONGO_CLIENT is None:
#         _MONGO_CLIENT = MongoClient(mongo_uri)

#     db = _MONGO_CLIENT[db_name]
#     return db[coll_name]


# def _mongo_authenticate(api_key: str) -> Tuple[str, Dict[str, Any]]:
#     """
#     Find matching client by checking bcrypt against stored hashes.

#     Returns:
#       (client_id, key_record) where key_record is the matched auth.keys[] entry.

#     NOTE: This is O(N) over active clients/keys. OK for early stage.
#     For scale, move to lookup by key_id + HMAC or store a keyed digest index.
#     """
#     coll = _get_clients_collection()

#     cursor = coll.find({"status": "active"}, {"auth": 1})
#     for doc in cursor:
#         client_id = str(doc.get("_id", "")) or ""
#         auth = doc.get("auth") or {}
#         keys = auth.get("keys") or []

#         for k in keys:
#             if not isinstance(k, dict):
#                 continue
#             if k.get("revoked_at") is not None:
#                 continue

#             stored_hash = k.get("hash")
#             if not stored_hash:
#                 continue

#             try:
#                 ok = bcrypt.checkpw(api_key.encode("utf-8"), str(stored_hash).encode("utf-8"))
#             except Exception:
#                 ok = False

#             if ok:
#                 return client_id, k

#     raise HTTPException(status_code=403, detail="API key inválida.")


# # ----------------------------
# # Core validator (string in -> ClientAuth out)
# # ----------------------------
# def authenticate_api_key_value(api_key_value: Optional[str]) -> ClientAuth:
#     """
#     Valida una API key ya extraída (string). Ideal para integrarla con Swagger APIKeyHeader sin redundancia.
#     """
#     if not api_key_value:
#         raise HTTPException(status_code=401, detail="Falta header X-API-Key.")

#     api_key = api_key_value.strip()

#     # 1) Mongo primero
#     try:
#         client_id, key_rec = _mongo_authenticate(api_key)
#         return ClientAuth(
#             client_id=client_id,
#             api_key=api_key,
#             plan="community",
#             rpm=60,
#             rpd=5000,
#             key_id=str(key_rec.get("key_id", "key_01")),
#             last4=str(key_rec.get("last4", "0000")),
#         )
#     except RuntimeError:
#         # Mongo no configurado
#         pass
#     except HTTPException:
#         raise
#     except Exception:
#         raise HTTPException(status_code=500, detail="Error validando API key (Mongo).")

#     # 2) Fallback ENV (temporal)
#     keys = _load_keys_from_env()
#     if not keys:
#         raise HTTPException(
#             status_code=500,
#             detail="Auth no configurada: Mongo (MONGO_URI/DB_NAME) o legacy ENV (QICORE_API_KEYS).",
#         )

#     client_id = keys.get(api_key)
#     if not client_id:
#         raise HTTPException(status_code=403, detail="API key inválida.")

#     return ClientAuth(client_id=str(client_id), api_key=api_key)


# # ----------------------------
# # FastAPI dependency (Header wrapper)
# # ----------------------------
# def authenticate_api_key(
#     x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
# ) -> ClientAuth:
#     """
#     Dependency FastAPI clásica: toma el header y delega al validador core.
#     """
#     return authenticate_api_key_value(x_api_key)

# services/auth_api_key.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import bcrypt
from fastapi import Header, HTTPException
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database


# ----------------------------
# Models
# ----------------------------
@dataclass(frozen=True)
class ClientAuth:
    client_id: str
    api_key: str  # ojo: nunca loguear completa
    plan: str = "community"
    rpm: int = 60
    rpd: int = 5000
    key_id: str = "key_01"
    last4: str = "0000"


# ----------------------------
# ENV fallback (legacy)
# ----------------------------
def _load_keys_from_env() -> Dict[str, str]:
    """
    Legacy mapping api_key -> client_id desde ENV.
    Útil solo como fallback temporal.
    """
    raw = (os.getenv("QICORE_API_KEYS") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass

    single_key = (os.getenv("QICORE_API_KEY") or "").strip()
    single_client = (os.getenv("QICORE_CLIENT_ID") or "").strip()
    if single_key and single_client:
        return {single_key: single_client}

    return {}


# ----------------------------
# Mongo (source of truth)
# ----------------------------
_MONGO_CLIENT: Optional[MongoClient] = None


def get_db() -> Database:
    """
    Retorna la DB Mongo (ej: clientRecommender) usando el singleton MongoClient.
    Útil para que otros módulos (usage_quota) escriban en usage_monthly/events.
    """
    global _MONGO_CLIENT

    mongo_uri = (os.getenv("MONGO_URI") or "").strip()
    db_name = (os.getenv("DB_NAME") or "").strip() or "clientRecommender"

    if not mongo_uri:
        raise RuntimeError("Missing MONGO_URI in environment.")

    if _MONGO_CLIENT is None:
        _MONGO_CLIENT = MongoClient(mongo_uri)

    return _MONGO_CLIENT[db_name]


def _get_clients_collection() -> Collection:
    """
    Returns Mongo collection for api clients. Uses singleton MongoClient.
    """
    db = get_db()
    coll_name = (os.getenv("API_CLIENTS_COLLECTION") or "").strip() or "api_clients"
    return db[coll_name]


def _mongo_authenticate(api_key: str) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Find matching client by checking bcrypt against stored hashes.

    Returns:
      (client_id, key_record, client_doc) where key_record is the matched auth.keys[] entry.

    NOTE: This is O(N) over active clients/keys. OK for early stage.
    For scale, move to lookup by key_id + HMAC or store a keyed digest index.
    """
    coll = _get_clients_collection()

    # Traemos solo lo necesario (y usage para plan/rate limits)
    cursor = coll.find({"status": "active"}, {"auth": 1, "usage": 1, "status": 1})
    for doc in cursor:
        client_id = str(doc.get("_id", "")) or ""
        auth = doc.get("auth") or {}
        keys = auth.get("keys") or []

        for k in keys:
            if not isinstance(k, dict):
                continue
            if k.get("revoked_at") is not None:
                continue

            stored_hash = k.get("hash")
            if not stored_hash:
                continue

            try:
                ok = bcrypt.checkpw(api_key.encode("utf-8"), str(stored_hash).encode("utf-8"))
            except Exception:
                ok = False

            if ok:
                return client_id, k, doc

    raise HTTPException(status_code=403, detail="API key inválida.")


# ----------------------------
# Core validator (string in -> ClientAuth out)
# ----------------------------
def authenticate_api_key_value(api_key_value: Optional[str]) -> ClientAuth:
    """
    Valida una API key ya extraída (string). Ideal para integrarla con Swagger APIKeyHeader sin redundancia.
    """
    if not api_key_value:
        raise HTTPException(status_code=401, detail="Falta header X-API-Key.")

    api_key = api_key_value.strip()

    # 1) Mongo primero
    try:
        client_id, key_rec, client_doc = _mongo_authenticate(api_key)

        # Plan real desde Mongo (api_clients.usage.plan)
        usage = client_doc.get("usage") or {}
        plan = str(usage.get("plan") or "community")

        # (Opcional) En el futuro puedes leer rpm/rpd desde usage.rate_limit si lo guardan ahí.
        # Por ahora dejamos defaults seguros.
        return ClientAuth(
            client_id=client_id,
            api_key=api_key,
            plan=plan,
            rpm=60,
            rpd=5000,
            key_id=str(key_rec.get("key_id", "key_01")),
            last4=str(key_rec.get("last4", "0000")),
        )
    except RuntimeError:
        # Mongo no configurado
        pass
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Error validando API key (Mongo).")

    # 2) Fallback ENV (temporal)
    keys = _load_keys_from_env()
    if not keys:
        raise HTTPException(
            status_code=500,
            detail="Auth no configurada: Mongo (MONGO_URI/DB_NAME) o legacy ENV (QICORE_API_KEYS).",
        )

    client_id = keys.get(api_key)
    if not client_id:
        raise HTTPException(status_code=403, detail="API key inválida.")

    return ClientAuth(client_id=str(client_id), api_key=api_key)


# ----------------------------
# FastAPI dependency (Header wrapper)
# ----------------------------
def authenticate_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ClientAuth:
    """
    Dependency FastAPI clásica: toma el header y delega al validador core.
    """
    return authenticate_api_key_value(x_api_key)