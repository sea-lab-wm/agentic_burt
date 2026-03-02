from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import Bug, Screen, Transition

def fetch_app_graph_and_name(session: Session, bug_id: int) -> str | None:
    """
    Fetch the application execution graph from the SQLite database by bug_id
    """

    graph = select(Bug.gui_graph).where(Bug.bug_id == bug_id)
    name = select(Bug.application_name).where(Bug.bug_id == bug_id)
    
    #returns string gui_graph if exists and none otherwise
    return session.execute(graph).scalar_one_or_none(), session.execute(name).scalar_one_or_none()
