from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Awaitable, Callable

from fastapi import Request, Response
from sqlalchemy import event
from sqlalchemy.engine import Engine


logger = logging.getLogger("haroona.performance")


@dataclass
class QueryStats:
    count: int = 0
    duration_ms: float = 0.0


_request_query_stats: ContextVar[QueryStats | None] = ContextVar(
    "haroona_request_query_stats",
    default=None,
)
_query_start_stack: ContextVar[list[float] | None] = ContextVar(
    "haroona_query_start_stack",
    default=None,
)
_query_events_installed = False


def _before_cursor_execute(*_args) -> None:
    stats = _request_query_stats.get()
    stack = _query_start_stack.get()
    if stats is None or stack is None:
        return
    stats.count += 1
    stack.append(perf_counter())


def _finish_query() -> None:
    stats = _request_query_stats.get()
    stack = _query_start_stack.get()
    if stats is None or not stack:
        return
    stats.duration_ms += (perf_counter() - stack.pop()) * 1000


def _after_cursor_execute(*_args) -> None:
    _finish_query()


def _handle_query_error(_exception_context) -> None:
    _finish_query()


def install_query_metrics() -> None:
    global _query_events_installed
    if _query_events_installed:
        return

    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(Engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(Engine, "handle_error", _handle_query_error)
    _query_events_installed = True


def _slow_request_threshold_ms() -> float:
    try:
        return max(0.0, float(os.getenv("PERF_SLOW_REQUEST_MS", "750")))
    except ValueError:
        return 750.0


async def measure_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    started = perf_counter()
    query_stats = QueryStats()
    stats_token = _request_query_stats.set(query_stats)
    stack_token = _query_start_stack.set([])

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started) * 1000
        logger.exception(
            "request_failed method=%s path=%s duration_ms=%.1f queries=%d db_ms=%.1f",
            request.method,
            request.url.path,
            duration_ms,
            query_stats.count,
            query_stats.duration_ms,
        )
        raise
    finally:
        _query_start_stack.reset(stack_token)
        _request_query_stats.reset(stats_token)

    duration_ms = (perf_counter() - started) * 1000
    timing = (
        f'app;dur={duration_ms:.1f}, '
        f'db;dur={query_stats.duration_ms:.1f};desc="{query_stats.count} queries"'
    )
    existing_timing = response.headers.get("Server-Timing")
    response.headers["Server-Timing"] = (
        f"{existing_timing}, {timing}" if existing_timing else timing
    )

    log_all = os.getenv("PERF_LOG_REQUESTS", "false").lower() == "true"
    if log_all or duration_ms >= _slow_request_threshold_ms():
        log = logger.info if log_all else logger.warning
        log(
            "request method=%s path=%s status=%d duration_ms=%.1f queries=%d "
            "db_ms=%.1f response_bytes=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            query_stats.count,
            query_stats.duration_ms,
            response.headers.get("content-length", "unknown"),
        )

    return response
