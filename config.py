import os
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "gpt-5.4"
PROMPT_VERSION = "bugscribe_mutli-candidate_transitions_and_screen_descriptions"
DESCRIPTION_CSV_PATH = "data/dev_set_info_element_gt_and_input_desc.csv"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
