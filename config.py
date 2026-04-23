import os
from dotenv import load_dotenv

load_dotenv()

#NOTE: config.py should probably not have any functions within
def _parse_cors_allowed_origins(raw_value: str | None) -> list[str]:
    """Parse a comma-separated CORS allowlist, falling back to the local Vite origin."""
    if raw_value is None:
        return ["http://localhost:5173"]

    origins = [origin.strip() for origin in raw_value.split(",") if origin.strip()]
    return origins or ["http://localhost:5173"]

MODEL_NAME = "gpt-5.4"
PROMPT_VERSION = "bugscribe_mutli-candidate_transitions_and_screen_descriptions"
DESCRIPTION_CSV_PATH = "data/dev_set_info_element_gt_and_input_desc.csv"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CORS_ALLOWED_ORIGINS = _parse_cors_allowed_origins(os.getenv("CORS_ALLOWED_ORIGINS"))
