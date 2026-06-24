from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import get_settings
from app.domain import STRUCTURE_TIMEFRAME
from app.db import get_session, init_db
from app.db import SessionLocal
from app.auth import (
    clear_cookie_kwargs,
    cookie_kwargs,
    create_session_cookie,
    password_is_configured,
    request_is_authenticated,
    setup_password,
    verify_password,
)
from app.models import (
    ApprovalRecord,
    AuditLog,
    BattlePoolItem,
    CandidateStock,
    DailyState,
    Indicator,
    KLine,
    MarketState,
    Position,
    ReviewStat,
    RiskConfig,
    SimOrder,
    StateTransitionLog,
    StockTrend,
    StructureEvent,
    TradeSignal,
    TradePlan,
    TradingState,
    WatchlistItem,
)
from app.services.approvals import approve_signal, reject_signal
from app.services.backtest import run_backtest
from app.services.pipeline import (
    run_60m,
    run_compute_indicators,
    run_daily,
    run_pipeline,
    run_scan_structures,
    run_screen_market,
    run_set_price_alerts,
    run_update_market_data,
)
from app.services.pipeline import symbol_data_status
from app.services.pipeline_lock import pipeline_lock
from app.services.market import market_diagnostics
from app.services import opend_admin
from app.services.risk import get_or_create_risk_config
from app.services.task_runner import get_active_task, get_task, start_task, task_payload
from app.services.workbench import (
    debug_payload,
    events_payload,
    frames_payload,
    signals_payload,
    state_payload,
    workbench_watchlist,
)
from app.services.command_center import command_center_payload
from app.services.plan_prices import refresh_trade_plan_prices
from app.services.portfolio_manager import futu_position_snapshot, portfolio_sync_status
from app.services.freshness import freshness_context
from app.services.performance import performance_middleware
from app.providers.futu_provider import FutuProvider
from app.services.view_models import (
    battle_view_models,
    candidate_view_models,
    journal_view_models,
    order_view_models,
    position_view_models,
    structure_view_models,
    trade_plan_groups,
)
from app.services.terminal_api import (
    kline_payload,
    journal_summary_payload,
    daily_stats_payload,
    first_valid_trade_payload,
    orders_payload,
    positions_payload,
    response_envelope,
    structures_payload,
    cached_terminal_summary,
    timeline_payload,
    trade_plan_overlay_payload,
    trade_plan_detail,
    trade_plan_list,
)
from app.presentation import (
    describe_market_state,
    describe_market_reason,
    describe_script,
    format_datetime,
    format_system_datetime,
    format_money,
    format_percent,
    format_price,
    format_reason,
    format_return,
    format_shares,
    label_for,
    json_list,
    css_class_for,
)

BASE_DIR = Path(__file__).resolve().parent
TERMINAL_DIST_DIR = BASE_DIR.parent / "frontend" / "dist"
STATIC_VERSION = str(
    max((BASE_DIR / "static" / "styles.css").stat().st_mtime_ns, (BASE_DIR / "static" / "app.js").stat().st_mtime_ns)
)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["static_version"] = STATIC_VERSION
templates.env.filters["label"] = label_for
templates.env.filters["market_desc"] = describe_market_state
templates.env.filters["market_reason_desc"] = describe_market_reason
templates.env.filters["script_desc"] = describe_script
templates.env.filters["reason"] = format_reason
templates.env.filters["money"] = format_money
templates.env.filters["percent"] = format_percent
templates.env.filters["shares"] = format_shares
templates.env.filters["price"] = format_price
templates.env.filters["return_pct"] = format_return
templates.env.filters["dt"] = format_datetime
templates.env.filters["system_dt"] = format_system_datetime
templates.env.filters["css_class"] = css_class_for
templates.env.filters["json_list"] = json_list

