from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Friend, Message, MessageType
from ..schemas import MessageBatchUpdateRequest, MessageResponse, MessageUpdateRequest
from ..text_utils import repair_mojibake


router = APIRouter(prefix="/messages", tags=["messages"])


def _validate_random_library(message_type: MessageType, message_content: str) -> None:
    if message_type != MessageType.random:
        return

    entries = [line.strip() for line in message_content.splitlines() if line.strip()]
    if len(entries) < 2:
        raise HTTPException(
            status_code=400,
            detail="随机话术库至少需要 2 条非空话术，请按行填写，每行一条。",
        )


def _serialize_message(friend: Friend) -> MessageResponse:
    assert friend.message is not None
    return MessageResponse(
        id=friend.message.id,
        friend_id=friend.id,
        account_id=friend.account_id,
        account_name=repair_mojibake(friend.account.nickname),
        friend_name=repair_mojibake(friend.friend_nickname),
        message_type=friend.message.message_type,
        message_content=friend.message.message_content,
        account_status=friend.account.status,
        schedule_window=friend.schedule_window,
        frequency_days=friend.frequency_days,
        cooldown_minutes=friend.cooldown_minutes,
        retry_limit=friend.retry_limit,
        retry_cooldown_minutes=friend.retry_cooldown_minutes,
        next_run_at=friend.next_run_at,
        last_run_at=friend.last_run_at,
        updated_at=friend.message.updated_at,
    )


@router.get("", response_model=list[MessageResponse])
def list_active_messages(db: Session = Depends(get_db)) -> list[MessageResponse]:
    friends = (
        db.execute(
            select(Friend)
            .options(joinedload(Friend.account), joinedload(Friend.message))
            .where(Friend.is_active.is_(True))
            .order_by(Friend.updated_at.desc())
        )
        .scalars()
        .all()
    )
    rows: list[MessageResponse] = []
    for friend in friends:
        if friend.message is None:
            continue
        rows.append(_serialize_message(friend))
    return rows


@router.put("/friend/{friend_id}", response_model=MessageResponse)
def update_friend_message(
    friend_id: int, payload: MessageUpdateRequest, db: Session = Depends(get_db)
) -> MessageResponse:
    friend = (
        db.execute(
            select(Friend)
            .options(joinedload(Friend.account), joinedload(Friend.message))
            .where(Friend.id == friend_id)
        )
        .scalars()
        .first()
    )
    if not friend:
        raise HTTPException(status_code=404, detail="好友不存在。")

    if friend.message is None:
        friend.message = Message(
            friend_id=friend.id,
            message_type=MessageType.fixed,
            message_content="",
        )

    _validate_random_library(payload.message_type, payload.message_content)
    friend.message.message_type = payload.message_type
    friend.message.message_content = payload.message_content
    db.commit()
    db.refresh(friend.message)
    return _serialize_message(friend)


@router.post("/batch-update")
def batch_update_messages(
    payload: MessageBatchUpdateRequest, db: Session = Depends(get_db)
) -> dict:
    _validate_random_library(payload.message_type, payload.message_content)
    query = select(Friend).options(joinedload(Friend.message)).where(Friend.is_active.is_(True))

    if payload.account_id is not None:
        query = query.where(Friend.account_id == payload.account_id)

    friends = db.execute(query).scalars().all()

    updated_count = 0
    for friend in friends:
        if friend.message is None:
            friend.message = Message(
                friend_id=friend.id,
                message_type=payload.message_type,
                message_content=payload.message_content,
            )
        else:
            friend.message.message_type = payload.message_type
            friend.message.message_content = payload.message_content
        updated_count += 1

    db.commit()
    return {"message": "批量更新成功。", "updated_count": updated_count}
