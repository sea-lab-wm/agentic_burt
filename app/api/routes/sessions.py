from uuid import uuid4

from fastapi import APIRouter
from redis.exceptions import RedisError

from app.services.session_store import redis_client

sessions_router = APIRouter()


@sessions_router.get("/healthz")
def healthz() -> dict[str, str | bool]:
    try:
        redis_ok = redis_client.ping()
    except RedisError:
        redis_ok = False

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
    }


@sessions_router.post("/sessions")
def create_session() -> dict[str, str]:
    return {
        "session_id": str(uuid4()),
        "status": "created",
    }