app = FastAPI(title="HeadacheTradeV2", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount(
    "/terminal/assets",
    StaticFiles(directory=str(TERMINAL_DIST_DIR / "assets"), check_dir=False),
    name="terminal-assets",
)


class RiskConfigUpdate(BaseModel):
    risk_per_trade_pct: float
    max_positions: int
    max_symbol_position_pct: float
    max_daily_new_trades: int
    max_daily_loss_pct: float
    max_consecutive_losses: int
    force_intraday_exit: bool
    enable_overnight_hold: bool
    no_new_entry_before_minutes_after_open: int
    no_new_entry_before_close_minutes: int
    reason: str = ""


class PasswordPayload(BaseModel):
    password: str


class LoginPayload(BaseModel):
    password: str


class OpenDConfigPayload(BaseModel):
    login_account: str
    login_password: str
    trd_unlock_password: str = ""


class OpenDCodePayload(BaseModel):
    kind: str
    code: str


PUBLIC_PATHS = {
    "/health",
    "/login",
    "/setup-password",
    "/api/auth/login",
    "/api/auth/setup-password",
}


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.middleware("http")
async def record_performance(request: Request, call_next):
    return await performance_middleware(request, call_next, get_settings())


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static/") or path in PUBLIC_PATHS:
        return await call_next(request)

    with SessionLocal() as session:
        configured = password_is_configured(session)
        authenticated = request_is_authenticated(request, session) if configured else False

    if not configured:
        if path.startswith("/api/") or path.startswith("/tasks/"):
            return JSONResponse({"detail": "请先设置访问密码"}, status_code=403)
        return RedirectResponse("/setup-password", status_code=303)
    if not authenticated:
        if path.startswith("/api/") or path.startswith("/tasks/"):
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/setup-password", response_class=HTMLResponse)
def setup_password_page(request: Request, session: Session = Depends(get_session)):
    if password_is_configured(session):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "setup_password.html", {"error": ""})


@app.post("/api/auth/setup-password")
def setup_password_api(payload: PasswordPayload, session: Session = Depends(get_session)):
    try:
        setup_password(session, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = JSONResponse({"status": "ok"})
    response.set_cookie(**cookie_kwargs(create_session_cookie(session)))
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, session: Session = Depends(get_session)):
    if not password_is_configured(session):
        return RedirectResponse("/setup-password", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/api/auth/login")
def login_api(payload: LoginPayload, session: Session = Depends(get_session)):
    if not verify_password(session, payload.password):
        raise HTTPException(status_code=401, detail="访问密码不正确")
    response = JSONResponse({"status": "ok"})
    response.set_cookie(**cookie_kwargs(create_session_cookie(session)))
    return response


@app.post("/api/auth/logout")
def logout_api():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(**clear_cookie_kwargs())
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "dashboard.html", _dashboard_context(session))


@app.get("/candidates", response_class=HTMLResponse)
def candidates_page(request: Request, pool: str = "", limit: int = 200, session: Session = Depends(get_session)):
    query = select(CandidateStock).where(CandidateStock.active.is_(True))
    if pool:
        query = query.where(CandidateStock.pool_types_json.contains(f'"{pool}"'))
    items = list(session.scalars(query.order_by(CandidateStock.rank_score.desc(), CandidateStock.symbol).limit(max(1, min(limit, 500)))))
    return templates.TemplateResponse(
        request,
        "candidates.html",
        {
            "items": candidate_view_models(session, items),
            "selected_pool": pool,
            "pool_counts": _candidate_pool_counts(session),
            "freshness": freshness_context(session, sections={"candidates"})["candidates"],
        },
    )


