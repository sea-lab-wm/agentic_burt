import json

import redis
import config

redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)

def create_session_record(session_record: dict) -> None:
    """Persist a serialized agent conversation session record in Redis under its session-specific key."""
    key = f"burt:session:{session_record['session_id']}"
    redis_client.set(key, json.dumps(session_record))

def get_session(session_id: str) -> dict | None:
    """Load and deserialize an agent conversation session record from Redis if it exists."""
    key = f"burt:session:{session_id}"
    session_record = redis_client.get(key)
    if session_record is None:
        return None
    return json.loads(session_record)

def ping() -> bool:
    """Return whether the Redis client can successfully respond to a ping."""
    return bool(redis_client.ping())
