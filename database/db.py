from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL

#Creating engine
engine = create_engine(DATABASE_URL, echo=True)

engine = create_engine(DATABASE_URL, echo=True)

SessionLocal = sessionmaker(bind=engine)