@app.get("/structures", response_class=HTMLResponse)
def structures_page(request: Request, scope: str = "active", limit: int = 100, session: Session = Depends(get_session)):
    scope = scope if scope in {"active", "history"} else "active"
    query = (
        select(StructureEvent)
        .where(StructureEvent.timeframe == STRUCTURE_TIMEFRAME)
        .order_by(StructureEvent.event_ts.desc())
        .limit(max(1, min(limit, 500)))
    )
    if scope == "active":
        query = (
            select(StructureEvent)
            .join(
                CandidateStock,
                (CandidateStock.symbol == StructureEvent.symbol) & CandidateStock.active.is_(True),
            )
            .where(StructureEvent.timeframe == STRUCTURE_TIMEFRAME)
            .order_by(StructureEvent.event_ts.desc())
            .limit(max(1, min(limit, 500)))
        )
    events = list(
        session.scalars(query)
    )
    daily_states = _latest_daily_states(session)
    return templates.TemplateResponse(
        request,
        "structures.html",
        {"events": structure_view_models(session, events), "daily_states": daily_states, "selected_scope": scope, "freshness": freshness_context(session, sections={"structures"})["structures"]},
    )


@app.get("/battle-pool", response_class=HTMLResponse)
def battle_pool_page(request: Request, limit: int = 100, session: Session = Depends(get_session)):
    items = list(
        session.scalars(
            select(BattlePoolItem)
            .where(BattlePoolItem.status == "ACTIVE")
            .order_by(BattlePoolItem.score.desc(), BattlePoolItem.symbol)
            .limit(max(1, min(limit, 500)))
        )
    )
    return templates.TemplateResponse(request, "battle_pool.html", {"items": battle_view_models(session, items), "freshness": freshness_context(session, sections={"battle"})["battle"]})


@app.get("/trade-plans", response_class=HTMLResponse)
def trade_plans_page(request: Request, status: str = "", limit: int = 100, session: Session = Depends(get_session)):
    bounded_limit = max(1, min(limit, 500))
    query = select(TradePlan).where(TradePlan.status != "EXPIRED")
    if status:
        query = query.where(TradePlan.status == status.upper())
    plans = list(
        session.scalars(
            query
            .order_by(_trade_plan_priority_order(), TradePlan.updated_at.desc())
            .limit(bounded_limit)
        )
    )
    return templates.TemplateResponse(
        request,
        "trade_plans.html",
        {"plans": plans, "groups": trade_plan_groups(session, plans, get_settings()), "freshness": freshness_context(session, sections={"plans"})["plans"]},
    )


@app.get("/api/terminal/summary")
def terminal_summary_api(session: Session = Depends(get_session)):
    summary = cached_terminal_summary(session, get_settings())
    return response_envelope(
        summary,
        source=summary["account_equity_source"],
        synced_at=summary["account_equity_synced_at"],
    )


