from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import Bug

def fetch_graph_data(session: Session, bug_id: int) -> str | None:
    """
    Fetches the application execution information necesarry for reasoning on the current bug description from the SQLite database by bug_id
    """

    graph = select(Bug.gui_graph).where(Bug.bug_id == bug_id)
    name = select(Bug.application_name).where(Bug.bug_id == bug_id)
    screen_descriptions = select(Bug.screen_descriptions).where(Bug.bug_id == bug_id)
    
    #returns string gui_graph if exists and none otherwise
    return session.execute(graph).scalar_one_or_none(), session.execute(name).scalar_one_or_none(), session.execute(screen_descriptions).scalar_one_or_none()
