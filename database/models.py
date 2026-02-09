from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy import ForeignKey

#Definng DB Schema:
class Base(DeclarativeBase):
    pass

class Application(Base):
    __tablename__ = "application"
    id : Mapped[int] = mapped_column(primary_key=True)
    name : Mapped[str]

    def __repr__(self) -> str:
        return f"Application(id={self.id!r}, name={self.name!r})"

class Screen(Base):
    __tablename__ = "screen"
    id : Mapped[int] = mapped_column(primary_key=True)
    application = mapped_column(ForeignKey("application.id"))
    full_state_line = Mapped[str]
    image_uri = Mapped[str]
    screen_description = Mapped[str]

    def __repr__(self) -> str:
        return f"Screen(id={self.id!r}, application={self.application!r},\n full_state_line={self.full_state_line!r},\n image_uri={self.image_uri!r},\n screen_description={self.screen_description!r})"

class Transition(Base):
    __tablename__ = "transition"
    id : Mapped[int] = mapped_column(primary_key=True)
    application = mapped_column(ForeignKey("application.id"))
    full_transition_line = Mapped[str]
    image_uri = Mapped[str]

    def __repr__(self) -> str:
         return f"Transition(id={self.id!r}, application={self.application!r},\n full_transition_line={self.full_transition_line!r},\n image_uri={self.image_uri!r}"