@app.get("/api/trade-plans")
def trade_plans_api(
    status: str = "",
    symbol: str = "",
    priority: str = "",
    direction: str = "",
    active_only: bool = True,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    plans = trade_plan_list(
        session,
        get_settings(),
        status=status,
        symbol=symbol,
        priority=priority,
        direction=direction,
        active_only=active_only,
        limit=limit,
    )
    synced_at = max((plan["updated_at"] for plan in plans if plan["updated_at"]), default=None)
    return response_envelope(plans, source="HEADACHE_TRADE_DB", synced_at=synced_at)


@app.get("/api/trade-plans/prices")
def trade_plan_prices_api(session: Session = Depends(get_session)):
    provider = FutuProvider(get_settings())
    try:
        return refresh_trade_plan_prices(session, provider)
    except OperationalError as exc:
        session.rollback()
        if "database is locked" in str(exc).lower():
            return {
                "prices": {},
                "changes": {},
                "statuses": {},
                "updated_at": None,
                "warning": "数据库正在处理后台任务，本次实时价暂未写入，页面将保留最后一次有效价格。",
            }
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OpenD 实时行情暂不可用：{exc}") from exc
    finally:
        provider.close()


@app.get("/api/trade-plans/{plan_id}")
def trade_plan_detail_api(plan_id: int, session: Session = Depends(get_session)):
    plan = session.get(TradePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="交易计划不存在")
    detail = trade_plan_detail(session, plan, get_settings())
    return response_envelope(detail, source="HEADACHE_TRADE_DB", synced_at=plan.updated_at)


@app.get("/api/positions")
def positions_api(symbol: str = "", limit: int = 300, session: Session = Depends(get_session)):
    positions = positions_payload(session, symbol, limit)
    synced_at = max((position["updated_at"] for position in positions if position["updated_at"]), default=None)
    return response_envelope(positions, source="FUTU_SIM_ACCOUNT", synced_at=synced_at)


@app.get("/api/futu-positions")
def futu_positions_api(session: Session = Depends(get_session)):
    sync = portfolio_sync_status(session)
    return response_envelope(
        futu_position_snapshot(session),
        source="FUTU_SIM_ACCOUNT",
        synced_at=sync.get("updated_at"),
    )


@app.get("/api/sim-orders")
def sim_orders_api(symbol: str = "", limit: int = 300, session: Session = Depends(get_session)):
    orders = orders_payload(session, symbol, limit)
    synced_at = max((order["submitted_at"] for order in orders if order["submitted_at"]), default=None)
    return response_envelope(orders, source="FUTU_SIM_ACCOUNT", synced_at=synced_at)


@app.get("/api/timeline")
def timeline_api(symbol: str, limit: int = 100, session: Session = Depends(get_session)):
    try:
        events = timeline_payload(session, symbol, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    synced_at = max((event["time"] for event in events), default=None)
    return response_envelope(events, source="HEADACHE_TRADE_DB", synced_at=synced_at)


@app.get("/api/journal/summary")
def journal_summary_api(session: Session = Depends(get_session)):
    payload = journal_summary_payload(session)
    synced_at = payload["curve"][-1]["time"] if payload["curve"] else None
    return response_envelope(payload, source="HEADACHE_TRADE_DB", synced_at=synced_at)


@app.get("/api/stats/daily")
def daily_stats_api(session: Session = Depends(get_session)):
    payload = daily_stats_payload(session)
    synced_at = max(
        (item["updated_at"] for item in payload["missed_opportunities"] if item["updated_at"]),
        default=None,
    )
    return response_envelope(payload, source="HEADACHE_TRADE_DB", synced_at=synced_at)


@app.get("/api/stats/first-valid-trade")
def first_valid_trade_api(session: Session = Depends(get_session)):
    payload = first_valid_trade_payload(session)
    synced_at = payload[0]["created_at"] if payload else None
    return response_envelope(payload, source="HEADACHE_TRADE_DB", synced_at=synced_at)


@app.get("/api/kline")
def kline_api(
    symbol: str,
    timeframe: str = "60m",
    limit: int = 300,
    session: Session = Depends(get_session),
):
    try:
        payload = kline_payload(session, symbol, timeframe, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = response_envelope(
        payload["bars"],
        source="HEADACHE_TRADE_DB",
        synced_at=payload["latest_bar_at"],
    )
    response["context"] = {
        "symbol": payload["symbol"],
        "timeframe": payload["timeframe"],
        "anomaly_count": payload["anomaly_count"],
    }
    return response


@app.get("/api/trade-plan-overlays")
def trade_plan_overlays_api(
    symbol: str,
    plan_id: int | None = None,
    session: Session = Depends(get_session),
):
    payload = trade_plan_overlay_payload(session, symbol, plan_id)
    return response_envelope(payload, source="HEADACHE_TRADE_DB")


@app.get("/api/structures")
def structures_api(
    symbol: str,
    timeframe: str = "60m",
    limit: int = 100,
    session: Session = Depends(get_session),
):
    try:
        events = structures_payload(session, symbol, timeframe, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    synced_at = max((event["event_ts"] for event in events), default=None)
    return response_envelope(events, source="HEADACHE_TRADE_DB", synced_at=synced_at)


@app.get("/sim-orders", response_class=HTMLResponse)
def sim_orders_page(request: Request, session: Session = Depends(get_session)):
    orders = list(session.scalars(select(SimOrder).order_by(SimOrder.submitted_at.desc()).limit(300)))
    return templates.TemplateResponse(request, "sim_orders.html", {"orders": order_view_models(session, orders), "freshness": freshness_context(session, sections={"orders"})["orders"]})


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request, session: Session = Depends(get_session)):
    positions = list(session.scalars(select(Position).order_by(Position.updated_at.desc()).limit(300)))
    return templates.TemplateResponse(
        request,
        "positions.html",
        {
            "positions": position_view_models(session, positions),
            "portfolio_sync": portfolio_sync_status(session),
            "freshness": freshness_context(session, sections={"positions"})["positions"],
        },
    )


@app.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "journal.html", {"trades": journal_view_models(session), "freshness": freshness_context(session, sections={"journal"})["journal"]})


@app.get("/audit-logs", response_class=HTMLResponse)
def audit_logs_page(request: Request, session: Session = Depends(get_session)):
    logs = list(session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)))
    return templates.TemplateResponse(request, "audit_logs.html", {"logs": logs, "freshness": freshness_context(session, sections={"audit"})["audit"]})


