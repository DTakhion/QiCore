# utils/usage_quota.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pymongo import ReturnDocument
from pymongo.database import Database


# -------------------------
# Models
# -------------------------
@dataclass(frozen=True)
class QuotaState:
    period: str
    used_tokens: int
    limit_tokens: int
    remaining_tokens: int
    exceeded: bool


# -------------------------
# Period helpers
# -------------------------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def month_period(dt: Optional[datetime] = None) -> str:
    dt = dt or utc_now()
    return f"{dt.year:04d}-{dt.month:02d}"


def monthly_id(client_id: str, period: str) -> str:
    return f"{client_id}#{period}"


# -------------------------
# Index setup (optional but recommended)
# -------------------------
def ensure_usage_indexes(db: Database) -> None:
    """
    Create indexes for usage collections. Safe to call on startup.
    """
    db.usage_monthly.create_index([("client_id", 1), ("period", 1)], unique=True)
    db.usage_events.create_index([("client_id", 1), ("created_at", -1)])
    db.usage_events.create_index([("period", 1), ("created_at", -1)])


# -------------------------
# Read quota state
# -------------------------
def get_quota_state(
    db: Database,
    client_id: str,
    limit_tokens: int,
    period: Optional[str] = None,
) -> QuotaState:
    """
    Returns current quota state for client and period.
    If no doc exists yet, used=0.
    """
    period = period or month_period()
    _id = monthly_id(client_id, period)

    doc = db.usage_monthly.find_one(
        {"_id": _id},
        {"tokens_total": 1, "monthly_limit_tokens": 1, "period": 1},
    )

    used = int(doc.get("tokens_total", 0)) if doc else 0
    limit = int(doc.get("monthly_limit_tokens", limit_tokens)) if doc else int(limit_tokens)
    remaining = max(0, limit - used)
    exceeded = used >= limit

    return QuotaState(
        period=period,
        used_tokens=used,
        limit_tokens=limit,
        remaining_tokens=remaining,
        exceeded=exceeded,
    )


def quota_precheck(
    db: Database,
    client_id: str,
    limit_tokens: int,
    period: Optional[str] = None,
) -> QuotaState:
    """
    Pre-check before running the LLM.
    Returns the state; caller can block if exceeded.
    """
    state = get_quota_state(db, client_id, limit_tokens, period=period)
    return state


# -------------------------
# Commit usage (atomic)
# -------------------------
def commit_usage(
    db: Database,
    *,
    client_id: str,
    plan: str,
    limit_tokens: int,
    tokens_in: int,
    tokens_out: int,
    route: str,
    engine: str,
    status: int,
    latency_ms: int,
    meta: Optional[Dict[str, Any]] = None,
    period: Optional[str] = None,
) -> Tuple[Dict[str, Any], QuotaState]:
    """
    Atomic monthly accumulation + optional per-request event log.

    Returns:
      (monthly_doc_after_update, quota_state_after_update)
    """
    now = utc_now()
    period = period or month_period(now)
    _id = monthly_id(client_id, period)

    ti = int(tokens_in)
    to = int(tokens_out)
    total = ti + to

    monthly_doc = db.usage_monthly.find_one_and_update(
        {"_id": _id},
        {
            "$setOnInsert": {
                "_id": _id,
                "client_id": client_id,
                "period": period,
                "plan": plan,
                "monthly_limit_tokens": int(limit_tokens),
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_total": 0,
                "requests": 0,
                "created_at": now,
            },
            "$inc": {
                "tokens_in": ti,
                "tokens_out": to,
                "tokens_total": total,
                "requests": 1,
            },
            "$set": {
                "last_request_at": now,
                "updated_at": now,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    # Per-request log (recommended)
    try:
        db.usage_events.insert_one(
            {
                "client_id": client_id,
                "period": period,
                "route": route,
                "engine": engine,
                "tokens_in": ti,
                "tokens_out": to,
                "tokens_total": total,
                "status": int(status),
                "latency_ms": int(latency_ms),
                "created_at": now,
                "meta": meta or {},
            }
        )
    except Exception:
        # Logging should never break the request path
        pass

    used = int(monthly_doc.get("tokens_total", 0))
    limit = int(monthly_doc.get("monthly_limit_tokens", limit_tokens))
    remaining = max(0, limit - used)
    exceeded = used >= limit

    return monthly_doc, QuotaState(
        period=period,
        used_tokens=used,
        limit_tokens=limit,
        remaining_tokens=remaining,
        exceeded=exceeded,
    )