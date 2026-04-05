from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import ForeignKey, UniqueConstraint

#Definng DB Schema:
class Base(DeclarativeBase):
    pass

class Bug(Base):
    __tablename__ = "bug"
    id : Mapped[int] = mapped_column(primary_key=True)
    bug_id : Mapped[int] = mapped_column(unique=True)
    application_name : Mapped[str]
    gui_graph : Mapped[str]
    screen_descriptions : Mapped[str | None]

    def __repr__(self) -> str:
        return f"Bug(id={self.id!r}, bug_id={self.bug_id}, name={self.application_name!r})"

# class Screen(Base):
#     __tablename__ = "screen"
#     id : Mapped[int] = mapped_column(primary_key=True)
#     bug : Mapped[int] = mapped_column(ForeignKey("bug.id"))
#     state_hash : Mapped[str]
#     full_state_line : Mapped[str]
#     image_uri : Mapped[str]
#     screen_description : Mapped[str]
#     __table_args__ = (
#         UniqueConstraint("state_hash", "image_uri"),
#     )

#     def __repr__(self) -> str:
#         return f"Screen(id={self.id!r}, bug={self.bug!r},\n full_state_line={self.full_state_line!r},\n image_uri={self.image_uri!r},\n screen_description={self.screen_description!r})"

# class Transition(Base):
#     __tablename__ = "transition"
#     id : Mapped[int] = mapped_column(primary_key=True)
#     bug : Mapped[int] = mapped_column(ForeignKey("bug.id"))
#     transition_hash : Mapped[str]
#     full_transition_line : Mapped[str]
#     image_uri : Mapped[str]
#     __table_args__ = (
#         UniqueConstraint("transition_hash", "image_uri"),
#     )

#     def __repr__(self) -> str:
#          return f"Transition(id={self.id!r}, bug={self.bug!r},\n full_transition_line={self.full_transition_line!r},\n image_uri={self.image_uri!r})"