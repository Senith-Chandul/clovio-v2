from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, MetaData, TypeDecorator, create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    settings.DATABASE_URL,
    # FastAPI runs plain-def routes in a thread pool; SQLite refuses cross-thread use by default.
    connect_args={"check_same_thread": False} if is_sqlite else {},
    # Supabase already pools connections server-side; NullPool releases each connection immediately
    # after the request finishes so bursts of concurrent users never exhaust MaxClientsInSessionMode.
    **({} if is_sqlite else {"poolclass": NullPool}),
)

if is_sqlite:
    # SQLite ignores foreign keys (and so ON DELETE) unless asked per connection.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class UTCDateTime(TypeDecorator):
    """A time with its zone. SQLite drops the zone on the way back, and everything stored is UTC, so put it back:
    otherwise the API sends zone-less times that browsers read as local time."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class Base(DeclarativeBase):
    # Stable constraint names, so later migrations can find and change them.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })
    # Times are always stored with their time zone; lists and dicts as JSON (portable to SQLite for tests).
    type_annotation_map = {datetime: UTCDateTime, list[str]: JSON, dict: JSON}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
