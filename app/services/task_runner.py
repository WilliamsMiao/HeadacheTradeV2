from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Callable
from uuid import uuid4


ProgressCallback = Callable[[int, int, str], None]
TaskFunction = Callable[[ProgressCallback], dict[str, Any]]


@dataclass
class TaskState:
    id: str
    name: str
    status: str = "PENDING"
    current: int = 0
    total: int = 0
    message: str = "等待执行"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="headachetrade-task")
_lock = Lock()
_tasks: dict[str, TaskState] = {}
_active_task_id: str | None = None


def start_task(name: str, function: TaskFunction) -> TaskState:
    global _active_task_id
    with _lock:
        active = _tasks.get(_active_task_id or "")
        if active and active.status in {"PENDING", "RUNNING"}:
            raise RuntimeError(f"任务“{active.name}”正在执行，请等待完成")
        state = TaskState(id=uuid4().hex, name=name)
        _tasks[state.id] = state
        _active_task_id = state.id
    _executor.submit(_run_task, state.id, function)
    return state


def get_task(task_id: str) -> TaskState | None:
    with _lock:
        return _copy(_tasks.get(task_id))


def get_active_task() -> TaskState | None:
    with _lock:
        return _copy(_tasks.get(_active_task_id or ""))


def task_payload(state: TaskState) -> dict[str, Any]:
    payload = asdict(state)
    payload["progress_pct"] = round((state.current / state.total) * 100, 1) if state.total else 0
    return payload


def _run_task(task_id: str, function: TaskFunction) -> None:
    _update(task_id, status="RUNNING", message="任务已开始")

    def progress(current: int, total: int, message: str) -> None:
        _update(task_id, current=current, total=total, message=message)

    try:
        result = function(progress)
        _update(task_id, status="SUCCEEDED", result=result, message="任务执行完成")
    except Exception as exc:
        _update(task_id, status="FAILED", error=str(exc), message="任务执行失败")


def _update(task_id: str, **values: Any) -> None:
    with _lock:
        state = _tasks[task_id]
        for key, value in values.items():
            setattr(state, key, value)
        state.updated_at = datetime.now(UTC).isoformat()


def _copy(state: TaskState | None) -> TaskState | None:
    return TaskState(**asdict(state)) if state else None
