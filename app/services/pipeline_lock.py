from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


LOCK_PATHS = (
    Path("/run/headachetrade/pipeline.lock"),
    Path("/tmp/headachetrade-pipeline.lock"),
)


class PipelineBusyError(RuntimeError):
    pass


@contextmanager
def pipeline_lock() -> Iterator[None]:
    lock_file = None
    for path in LOCK_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = path.open("a+")
            break
        except OSError:
            continue
    if lock_file is None:
        raise RuntimeError("无法创建任务互斥锁")

    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineBusyError("已有行情或扫描任务正在运行，本次任务已跳过") from exc
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
