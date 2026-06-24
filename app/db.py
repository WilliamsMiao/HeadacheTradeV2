from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings
from app.services.performance import install_sqlalchemy_performance_hooks


class Base(DeclarativeBase):
    pass


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False, "timeout": 30.0}
    return {}


def _install_sqlite_pragmas(target_engine) -> None:
    if not target_engine.url.get_backend_name().startswith("sqlite"):
        return
    if getattr(target_engine, "_headache_sqlite_pragmas_installed", False):
        return

    @event.listens_for(target_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA synchronous=NORMAL")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:
            # In-memory SQLite and some read-only connections cannot switch journal mode.
            pass
        cursor.close()

    setattr(target_engine, "_headache_sqlite_pragmas_installed", True)


settings = get_settings()
if settings.database_url.startswith("sqlite:///./"):
    db_path = Path(settings.database_url.replace("sqlite:///./", "./"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args=_connect_args(settings.database_url))
_install_sqlite_pragmas(engine)
install_sqlalchemy_performance_hooks(engine, settings)
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
                "direction": "VARCHAR(16) DEFAULT ''",
                "stage": "VARCHAR(24) DEFAULT ''",
                "quality_score": "FLOAT",
                "battle_eligible": "BOOLEAN DEFAULT 0",
                "suggested_action": "VARCHAR(64) DEFAULT ''",
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
        if "klines" in tables:
            existing = {column["name"] for column in inspector.get_columns("klines")}
            if "turnover" not in existing:
                connection.execute(text("ALTER TABLE klines ADD COLUMN turnover FLOAT DEFAULT 0"))
        if "indicators" in tables:
            existing = {column["name"] for column in inspector.get_columns("indicators")}
            additions = {
                "ma5": "FLOAT",
                "ma10": "FLOAT",
                "ema5": "FLOAT",
                "ema10": "FLOAT",
                "ema20": "FLOAT",
                "ema60": "FLOAT",
                "boll_mid": "FLOAT",
                "boll_upper": "FLOAT",
                "boll_lower": "FLOAT",
                "rsi6": "FLOAT",
                "rsi14": "FLOAT",
                "kdj_k": "FLOAT",
                "kdj_d": "FLOAT",
                "kdj_j": "FLOAT",
                "turnover": "FLOAT",
                "turnover_ma20": "FLOAT",
                "volume_ratio": "FLOAT",
                "change_pct": "FLOAT",
                "amplitude_pct": "FLOAT",
            }
            for column, sql_type in additions.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE indicators ADD COLUMN {column} {sql_type}"))
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
        _add_columns(
            connection,
            inspector,
            tables,
            "candidate_stocks",
            {
                "first_selected_at": "DATETIME",
                "last_selected_at": "DATETIME",
                "candidate_age_days": "INTEGER DEFAULT 0",
                "candidate_status": "VARCHAR(24) DEFAULT 'ACTIVE_TODAY'",
                "carry_reason": "TEXT DEFAULT ''",
                "dropped_reason": "TEXT DEFAULT ''",
                "risk_flags_json": "TEXT DEFAULT '[]'",
            },
        )
        _add_columns(
            connection,
            inspector,
            tables,
            "trade_plans",
            {
                "no_chase_above": "FLOAT",
                "no_chase_below": "FLOAT",
                "current_price": "FLOAT",
                "current_change_pct": "FLOAT",
                "last_validated_at": "DATETIME",
                "rules_approval_status": "VARCHAR(40) DEFAULT 'NOT_REVIEWED'",
                "rules_reject_reason": "TEXT DEFAULT ''",
                "capital_status": "VARCHAR(32) DEFAULT 'CAPITAL_UNKNOWN'",
                "capital_reason": "TEXT DEFAULT ''",
                "activation_status": "VARCHAR(32) DEFAULT 'PLANNED'",
                "waitlist_rank": "INTEGER",
                "simulated_order_id": "INTEGER",
                "missed_by_capital_at": "DATETIME",
                "missed_by_capital_price": "FLOAT",
                "suggested_shares": "INTEGER",
                "available_cash_snapshot": "FLOAT",
                "max_new_position_value": "FLOAT",
                "manual_checklist_json": "TEXT DEFAULT '[]'",
            },
        )
        _add_columns(
            connection,
            inspector,
            tables,
            "positions",
            {
                "source_trade_plan_id": "INTEGER",
                "entry_order_id": "INTEGER",
                "exit_order_id": "INTEGER",
                "target_1": "FLOAT",
                "target_2": "FLOAT",
                "max_r": "FLOAT DEFAULT 0",
                "min_r": "FLOAT DEFAULT 0",
                "partial_exit_done": "BOOLEAN DEFAULT 0",
                "trailing_stop_price": "FLOAT",
                "overnight_policy": "VARCHAR(24) DEFAULT 'INTRADAY_ONLY'",
                "source": "VARCHAR(32) DEFAULT 'LOCAL_STRATEGY'",
                "is_orphan": "BOOLEAN DEFAULT 0",
                "name": "VARCHAR(128) DEFAULT ''",
                "available_shares": "INTEGER DEFAULT 0",
                "current_price": "FLOAT",
                "market_value": "FLOAT DEFAULT 0",
                "unrealized_pnl": "FLOAT DEFAULT 0",
                "unrealized_pnl_pct": "FLOAT DEFAULT 0",
                "exit_price": "FLOAT",
                "realized_pnl": "FLOAT",
                "close_verified": "BOOLEAN DEFAULT 0",
                "close_source": "VARCHAR(32) DEFAULT ''",
                "take_profit_pct": "FLOAT",
                "stop_loss_pct": "FLOAT",
                "last_synced_at": "DATETIME",
                "last_risk_checked_at": "DATETIME",
                "last_error": "TEXT DEFAULT ''",
            },
        )
        _add_columns(
            connection,
            inspector,
            tables,
            "sim_orders",
            {
                "retry_count": "INTEGER DEFAULT 0",
            },
        )
        if "reconciliation_issues" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE reconciliation_issues (
                        id INTEGER PRIMARY KEY,
                        symbol VARCHAR(32) DEFAULT '',
                        issue_type VARCHAR(64),
                        severity VARCHAR(24) DEFAULT 'WARN',
                        status VARCHAR(24) DEFAULT 'OPEN',
                        remote_order_id VARCHAR(64) DEFAULT '',
                        local_order_id INTEGER,
                        position_id INTEGER,
                        trade_plan_id INTEGER,
                        reason TEXT DEFAULT '',
                        payload_json TEXT DEFAULT '{}',
                        first_seen_at DATETIME,
                        last_seen_at DATETIME,
                        resolved_at DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                    """
                )
            )
            tables.add("reconciliation_issues")
        if "reconciliation_issues" in tables:
            for column in (
                "symbol",
                "issue_type",
                "severity",
                "status",
                "remote_order_id",
                "local_order_id",
                "position_id",
                "trade_plan_id",
                "first_seen_at",
                "last_seen_at",
            ):
                connection.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_reconciliation_issues_{column} "
                        f"ON reconciliation_issues ({column})"
                    )
                )
        _ensure_performance_indexes(connection, tables)


def _ensure_performance_indexes(connection, tables: set[str]) -> None:
    indexes = {
        "trade_plans": {
            "ix_trade_plans_status_updated": "status, updated_at",
            "ix_trade_plans_symbol_updated": "symbol, updated_at",
            "ix_trade_plans_priority_updated": "priority_level, updated_at",
            "ix_trade_plans_last_validated": "last_validated_at",
            "ix_trade_plans_source_structure": "source_structure_id",
            "ix_trade_plans_battle_pool": "battle_pool_id",
        },
        "sim_orders": {
            "ix_sim_orders_plan_submitted": "trade_plan_id, submitted_at",
            "ix_sim_orders_symbol_status": "symbol, status",
            "ix_sim_orders_status_submitted": "status, submitted_at",
            "ix_sim_orders_futu_order": "futu_order_id",
        },
        "positions": {
            "ix_positions_status_updated": "status, updated_at",
            "ix_positions_plan_updated": "source_trade_plan_id, updated_at",
            "ix_positions_close_verified": "close_verified",
        },
        "audit_logs": {
            "ix_audit_logs_subject_created": "subject_type, subject_id, created_at",
            "ix_audit_logs_symbol_created": "symbol, created_at",
            "ix_audit_logs_action_created": "action, created_at",
        },
        "reconciliation_issues": {
            "ix_reconciliation_open_severity": "status, severity",
            "ix_reconciliation_symbol_status": "symbol, status",
            "ix_reconciliation_type_seen": "issue_type, last_seen_at",
        },
    }
    for table, table_indexes in indexes.items():
        if table not in tables:
            continue
        for name, columns in table_indexes.items():
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))


def _add_columns(connection, inspector, tables, table: str, additions: dict[str, str]) -> None:
    if table not in tables:
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    for column, sql_type in additions.items():
        if column not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
