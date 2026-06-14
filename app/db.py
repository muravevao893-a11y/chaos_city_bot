from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def _engine_kwargs() -> dict:
    if settings.is_sqlite:
        return {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }
    if settings.is_postgres:
        return {
            "pool_pre_ping": True,
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_recycle": settings.db_pool_recycle_seconds,
            "connect_args": {"connect_timeout": 10},
        }
    return {"pool_pre_ping": True}


engine = create_engine(settings.database_url, future=True, **_engine_kwargs())


if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def _quote_ident(name: str) -> str:
    # All project table/column names are controlled constants. Keep quoting simple
    # and safe for PostgreSQL reserved words / mixed hosting configs.
    return '"' + name.replace('"', '""') + '"'


def _timestamp_ddl(nullable: bool = True) -> str:
    base = "TIMESTAMP WITH TIME ZONE" if settings.is_postgres else "TIMESTAMP"
    return base if nullable else f"{base} NOT NULL"


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    """Small additive migration helper for MVP installs.

    This is intentionally tiny: enough for current early versions without forcing
    Alembic onto the project yet. It works with both SQLite and PostgreSQL.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if table_name not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {_quote_ident(table_name)} ADD COLUMN {ddl}"))


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
    _add_column_if_missing("cities", "season_started_at", f"season_started_at {_timestamp_ddl()}")
    _add_column_if_missing("cities", "last_bot_message_id", "last_bot_message_id BIGINT")
    _add_column_if_missing("players", "last_daily_at", f"last_daily_at {_timestamp_ddl()}")
    _add_column_if_missing("players", "daily_streak", "daily_streak INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("memberships", "special_title", "special_title VARCHAR(64)")
    _add_column_if_missing("memberships", "civic_title", "civic_title VARCHAR(64)")
    _add_column_if_missing("memberships", "jailed_until", f"jailed_until {_timestamp_ddl()}")
    _add_column_if_missing("memberships", "convictions", "convictions INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("memberships", "last_action_at", f"last_action_at {_timestamp_ddl()}")
    _create_index_if_missing("ix_wars_defender_status_created", "CREATE INDEX ix_wars_defender_status_created ON wars (defender_city_id, status, created_at)")
    _create_index_if_missing("ix_wars_attacker_defender_status", "CREATE INDEX ix_wars_attacker_defender_status ON wars (attacker_city_id, defender_city_id, status)")
    _create_index_if_missing("ix_players_daily", "CREATE INDEX ix_players_daily ON players (last_daily_at)")
    _create_index_if_missing("ix_cities_owner", "CREATE INDEX ix_cities_owner ON cities (owner_telegram_user_id)")
    _create_index_if_missing("ix_players_telegram", "CREATE INDEX ix_players_telegram ON players (telegram_user_id)")
    _create_index_if_missing("ix_action_logs_action_created", "CREATE INDEX ix_action_logs_action_created ON action_logs (action, created_at)")
    _create_index_if_missing("ix_duels_city_status_created", "CREATE INDEX ix_duels_city_status_created ON duels (city_id, status, created_at)")
    _create_index_if_missing("ix_duels_target_status", "CREATE INDEX ix_duels_target_status ON duels (target_player_id, status)")


def init_db() -> None:
    # Import models before create_all so SQLAlchemy sees all tables.
    import app.models  # noqa: F401

    try:
        Base.metadata.create_all(bind=engine)
        _run_light_migrations()
    except OperationalError as exc:
        db_hint = (
            "\n\nНе удалось подключиться к базе данных.\n"
            "Проверь DATABASE_URL в .env. Для локального PostgreSQL можно запустить:\n"
            "  docker compose up -d postgres\n"
            "и использовать:\n"
            "  DATABASE_URL=postgresql+psycopg://chatograd:chatograd_password@localhost:5432/chatograd\n"
        )
        raise RuntimeError(db_hint) from exc


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
