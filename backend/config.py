import os
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "gpt-5.4"
PROMPT_VERSION = "bugscribe_mutli-candidate_transitions_and_screen_descriptions"
DATASET = "BURT" # "BugScribe_dev", "BugScribe_test", "BURT"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
# How many times a user may edit a report and have BURT++ regenerate from the edit.
# Three edits produce final reports 1-3 and draft reports 1-4.
MAX_REPORT_EDITS = int(os.getenv("MAX_REPORT_EDITS", "3"))
