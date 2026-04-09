"""Utilities for loading selected graph data into the local SQLite database."""

from db import SessionLocal
from models import Bug
from graph_data_parser import get_graph_file_path, filter_graph
from generate_screen_descriptions import generate_screen_descriptions
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
from pathlib import Path

SELECTED_DATA = {
    2: "Family_Finance",
    10: "Material_Files",
    110: "Vinyl_Music_Player",
    117: "Open_Food_Facts_Food_Scanner",
    130: "andOTP_OTP_Authenticator",
    135: "Wikimedia_Commons",
    248: "ODK_Collect",
    1299: "Field_Book",
    1563: "lrkFM_File_Manager",
    1568: "lrkFM_File_Manager",
}

#use SessionLocal session factory to make a new session
db_session = SessionLocal()

def load_data():
    """Load the selected bug graphs into the database.

    For each bug listed in ``SELECTED_DATA``, this script:

    1. locates the raw ``graph.txt`` file on disk
    2. filters the graph content used at runtime
    3. generates screen descriptions from the unfiltered graph
    4. inserts the resulting graph payloads into the ``Bug`` table

    The script currently expects a locally available graph-data directory and is
    intended as a manual data-loading utility rather than a portable CLI.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    screen_description_model = ChatOpenAI(model="gpt-5.4")
    mode = "dev" #change to test to load test set data 

    if mode == "dev":
        #TODO: change this to a in repository directory holding AstroBR and EULER graphs
        DATA_DIR = "/Users/sambennett/desktop/BURT++/bug_reporting_with_llm/graph_data/graphs_json_data_AstroBR"
    elif mode == "test":
        #TODO: wire up test set
        DATA_DIR = ""
    else:
        raise(ValueError("Please set mode to either 'dev' or 'test"))


    print("Walking Bug Reports")
    if not os.path.isdir(DATA_DIR):
        raise FileNotFoundError(f"DATA_DIR does not exist or is not a directory: {DATA_DIR}")

    for bug_num, app_name in SELECTED_DATA.items():
        try:
            graph_file_path = get_graph_file_path(DATA_DIR, bug_num)
        except FileNotFoundError as exc:
            print(f"Skipping Bug{bug_num}: {exc}")
            continue

        with open(graph_file_path, "r", encoding="utf-8") as f:
            unfiltered_graph_text = f.read()
            filtered_graph_text = filter_graph(unfiltered_graph_text=unfiltered_graph_text)

        #generate screen descriptions for graph
        screen_descriptions = generate_screen_descriptions(unfiltered_graph_text, screen_description_model)
        print(f"generated bug descriptions for bug {bug_num}")

        app_row = Bug(bug_id=bug_num, application_name=app_name, gui_graph=filtered_graph_text, screen_descriptions=screen_descriptions)
        db_session.add(app_row)
        db_session.commit()
        print(f"Inserted Bug: {bug_num} (graph chars: {len(filtered_graph_text)} screen_desc chars: {len(screen_descriptions)})")

if __name__ == "__main__":
    load_data()
