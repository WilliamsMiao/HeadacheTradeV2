from sqlalchemy import create_engine, inspect, text

from app.db import _migrate_sqlite_schema


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