@app.get("/market", response_class=HTMLResponse)
def market_page(request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    market = session.scalar(select(MarketState).order_by(MarketState.updated_at.desc()).limit(1))
    return templates.TemplateResponse(
        request,
        "market_dashboard.html",
        {"market": market, "market_checks": market_diagnostics(session, settings.market_symbols), "freshness": freshness_context(session, sections={"market"})["market"]},
    )


@app.get("/symbols/{symbol}", response_class=HTMLResponse)
def symbol_detail(symbol: str, request: Request, session: Session = Depends(get_session)):
    symbol = symbol.upper()
    item = session.scalar(select(CandidateStock).where(CandidateStock.symbol == symbol))
    if item is None:
        item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == symbol))
    if item is None:
        raise HTTPException(status_code=404, detail="symbol not found")
    klines = list(
        session.scalars(
            select(KLine).where(KLine.symbol == symbol, KLine.timeframe == "1d").order_by(KLine.ts.desc()).limit(80)
        )
    )
    indicators = list(
        session.scalars(
            select(Indicator).where(Indicator.symbol == symbol, Indicator.timeframe == "1d").order_by(Indicator.ts.desc()).limit(20)
        )
    )
    structures = list(
        session.scalars(select(StructureEvent).where(StructureEvent.symbol == symbol).order_by(StructureEvent.event_ts.desc()).limit(20))
    )
    logs = list(
        session.scalars(select(StateTransitionLog).where(StateTransitionLog.symbol == symbol).order_by(StateTransitionLog.created_at.desc()).limit(20))
    )
    state = session.scalar(select(TradingState).where(TradingState.symbol == symbol))
    daily_state = session.scalar(select(DailyState).where(DailyState.symbol == symbol).order_by(DailyState.as_of.desc()).limit(1))
    plan = session.scalar(
        select(TradePlan)
        .where(TradePlan.symbol == symbol, TradePlan.status == "ACTIVE")
        .order_by(TradePlan.updated_at.desc())
        .limit(1)
    )
    position = session.scalar(select(Position).where(Position.symbol == symbol, Position.status == "OPEN"))
    signals = list(session.scalars(select(TradeSignal).where(TradeSignal.symbol == symbol).order_by(TradeSignal.created_at.desc()).limit(20)))
    return templates.TemplateResponse(
        request,
        "symbol.html",
        {
            "item": item,
            "klines": klines,
            "indicators": indicators,
            "structures": structures,
            "logs": logs,
            "state": state,
            "daily_state": daily_state,
            "plan": plan,
            "position": position,
            "signals": signals,
        },
    )


