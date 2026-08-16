from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Friend, RunLog
from ..schemas import PaginatedLogsResponse, RunLogResponse
from ..text_utils import repair_mojibake

router = APIRouter(prefix="/logs", tags=["logs"])


def _serialize_run_log(log: RunLog) -> RunLogResponse:
    return RunLogResponse(
        id=log.id,
        friend_id=log.friend_id,
        status=log.status,
        summary=repair_mojibake(log.summary),
        details=repair_mojibake(log.details),
        created_at=log.created_at,
    )


@router.get("", response_model=PaginatedLogsResponse)
def list_logs(
    page: int = 1,
    limit: int = 50,
    account_id: int | None = None,
    db: Session = Depends(get_db),
) -> PaginatedLogsResponse:
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    query = select(RunLog).join(RunLog.friend)

    if account_id:
        query = query.where(Friend.account_id == account_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    logs = (
        db.execute(
            query.order_by(RunLog.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return PaginatedLogsResponse(
        items=[_serialize_run_log(log) for log in logs],
        total=total,
    )
