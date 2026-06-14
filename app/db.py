from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "pool_pre_ping": True}
    return {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


settings = get_settings()
engine = create_engine(settings.database_url, future=True, **_engine_kwargs(settings.database_url))


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    """Tiny safe migration helper for early MVP installs.

    The project intentionally avoids Alembic for now, but existing local SQLite/Postgres
    databases still need small additive schema updates when v0.4 adds fields.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if table_name not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _create_index_if_missing(index_name: str, ddl: str) -> None:
    inspector = inspect(engine)
    existing = set()
    for table_name in inspector.get_table_names():
        existing.update(index["name"] for index in inspector.get_indexes(table_name) if index.get("name"))
    if index_name in existing:
        return
    with engine.begin() as conn:
        conn.execute(text(ddl))


def _run_light_migrations() -> None:
    _add_column_if_missing("cities", "owner_telegram_user_id", "owner_telegram_user_id BIGINT")
    _add_column_if_missing("cities", "buildings_json", "buildings_json TEXT NOT NULL DEFAULT '{}'")
    _add_column_if_missing("cities", "trophies_json", "trophies_json TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing("cities", "shop_json", "shop_json TEXT NOT NULL DEFAULT '{}'")
    _add_column_if_missing("cities", "season_number", "season_number INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing("cities", "season_started_at", "season_started_at TIMESTAMP")
    _add_column_if_missing("cities", "last_bot_message_id", "last_bot_message_id BIGINT")
    _add_column_if_missing("players", "last_daily_at", "last_daily_at TIMESTAMP")
    _add_column_if_missing("players", "daily_streak", "daily_streak INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("memberships", "special_title", "special_title VARCHAR(64)")
    _add_column_if_missing("memberships", "civic_title", "civic_title VARCHAR(64)")
    _add_column_if_missing("memberships", "jailed_until", "jailed_until TIMESTAMP")
    _add_column_if_missing("memberships", "convictions", "convictions INTEGER NOT NULL DEFAULT 0")
    _create_index_if_missing("ix_wars_defender_status_created", "CREATE INDEX ix_wars_defender_status_created ON wars (defender_city_id, status, created_at)")
    _create_index_if_missing("ix_wars_attacker_defender_status", "CREATE INDEX ix_wars_attacker_defender_status ON wars (attacker_city_id, defender_city_id, status)")
    _create_index_if_missing("ix_players_daily", "CREATE INDEX ix_players_daily ON players (last_daily_at)")


def init_db() -> None:
    # Import models before create_all so SQLAlchemy sees all tables.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_light_migrations()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