@app.get("/workbench/{symbol}", response_class=HTMLResponse)
def workbench(symbol: str, request: Request, session: Session = Depends(get_session)):
    symbol = symbol.upper()
    item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == symbol))
    if item is None:
        raise HTTPException(status_code=404, detail="symbol not found")
    return templates.TemplateResponse(
        request,
        "workbench.html",
        {
            "title": f"{symbol} 多周期工作台",
            "item": item,
            "watchlist": workbench_watchlist(session),
        },
    )


@app.get("/workbench")
def workbench_default(session: Session = Depends(get_session)):
    symbol = session.scalar(
        select(WatchlistItem.symbol)
        .where(WatchlistItem.active.is_(True))
        .order_by(WatchlistItem.symbol)
        .limit(1)
    )
    if symbol is None:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"/workbench/{symbol}", status_code=303)


@app.get("/risk", response_class=HTMLResponse)
def risk_page(request: Request, session: Session = Depends(get_session)):
    from app.services.risk_control import risk_page_context

    config = get_or_create_risk_config(session)
    return templates.TemplateResponse(
        request,
        "risk.html",
        {"config": config, "risk": risk_page_context(session, get_settings(), config)},
    )


@app.get("/opend", response_class=HTMLResponse)
def opend_page(request: Request, session: Session = Depends(get_session)):
    status_result = opend_admin.status()
    return templates.TemplateResponse(
        request,
        "opend.html",
        {
            "status": _opend_payload(status_result),
            "message": status_result.message,
            "portfolio_sync": portfolio_sync_status(session),
            "freshness": freshness_context(session, sections={"portfolio"})["portfolio"],
        },
    )


