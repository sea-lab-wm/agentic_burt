from db import SessionLocal
from models import Bug, Transition, Screen
import os

#Change to whatever location your graph data is located at
DATA_DIR = "/Users/sambennett/desktop/BURT++/bug_reporting_with_llm/graph_data/graphs_json_data_AstroBR"

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
    print("Walking Bug Reports")
    if not os.path.isdir(DATA_DIR):
        raise FileNotFoundError(f"DATA_DIR does not exist or is not a directory: {DATA_DIR}")

    # Only process Bug{N} folders where N is in SELECTED_DATA
    for bug in os.scandir(DATA_DIR):
        if not bug.is_dir():
            continue
        name = bug.name
        if not name.startswith("Bug"):
            continue
        suffix = name[3:]
        if not suffix.isdigit():
            continue
        bug_num = int(suffix)
        if bug_num not in SELECTED_DATA:
            continue

        bug_dir = bug.path
        # Find the txt file containing "BUG-graph" inside the bug's subfolder
        target_file = None
        for root, _dirs, files in os.walk(bug_dir):
            for filename in files:
                if "graph" in filename and filename.lower().endswith(".txt"):
                    target_file = os.path.join(root, filename)
                    break
            if target_file:
                break

        if not target_file:
            print(f"No BUG-graph txt found for {name}")
            continue

        with open(target_file, "r", encoding="utf-8") as f:
            graph_text = f.read()

        app_name = SELECTED_DATA.get(bug_num, f"Bug{bug_num}")
        app_row = Bug(bug_id=bug_num, application_name=app_name, gui_graph=graph_text)
        db_session.add(app_row)
        db_session.commit()
        print(f"Inserted Bug: {bug_num} (graph chars: {len(graph_text)})")

if __name__ == "__main__":
    load_data()
