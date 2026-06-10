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
    TradingState,
    WatchlistItem,
)
from app.services.approvals import approve_signal, reject_signal
from app.services.backtest import run_backtest
from app.services.pipeline import run_compute_indicators, run_full_refresh, run_pipeline, run_sync_watchlist, run_update_market_data
from app.services.pipeline import symbol_data_status
from app.services.market import market_diagnostics
from app.services import opend_admin
from app.services.risk import get_or_create_risk_config
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


@app.get("/symbols/{symbol}", response_class=HTMLResponse)
def symbol_detail(symbol: str, request: Request, session: Session = Depends(get_session)):
    symbol = symbol.upper()
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
    trend = session.scalar(select(StockTrend).where(StockTrend.symbol == symbol).order_by(StockTrend.as_of.desc()).limit(1))
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
            "trend": trend,
            "position": position,
            "signals": signals,
        },
    )


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
    if task_name == "sync-watchlist":
        payload = {"synced": run_sync_watchlist(session, settings, use_mock=mock)}
    elif task_name == "update-market-data":
        payload = run_update_market_data(session, settings, use_mock=mock)
    elif task_name == "compute-indicators":
        payload = {"computed": run_compute_indicators(session, settings)}
    elif task_name == "run-pipeline":
        payload = run_pipeline(session, settings)
    elif task_name == "run-backtest":
        payload = run_backtest(session, settings)
    elif task_name == "mock-full-refresh":
        payload = run_full_refresh(session, settings, use_mock=True)
    else:
        raise HTTPException(status_code=404, detail="unknown task")
    return payload


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/opend/health")
def opend_health() -> dict[str, object]:
    return opend_admin.opend_socket_health()


def _opend_payload(result: opend_admin.AdminResult) -> dict[str, object]:
    payload = {"ok": result.ok, "message": result.message, **result.data}
    payload["socket_health"] = opend_admin.opend_socket_health()
    return payload


def _dashboard_context(session: Session) -> dict[str, object]:
    settings = get_settings()
    market = session.scalar(select(MarketState).order_by(MarketState.updated_at.desc()).limit(1))
    market_checks = market_diagnostics(session, settings.market_symbols)
    items = list(session.scalars(select(WatchlistItem).where(WatchlistItem.active.is_(True)).order_by(WatchlistItem.symbol)))
    rows = []
    for item in items:
        trend = session.scalar(select(StockTrend).where(StockTrend.symbol == item.symbol).order_by(StockTrend.as_of.desc()).limit(1))
        state = session.scalar(select(TradingState).where(TradingState.symbol == item.symbol))
        structure = session.scalar(select(StructureEvent).where(StructureEvent.symbol == item.symbol).order_by(StructureEvent.event_ts.desc()).limit(1))
        signal = session.scalar(select(TradeSignal).where(TradeSignal.symbol == item.symbol, TradeSignal.status == "PENDING").order_by(TradeSignal.created_at.desc()).limit(1))
        position = session.scalar(select(Position).where(Position.symbol == item.symbol, Position.status == "OPEN"))
        data_ok, data_reason = symbol_data_status(session, item.symbol)
        rows.append(
            {
                "item": item,
                "trend": trend,
                "state": state,
                "structure": structure,
                "signal": signal,
                "position": position,
                "data_ok": data_ok,
                "data_reason": data_reason,
            }
        )
    signals = list(session.scalars(select(TradeSignal).where(TradeSignal.status == "PENDING").order_by(TradeSignal.created_at.desc()).limit(30)))
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN").order_by(Position.created_at.desc())))
    reviews = list(session.scalars(select(ReviewStat).order_by(ReviewStat.created_at.desc()).limit(20)))
    approvals = list(session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.created_at.desc()).limit(20)))
    risk_rows = [
        row
        for row in rows
        if (row["state"] and row["state"].state in {"RISK_PROTECTION", "EXIT_CANDIDATE"})
        or (row["signal"] and row["signal"].signal_type in {"REDUCE", "EXIT"})
    ]
    summary = {
        "pending_signals": len(signals),
        "open_positions": len(positions),
        "risk_items": len(risk_rows),
        "watchlist": len(rows),
    }
    return {
        "market": market,
        "market_checks": market_checks,
        "rows": rows,
        "signals": signals,
        "positions": positions,
        "reviews": reviews,
        "approvals": approvals,
        "summary": summary,
    }
