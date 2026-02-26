# utils/seed_api_clients.py
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List

import bcrypt
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# -----------------------------
# Helpers
# -----------------------------
def generate_api_key(prefix: str = "qk_live", nbytes: int = 32) -> str:
    token = secrets.token_urlsafe(nbytes)
    return f"{prefix}_{token}"


def hash_api_key(api_key: str, rounds: int = 12) -> str:
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(api_key.encode("utf-8"), salt).decode("utf-8")


def last4(api_key: str) -> str:
    clean = api_key.replace("-", "").replace("_", "")
    return clean[-4:]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------
# Mongo
# -----------------------------
def get_collection() -> Collection:
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("DB_NAME", "clientRecommender")
    coll_name = os.getenv("API_CLIENTS_COLLECTION", "api_clients")

    if not mongo_uri:
        raise RuntimeError("Missing MONGO_URI in environment.")

    client = MongoClient(mongo_uri)
    return client[db_name][coll_name]


# -----------------------------
# Create new client doc
# -----------------------------
def make_client_doc(
    client_id: str,
    first_name: str,
    last_name: str,
    user_type: str,
    email: Optional[str],
    company: Optional[str],
    address: Optional[Dict[str, Any]],
    plan: str,
    rpm: int,
    rpd: int,
    api_key_plain: str,
) -> Dict[str, Any]:

    return {
        "_id": client_id,
        "status": "active",
        "profile": {
            "first_name": first_name,
            "last_name": last_name,
            "type": user_type,
            "company": company,
            "email": email,
            "address": address,
        },
        "auth": {
            "keys": [
                {
                    "key_id": "key_01",
                    "prefix": "qk_live",
                    "last4": last4(api_key_plain),
                    "hash": hash_api_key(api_key_plain),
                    "created_at": now_iso(),
                    "revoked_at": None,
                }
            ]
        },
        "usage": {
            "plan": plan,
            "rate_limit": {"rpm": rpm, "rpd": rpd},
            "counters": {
                "day": {
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "requests": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                }
            },
        },
        "metadata": {
            "seeded": True,
            "seeded_at": now_iso(),
        },
    }


# -----------------------------
# MAIN (Idempotente)
# -----------------------------
def main() -> None:
    coll = get_collection()

    clients_to_seed = [
        {
            "client_id": "cliente_01",
            "first_name": "Sebastian",
            "last_name": "Seguel",
            "user_type": "tech_lead",
            "email": "sebastian@takhion.com",
            "company": None,
            "address": {
                "line1": "Avenida Francisco Bilbao 123",
                "city": "Santiago",
                "region": "RM",
                "country": "CL",
            },
        },
        {
            "client_id": "cliente_02",
            "first_name": "Daniel",
            "last_name": "Montenegro",
            "user_type": "indie_dev",
            "email": "daniel2@takhion.com",
            "company": "Empresa Demo SpA",
            "address": None,
        },
    ]

    created_keys: List[Tuple[str, str]] = []

    try:
        for data in clients_to_seed:
            existing = coll.find_one({"_id": data["client_id"]}, {"_id": 1})

            if existing:
                print(f"Cliente {data['client_id']} ya existe → no se modifica.")
                continue

            # Crear solo si NO existe
            new_key = generate_api_key("qk_live")

            doc = make_client_doc(
                client_id=data["client_id"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                user_type=data["user_type"],
                email=data["email"],
                company=data["company"],
                address=data["address"],
                plan="community",
                rpm=60,
                rpd=5000,
                api_key_plain=new_key,
            )

            coll.insert_one(doc)
            created_keys.append((data["client_id"], new_key))
            print(f"Cliente {data['client_id']} creado.")

        print("\nSeed finalizado.")
        print(f"DB: {os.getenv('DB_NAME', 'clientRecommender')} | Collection: {coll.name}")

        if created_keys:
            print("\n🔐 API keys generadas (MOSTRAR SOLO UNA VEZ):")
            for cid, key in created_keys:
                print(f" - {cid}: {key}")
        else:
            print("\nNo se crearon nuevos clientes.")

    except PyMongoError as e:
        raise RuntimeError(f"Mongo error: {e}") from e


if __name__ == "__main__":
    main()