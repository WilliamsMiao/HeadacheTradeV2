from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db import _migrate_sqlite_schema
from app.models import Position


def test_structure_event_columns_are_added_to_existing_sqlite_database():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE structure_events (
                    id INTEGER PRIMARY KEY,
                    symbol VARCHAR(32),
                    timeframe VARCHAR(16),
                    event_type VARCHAR(48),
                    event_ts DATETIME,
                    price FLOAT,
                    reason TEXT
                )
                """
            )
        )

    _migrate_sqlite_schema(engine)
    _migrate_sqlite_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("structure_events")}
    assert {
        "pivot_low",
        "pivot_high",
        "confirm_level",
        "invalidation_level",
        "trigger_level",
        "parent_event_id",
        "expires_at",
        "script_version",
    }.issubset(columns)


def test_trade_signal_audit_columns_are_added_to_existing_sqlite_database():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE trade_signals (
                    id INTEGER PRIMARY KEY,
                    symbol VARCHAR(32),
                    signal_type VARCHAR(48),
                    reason TEXT
                )
                """
            )
        )

    _migrate_sqlite_schema(engine)
    _migrate_sqlite_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("trade_signals")}
    assert {
        "risk_per_share",
        "allowed_loss",
        "position_value",
        "source_structure_id",
        "trigger_timeframe",
        "trigger_ts",
        "trigger_level",
        "expires_at",
        "cancel_reason",
        "script_version",
    }.issubset(columns)


def test_position_without_signal_is_compatible_with_legacy_not_null_column():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE positions (
                    id INTEGER PRIMARY KEY,
                    symbol VARCHAR(32) UNIQUE,
                    status VARCHAR(32),
                    entry_signal_id INTEGER NOT NULL,
                    entry_price FLOAT NOT NULL,
                    stop_price FLOAT NOT NULL,
                    trailing_stop FLOAT,
                    shares INTEGER NOT NULL,
                    risk_amount FLOAT NOT NULL,
                    current_r FLOAT DEFAULT 0,
                    exit_reason TEXT DEFAULT '',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
    _migrate_sqlite_schema(engine)

    with Session(engine) as session:
        position = Position(
            symbol="US.EMR",
            status="OPEN",
            entry_price=142.143,
            stop_price=139.3,
            shares=864,
            risk_amount=2456,
            source="FUTU_DETECTED",
            is_orphan=True,
        )
        session.add(position)
        session.commit()

        assert position.entry_signal_id == 0


def test_reconciliation_issues_table_is_created_for_existing_sqlite_database():
    engine = create_engine("sqlite:///:memory:")

    _migrate_sqlite_schema(engine)
    _migrate_sqlite_schema(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("reconciliation_issues")}
    indexes = {index["name"] for index in inspector.get_indexes("reconciliation_issues")}
    assert {
        "symbol",
        "issue_type",
        "severity",
        "status",
        "remote_order_id",
        "local_order_id",
        "position_id",
        "trade_plan_id",
        "reason",
        "payload_json",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
    }.issubset(columns)
    assert "ix_reconciliation_issues_symbol" in indexes
    assert "ix_reconciliation_issues_last_seen_at" in indexes
