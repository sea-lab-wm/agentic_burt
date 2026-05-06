import json
from uuid import uuid4

import redis
import config

redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)

#session lock life span capped at 3 minutes
SESSION_LOCK_TTL_SECONDS = 180

# Checks if the current value of the lock key is equal to the provided token
# If the two match, delete the lock key (effectively releasing the lock)
_RELEASE_SESSION_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def _session_key(session_id: str) -> str:
    """Build the Redis key used to persist session records."""
    return f"burt:session:{session_id}"

def _session_lock_key(session_id: str) -> str:
    """Build the Redis key used to coordinate per-session resume locks."""
    return f"burt:session-lock:{session_id}"

def create_session_record(session_record: dict) -> None:
    """Persist a serialized agent conversation session record in Redis under its session-specific key."""
    key = _session_key(session_record["session_id"])
    redis_client.set(key, json.dumps(session_record))

def get_session(session_id: str) -> dict | None:
    """Load and deserialize an agent conversation session record from Redis if it exists."""
    key = _session_key(session_id)
    session_record = redis_client.get(key)
    if session_record is None:
        return None
    return json.loads(session_record)

def acquire_session_lock(session_id: str) -> str | None:
    """Try to acquire the per-session resume lock.
    If per-session resume lock acquired successfully, return the unique randomly generated ownership token corresponding with it.
    Note: the ownership token is used to guarantee that the lock is only released (other than time out) by the same worker that acquired it.
    """
    key = _session_lock_key(session_id)
    token = uuid4().hex
    #store the generated ownership token as the value at the session lock key
    acquired = redis_client.set(key, token, nx=True, ex=SESSION_LOCK_TTL_SECONDS)
    if not acquired:
        return None
    return token

def release_session_lock(session_id: str, token: str) -> None:
    """Release the per-session resume lock only if the caller still owns it (ie. if the ownership token presented by the caller is the same as the token stored at the lock key)"""
    key = _session_lock_key(session_id)
    #execute _RELEASE_SESSION_LOCK_LUA lua script on redis server
    #1 = number of keys passed in KEYS
    #token = ARGV argument
    redis_client.eval(_RELEASE_SESSION_LOCK_LUA, 1, key, token)

def ping() -> bool:
    """Return whether the Redis client can successfully respond to a ping."""
    return bool(redis_client.ping())
