from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


settings = get_settings()
if settings.database_url.startswith("sqlite:///./"):
    db_path = Path(settings.database_url.replace("sqlite:///./", "./"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args=_connect_args(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_schema()


def _migrate_sqlite_schema(target_engine=engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return
    inspector = inspect(target_engine)
    tables = set(inspector.get_table_names())
    with target_engine.begin() as connection:
        if "structure_events" in tables:
            existing = {column["name"] for column in inspector.get_columns("structure_events")}
            additions = {
                "pivot_low": "FLOAT",
                "pivot_high": "FLOAT",
                "confirm_level": "FLOAT",
                "invalidation_level": "FLOAT",
                "trigger_level": "FLOAT",
                "parent_event_id": "INTEGER",
                "expires_at": "DATETIME",
                "script_version": "VARCHAR(64)",
            }
            for column, sql_type in additions.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE structure_events ADD COLUMN {column} {sql_type}"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_structure_events_parent_event_id "
                    "ON structure_events (parent_event_id)"
                )
            )
        if "trade_signals" in tables:
            existing = {column["name"] for column in inspector.get_columns("trade_signals")}
            additions = {
                "risk_per_share": "FLOAT",
                "allowed_loss": "FLOAT",
                "position_value": "FLOAT",
                "source_structure_id": "INTEGER",
                "trigger_timeframe": "VARCHAR(16)",
                "trigger_ts": "DATETIME",
                "trigger_level": "FLOAT",
                "expires_at": "DATETIME",
                "cancel_reason": "TEXT",
                "script_version": "VARCHAR(64)",
            }
            for column, sql_type in additions.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE trade_signals ADD COLUMN {column} {sql_type}"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_trade_signals_source_structure_id "
                    "ON trade_signals (source_structure_id)"
                )
            )


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
