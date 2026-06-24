import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.requests import Request

from app.config import Settings


logger = logging.getLogger("app.performance")


@dataclass
class RequestMetrics:
    sql_count: int = 0


_request_metrics: ContextVar[RequestMetrics | None] = ContextVar("request_metrics", default=None)


def current_request_metrics() -> RequestMetrics | None:
    return _request_metrics.get()


async def performance_middleware(request: Request, call_next, settings: Settings):
    if not settings.perf_log_enabled:
        return await call_next(request)

    metrics = RequestMetrics()
    token = _request_metrics.set(metrics)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _request_metrics.reset(token)
        path = request.url.path
        kind = "api" if path.startswith("/api/") else "html"
        query = str(request.url.query)
        logger.info(
            "[PERF] %s %s %s total=%sms sql_count=%s kind=%s%s",
            request.method,
            path,
            status_code,
            duration_ms,
            metrics.sql_count,
            kind,
            f" query={query}" if query else "",
        )
        if duration_ms >= settings.slow_request_ms:
            logger.warning(
                "[SLOW_REQUEST] %s %s total=%sms sql_count=%s",
                request.method,
                path,
                duration_ms,
                metrics.sql_count,
            )
        if metrics.sql_count > 50:
            logger.warning(
                "[N_PLUS_ONE_SUSPECT] %s %s sql_count=%s total=%sms",
                request.method,
                path,
                metrics.sql_count,
                duration_ms,
            )


def install_sqlalchemy_performance_hooks(engine: Engine, settings: Settings) -> None:
    if getattr(engine, "_headache_perf_hooks_installed", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        context._headache_perf_started_at = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        metrics = current_request_metrics()
        if metrics is not None:
            metrics.sql_count += 1
        if not settings.perf_log_enabled:
            return
        started = getattr(context, "_headache_perf_started_at", None)
        if started is None:
            return
        duration_ms = int((time.perf_counter() - started) * 1000)
        if duration_ms >= settings.slow_sql_ms:
            normalized = " ".join(str(statement).split())
            logger.warning("[SLOW_SQL] %sms %s", duration_ms, normalized[:500])

    setattr(engine, "_headache_perf_hooks_installed", True)