@app.post("/api/risk")
def update_risk_config(payload: RiskConfigUpdate, session: Session = Depends(get_session)):
    from app.services.risk_control import update_risk_settings

    values = payload.model_dump()
    reason = values.pop("reason", "")
    try:
        effective = update_risk_settings(session, get_settings(), values, reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", "effective": effective}


@app.post("/api/signals/{signal_id}/approve")
def approve(signal_id: int, session: Session = Depends(get_session)):
    approve_signal(session, signal_id)
    return {"status": "approved"}


@app.post("/api/signals/{signal_id}/reject")
def reject(signal_id: int, session: Session = Depends(get_session)):
    reject_signal(session, signal_id)
    return {"status": "rejected"}


@app.get("/api/opend/status")
def api_opend_status():
    return _opend_payload(opend_admin.status())


@app.get("/api/opend/diagnostics")
def api_opend_diagnostics():
    return _opend_payload(opend_admin.diagnostics())


@app.post("/api/opend/install")
def api_opend_install():
    return _opend_payload(opend_admin.install())


@app.post("/api/opend/configure")
def api_opend_configure(payload: OpenDConfigPayload):
    return _opend_payload(opend_admin.configure(payload.login_account, payload.login_password, payload.trd_unlock_password))


@app.post("/api/opend/start")
def api_opend_start():
    return _opend_payload(opend_admin.start())


@app.post("/api/opend/stop")
def api_opend_stop():
    return _opend_payload(opend_admin.stop())


@app.post("/api/opend/restart")
def api_opend_restart():
    return _opend_payload(opend_admin.restart())


@app.post("/api/opend/verify-code")
def api_opend_verify_code(payload: OpenDCodePayload):
    if payload.kind not in {"phone", "captcha"}:
        raise HTTPException(status_code=400, detail="验证码类型无效")
    return _opend_payload(opend_admin.verify_code(payload.kind, payload.code))


@app.post("/tasks/{task_name}")
def run_task(task_name: str, mock: bool = False, session: Session = Depends(get_session)):
    settings = get_settings()
    if task_name in {"screen-market", "update-market-data", "run-daily", "run-60m", "set-price-alerts", "run-backtest"}:
        try:
            state = start_task(
                task_name,
                lambda progress: _run_background_task(task_name, settings, mock, progress),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(task_payload(state), status_code=202)
    if task_name == "compute-indicators":
        payload = {"computed": run_compute_indicators(session, settings)}
    elif task_name == "scan-structures":
        payload = run_scan_structures(session, settings)
    elif task_name == "run-pipeline":
        payload = run_pipeline(session, settings)
    else:
        raise HTTPException(status_code=404, detail="unknown task")
    return payload


@app.get("/api/tasks/active")
def active_task_status():
    state = get_active_task()
    return task_payload(state) if state else {"status": "IDLE"}


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str):
    state = get_task(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启")
    return task_payload(state)


def _run_background_task(task_name: str, settings, mock: bool, progress):
    with pipeline_lock():
        with SessionLocal() as session:
            if task_name == "screen-market":
                progress(0, 1, "正在通过 Futu 条件选股扫描美股市场")
                result = run_screen_market(session, settings, use_mock=mock)
                progress(1, 1, "候选池已生成")
                return result
            if task_name == "update-market-data":
                return run_update_market_data(session, settings, use_mock=mock, on_progress=progress)
            if task_name == "run-daily":
                return run_daily(session, settings, use_mock=mock, on_progress=progress)
            if task_name == "run-60m":
                return run_60m(session, settings, use_mock=mock, on_progress=progress)
            if task_name == "set-price-alerts":
                progress(0, 1, "正在同步 Futu 到价提醒")
                result = run_set_price_alerts(session, settings, use_mock=mock)
                progress(1, 1, "到价提醒已同步")
                return result
            if task_name == "run-backtest":
                progress(0, 1, "正在执行时间步进复盘")
                result = run_backtest(session, settings)
                progress(1, 1, "复盘数据已生成")
                return result
    raise ValueError("不支持的后台任务")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/terminal", response_class=HTMLResponse)
@app.get("/terminal/{path:path}", response_class=HTMLResponse)
def terminal_app(path: str = ""):
    index_file = TERMINAL_DIST_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=503, detail="Terminal 前端尚未构建")
    return FileResponse(index_file)


@app.get("/api/opend/health")
def opend_health() -> dict[str, object]:
    return opend_admin.opend_socket_health()


@app.get("/api/workbench/{symbol}/frames")
def api_workbench_frames(symbol: str, session: Session = Depends(get_session)):
    _ensure_workbench_symbol(session, symbol)
    return frames_payload(session, symbol)


@app.get("/api/workbench/{symbol}/state")
def api_workbench_state(symbol: str, session: Session = Depends(get_session)):
    return _workbench_call(state_payload, session, get_settings(), symbol)


@app.get("/api/workbench/{symbol}/events")
def api_workbench_events(symbol: str, session: Session = Depends(get_session)):
    return _workbench_call(events_payload, session, symbol)


@app.get("/api/workbench/{symbol}/signals")
def api_workbench_signals(symbol: str, session: Session = Depends(get_session)):
    return _workbench_call(signals_payload, session, symbol)


@app.get("/api/workbench/{symbol}/debug")
def api_workbench_debug(symbol: str, session: Session = Depends(get_session)):
    return _workbench_call(debug_payload, session, get_settings(), symbol)


def _ensure_workbench_symbol(session: Session, symbol: str) -> None:
    if session.scalar(select(WatchlistItem.id).where(WatchlistItem.symbol == symbol.upper())) is None:
        raise HTTPException(status_code=404, detail="symbol not found")


def _workbench_call(function, *args):
    try:
        return function(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _opend_payload(result: opend_admin.AdminResult) -> dict[str, object]:
    payload = {"ok": result.ok, "message": result.message, **result.data}
    if "api_port_open" in result.data:
        settings = get_settings()
        connected = bool(result.data["api_port_open"])
        payload["socket_health"] = {
            "status": "ok" if connected else "error",
            "host": settings.futu_host,
            "port": settings.futu_port,
            "connected": connected,
        }
    else:
        payload["socket_health"] = opend_admin.opend_socket_health()
    return payload


def _dashboard_context(session: Session) -> dict[str, object]:
    from app.services.risk_control import effective_risk_settings

    settings = effective_risk_settings(session, get_settings())
    market = session.scalar(select(MarketState).order_by(MarketState.updated_at.desc()).limit(1))
    market_checks = market_diagnostics(session, settings.market_symbols)
    candidates = list(
        session.scalars(
            select(CandidateStock)
            .where(CandidateStock.active.is_(True))
            .order_by(CandidateStock.rank_score.desc())
            .limit(12)
        )
    )
    battle_items = list(
        session.scalars(
            select(BattlePoolItem)
            .where(BattlePoolItem.status == "ACTIVE")
            .order_by(BattlePoolItem.score.desc())
            .limit(12)
        )
    )
    plans = list(
        session.scalars(
            select(TradePlan)
            .where(
                TradePlan.status.in_(
                    {"PLANNED", "ACTIVE", "ARMED", "WAIT_PULLBACK", "NO_CHASE", "TRIGGERED", "ORDER_SUBMITTED", "IN_POSITION", "WAITLIST", "MISSED_BY_CAPITAL"}
                )
            )
            .order_by(_trade_plan_priority_order(), TradePlan.updated_at.desc())
            .limit(6)
        )
    )
    signals = list(session.scalars(select(TradeSignal).where(TradeSignal.status == "PENDING").order_by(TradeSignal.created_at.desc()).limit(30)))
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN").order_by(Position.created_at.desc())))
    reviews = list(session.scalars(select(ReviewStat).order_by(ReviewStat.created_at.desc()).limit(20)))
    approvals = list(session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.created_at.desc()).limit(20)))
    summary = {
        "candidate_count": session.query(CandidateStock).filter(CandidateStock.active.is_(True)).count(),
        "battle_count": session.query(BattlePoolItem).filter(BattlePoolItem.status == "ACTIVE").count(),
        "plan_count": session.query(TradePlan).filter(
            TradePlan.status.in_(
                {"PLANNED", "ACTIVE", "ARMED", "WAIT_PULLBACK", "NO_CHASE", "TRIGGERED", "ORDER_SUBMITTED", "IN_POSITION", "WAITLIST", "MISSED_BY_CAPITAL"}
            )
        ).count(),
        "open_positions": len(positions),
        "waitlist_count": session.query(TradePlan).filter(TradePlan.status.in_({"WAITLIST", "MISSED_BY_CAPITAL"})).count(),
        "sim_mode": "SIM_TRADING" if settings.enable_sim_trading else "SIM_DISABLED",
        "real_trading": "DISABLED",
    }
    return {
        "market": market,
        "market_checks": market_checks,
        "candidates": candidates,
        "battle_items": battle_items,
        "plans": plans,
        "signals": signals,
        "positions": positions,
        "reviews": reviews,
        "approvals": approvals,
        "summary": summary,
        "command": command_center_payload(session, settings),
        "freshness": freshness_context(session),
    }


def _trade_plan_priority_order():
    return case(
        (TradePlan.priority_level == "S", 0),
        (TradePlan.priority_level == "A", 1),
        (TradePlan.priority_level == "B", 2),
        (TradePlan.priority_level == "C", 3),
        else_=4,
    )


def _candidate_pool_counts(session: Session) -> dict[str, int]:
    items = list(session.scalars(select(CandidateStock).where(CandidateStock.active.is_(True))))
    pools = ("LOW_REBOUND", "TREND_UP", "HIGH_RISK", "WEAK_DOWN")
    return {
        pool: sum(f'"{pool}"' in item.pool_types_json for item in items)
        for pool in pools
    }


def _latest_daily_states(session: Session) -> dict[str, DailyState]:
    records = list(session.scalars(select(DailyState).order_by(DailyState.symbol, DailyState.as_of.desc())))
    output: dict[str, DailyState] = {}
    for record in records:
        output.setdefault(record.symbol, record)
    return output
