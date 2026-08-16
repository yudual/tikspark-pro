from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Account, Friend, Message, MessageType
from ..schemas import (
    AccountCookieUpdateRequest,
    AccountImportRequest,
    AccountResponse,
    AccountUpdateRequest,
    FriendResponse,
    FriendScheduleUpdateRequest,
    FriendStrategyUpdateRequest,
    FriendToggleRequest,
)
from ..services.credential_service import credential_service
from ..services.schedule_service import (
    compute_friend_next_run_at,
    get_local_now,
    normalize_schedule_window,
    sanitize_cooldown_minutes,
    sanitize_frequency_days,
    sanitize_retry_cooldown_minutes,
    sanitize_retry_limit,
    validate_schedule_window,
)
from ..text_utils import repair_mojibake


router = APIRouter(prefix="/accounts", tags=["accounts"])


def _serialize_account(account: Account) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        avatar_url=account.avatar_url,
        nickname=repair_mojibake(account.nickname),
        dy_id=repair_mojibake(account.dy_id),
        proxy_url=account.proxy_url,
        status=account.status,
        status_reason=repair_mojibake(account.status_reason),
        last_checked_at=account.last_checked_at,
        cookie_expires_at=account.cookie_expires_at,
        cookie_updated_at=account.cookie_updated_at,
        updated_at=account.updated_at,
        friend_count=len(account.friends),
        active_friend_count=sum(1 for friend in account.friends if friend.is_active),
    )


def _serialize_friend(friend: Friend) -> FriendResponse:
    return FriendResponse(
        id=friend.id,
        account_id=friend.account_id,
        friend_dy_id=repair_mojibake(friend.friend_dy_id),
        friend_nickname=repair_mojibake(friend.friend_nickname),
        friend_avatar=friend.friend_avatar,
        is_active=friend.is_active,
        schedule_window=friend.schedule_window,
        frequency_days=friend.frequency_days,
        cooldown_minutes=friend.cooldown_minutes,
        retry_limit=friend.retry_limit,
        retry_cooldown_minutes=friend.retry_cooldown_minutes,
        consecutive_failures=friend.consecutive_failures,
        next_run_at=friend.next_run_at,
        last_run_at=friend.last_run_at,
        last_synced_at=friend.last_synced_at,
        message_type=friend.message.message_type if friend.message else None,
        message_content=friend.message.message_content if friend.message else "",
    )


@router.get("", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)) -> list[AccountResponse]:
    accounts = (
        db.execute(
            select(Account).options(joinedload(Account.friends)).order_by(Account.updated_at.desc())
        )
        .scalars()
        .unique()
        .all()
    )
    return [_serialize_account(account) for account in accounts]


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def import_account(payload: AccountImportRequest, db: Session = Depends(get_db)) -> AccountResponse:
    try:
        account = credential_service.import_account(db, payload.cookie_text)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(account)
    return _serialize_account(account)


@router.put("/{account_id}/cookie", response_model=AccountResponse)
def update_account_cookie(
    account_id: int,
    payload: AccountCookieUpdateRequest,
    db: Session = Depends(get_db),
) -> AccountResponse:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    try:
        credential_service.update_account_cookie(db, account, payload.cookie_text)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(account)
    return _serialize_account(account)


@router.post("/{account_id}/refresh-friends", response_model=list[FriendResponse])
def refresh_account_friends(account_id: int, db: Session = Depends(get_db)) -> list[FriendResponse]:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    try:
        credential_service.refresh_friends(db, account)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(account)
    return list_account_friends(account_id, db)


@router.get("/{account_id}/friends", response_model=list[FriendResponse])
def list_account_friends(account_id: int, db: Session = Depends(get_db)) -> list[FriendResponse]:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    friends = (
        db.execute(
            select(Friend)
            .options(joinedload(Friend.message))
            .where(Friend.account_id == account_id)
            .order_by(Friend.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [_serialize_friend(friend) for friend in friends]


@router.patch("/friends/{friend_id}/toggle", response_model=FriendResponse)
def toggle_friend(friend_id: int, payload: FriendToggleRequest, db: Session = Depends(get_db)) -> FriendResponse:
    friend = (
        db.execute(select(Friend).options(joinedload(Friend.message)).where(Friend.id == friend_id))
        .scalars()
        .first()
    )
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found.")

    friend.is_active = payload.is_active
    friend.schedule_window = normalize_schedule_window(friend.schedule_window)

    if friend.message is None:
        friend.message = Message(
            friend_id=friend.id,
            message_type=MessageType.fixed,
            message_content="[火花]",
        )

    if payload.is_active:
        friend.next_run_at = compute_friend_next_run_at(
            schedule_window=friend.schedule_window,
            now=get_local_now(),
            frequency_days=friend.frequency_days,
            cooldown_minutes=friend.cooldown_minutes,
            last_run_at=friend.last_run_at,
        )
    else:
        friend.next_run_at = None
        friend.consecutive_failures = 0

    db.commit()
    db.refresh(friend)
    return _serialize_friend(friend)


@router.patch("/friends/{friend_id}/schedule", response_model=FriendResponse)
def update_friend_schedule(
    friend_id: int, payload: FriendScheduleUpdateRequest, db: Session = Depends(get_db)
) -> FriendResponse:
    friend = (
        db.execute(select(Friend).options(joinedload(Friend.message)).where(Friend.id == friend_id))
        .scalars()
        .first()
    )
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found.")

    try:
        friend.schedule_window = validate_schedule_window(payload.schedule_window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if friend.is_active:
        friend.next_run_at = compute_friend_next_run_at(
            schedule_window=friend.schedule_window,
            now=get_local_now(),
            frequency_days=friend.frequency_days,
            cooldown_minutes=friend.cooldown_minutes,
            last_run_at=friend.last_run_at,
        )
    else:
        friend.next_run_at = None

    db.commit()
    db.refresh(friend)
    return _serialize_friend(friend)


@router.patch("/friends/{friend_id}/strategy", response_model=FriendResponse)
def update_friend_strategy(
    friend_id: int, payload: FriendStrategyUpdateRequest, db: Session = Depends(get_db)
) -> FriendResponse:
    friend = (
        db.execute(select(Friend).options(joinedload(Friend.message)).where(Friend.id == friend_id))
        .scalars()
        .first()
    )
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found.")

    try:
        friend.schedule_window = validate_schedule_window(payload.schedule_window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    friend.frequency_days = sanitize_frequency_days(payload.frequency_days)
    friend.cooldown_minutes = sanitize_cooldown_minutes(payload.cooldown_minutes)
    friend.retry_limit = sanitize_retry_limit(payload.retry_limit)
    friend.retry_cooldown_minutes = sanitize_retry_cooldown_minutes(payload.retry_cooldown_minutes)

    if friend.is_active:
        friend.next_run_at = compute_friend_next_run_at(
            schedule_window=friend.schedule_window,
            now=get_local_now(),
            frequency_days=friend.frequency_days,
            cooldown_minutes=friend.cooldown_minutes,
            last_run_at=friend.last_run_at,
        )
    else:
        friend.next_run_at = None

    db.commit()
    db.refresh(friend)
    return _serialize_friend(friend)


@router.patch("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: int, payload: AccountUpdateRequest, db: Session = Depends(get_db)
) -> AccountResponse:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    if payload.nickname is not None:
        account.nickname = payload.nickname
    if payload.avatar_url is not None:
        account.avatar_url = payload.avatar_url.strip()
    if payload.proxy_url is not None:
        account.proxy_url = payload.proxy_url

    db.commit()
    db.refresh(account)
    return _serialize_account(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    db.delete(account)
    db.commit()
    return None
