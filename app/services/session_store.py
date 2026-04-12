import os
from pathlib import Path
import redis
from dotenv import load_dotenv
import json

# Load the repo-root .env so local FastAPI runs can resolve REDIS_URL.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

REDIS_URL = os.getenv("REDIS_URL")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def create_session(redis_client, session_record: dict) -> None:
    key = f"burt:session:{session_record['session_id']}"
    redis_client.set(key,json.dumps(session_record))
