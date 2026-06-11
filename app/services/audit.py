import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit(
    session: Session,
    action: str,
    *,
    symbol: str = "",
    subject_type: str = "",
    subject_id: int | None = None,
    status: str = "INFO",
    reason: str = "",
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    record = AuditLog(
        action=action,
        symbol=symbol,
        subject_type=subject_type,
        subject_id=subject_id,
        status=status,
        reason=reason,
        payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
    )
    session.add(record)
    return record
