import json

import redis
import config

redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)

def create_session_record(session_record: dict) -> None:
    key = f"burt:session:{session_record['session_id']}"
    redis_client.set(key, json.dumps(session_record))

def get_session(session_id: str) -> dict | None:
    key = f"burt:session:{session_id}"
    session_record = redis_client.get(key)
    if session_record is None:
        return None
    return json.loads(session_record)

def ping() -> bool:
    return bool(redis_client.ping())
