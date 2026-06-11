from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
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
    BattlePoolItem,
    CandidateStock,
    DailyState,
    Indicator,
    KLine,
    MarketState,
    Position,
    ReviewStat,
    RiskConfig,
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
from app.presentation import (
    describe_market_state,
    describe_market_reason,
    describe_script,
    format_datetime,
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
templates.env.filters["css_class"] = css_class_for
templates.env.filters["json_list"] = json_list

app = FastAPI(title="HeadacheTradeV2", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class RiskConfigUpdate(BaseModel):
    account_equity: float
    risk_per_trade_pct: float
    neutral_risk_multiplier: float
    script_b_risk_multiplier: float
    max_positions: int
    max_symbol_position_pct: float
    max_industry_exposure_pct: float
    cooldown_days: int


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
def candidates_page(request: Request, pool: str = "", session: Session = Depends(get_session)):
    query = select(CandidateStock).where(CandidateStock.active.is_(True))
    if pool:
        query = query.where(CandidateStock.pool_types_json.contains(f'"{pool}"'))
    items = list(session.scalars(query.order_by(CandidateStock.rank_score.desc(), CandidateStock.symbol)))
    return templates.TemplateResponse(
        request,
        "candidates.html",
        {
            "items": items,
            "selected_pool": pool,
            "pool_counts": _candidate_pool_counts(session),
        },
    )


@app.get("/structures", response_class=HTMLResponse)
def structures_page(request: Request, scope: str = "active", session: Session = Depends(get_session)):
    scope = scope if scope in {"active", "history"} else "active"
    query = (
        select(StructureEvent)
        .where(StructureEvent.timeframe == STRUCTURE_TIMEFRAME)
        .order_by(StructureEvent.event_ts.desc())
        .limit(300)
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
            .limit(300)
        )
    events = list(
        session.scalars(query)
    )
    daily_states = _latest_daily_states(session)
    return templates.TemplateResponse(
        request,
        "structures.html",
        {"events": events, "daily_states": daily_states, "selected_scope": scope},
    )


@app.get("/battle-pool", response_class=HTMLResponse)
def battle_pool_page(request: Request, session: Session = Depends(get_session)):
    items = list(
        session.scalars(
            select(BattlePoolItem)
            .where(BattlePoolItem.status == "ACTIVE")
            .order_by(BattlePoolItem.score.desc(), BattlePoolItem.symbol)
        )
    )
    return templates.TemplateResponse(request, "battle_pool.html", {"items": items})


@app.get("/trade-plans", response_class=HTMLResponse)
def trade_plans_page(request: Request, session: Session = Depends(get_session)):
    plans = list(
        session.scalars(
            select(TradePlan)
            .where(TradePlan.status == "ACTIVE")
            .order_by(TradePlan.priority_level, TradePlan.updated_at.desc())
        )
    )
    return templates.TemplateResponse(request, "trade_plans.html", {"plans": plans})


@app.get("/market", response_class=HTMLResponse)
def market_page(request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    market = session.scalar(select(MarketState).order_by(MarketState.updated_at.desc()).limit(1))
    return templates.TemplateResponse(
        request,
        "market_dashboard.html",
        {"market": market, "market_checks": market_diagnostics(session, settings.market_symbols)},
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
    return templates.TemplateResponse(request, "risk.html", {"config": get_or_create_risk_config(session)})


@app.get("/opend", response_class=HTMLResponse)
def opend_page(request: Request):
    status_result = opend_admin.status()
    return templates.TemplateResponse(
        request,
        "opend.html",
        {"status": _opend_payload(status_result), "message": status_result.message},
    )


@app.post("/api/risk")
def update_risk_config(payload: RiskConfigUpdate, session: Session = Depends(get_session)):
    config = get_or_create_risk_config(session)
    for field, value in payload.model_dump().items():
        setattr(config, field, value)
    session.commit()
    return {"status": "ok"}


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
    payload["socket_health"] = opend_admin.opend_socket_health()
    return payload


def _dashboard_context(session: Session) -> dict[str, object]:
    settings = get_settings()
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
            .where(TradePlan.status == "ACTIVE")
            .order_by(TradePlan.priority_level, TradePlan.updated_at.desc())
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
        "plan_count": session.query(TradePlan).filter(TradePlan.status == "ACTIVE").count(),
        "open_positions": len(positions),
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
    }


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
