from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

import os
import shutil

from ..models import Account, AccountStatus, Friend, Message, MessageType
from ..schemas import (
    AccountCheckResult,
    FriendBatchImportRequest,
    FriendCreateRequest,
    FriendUpdateRequest,
)
from ..time_utils import beijing_now, from_beijing_epoch
from .app_settings_service import get_default_schedule_window
from .execution_service import PLAYWRIGHT_STEALTH_SCRIPT
from .schedule_service import compute_friend_next_run_at, get_local_now, validate_schedule_window
from .secret_service import get_secret_service

DEFAULT_MESSAGE = "[火花]"

SYSTEM_BOT_KEYWORDS: set[str] = {
    "抖音火山版", "头条", "今日头条", "西瓜视频", "懂车帝", "抖音小助手",
    "系统通知", "服务通知", "创作者服务中心", "电商小助手", "随拍小助手",
    "抖音安全中心", "消息助手", "活动通知", "群聊", "陌生人消息", "服务号",
    "钱包小助手", "直播小助手", "抖音商城", "抖音小店", "抖音创作仔", "抖音搜索",
    "dou+", "dou+小助手"
}


def get_browser_executable_path() -> str | None:
    for path in ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]:
        if os.path.exists(path):
            return path
    return shutil.which("google-chrome-stable") or shutil.which("google-chrome") or shutil.which("chromium")


@dataclass
class ParsedCredential:
    dy_id: str
    uid: str


@dataclass
class UserCandidate:
    uid: str
    display_id: str
    nickname: str
    avatar_url: str
    remark: str
    source: str
    self_score: int = 0


@dataclass
class SyncResult:
    account_candidate: UserCandidate | None
    friends: list[UserCandidate]
    status: AccountStatus
    status_reason: str
    refreshed_cookies: str | None = None


class CredentialService:
    def parse_cookie_text(self, cookie_text: str) -> ParsedCredential:
        uid = ""
        dy_id = ""

        parsed_json = self._try_parse_cookie_json(cookie_text)
        if parsed_json is not None:
            cookie_map = {
                str(item.get("name", "")).strip(): str(item.get("value", "")).strip()
                for item in parsed_json
                if isinstance(item, dict)
            }
            uid = cookie_map.get("uid") or cookie_map.get("user_id") or ""
            dy_id = cookie_map.get("sec_uid") or uid
        else:
            cookie_map = {}
            clean_text = cookie_text.strip()
            if clean_text.lower().startswith("cookie:"):
                clean_text = clean_text[7:].strip()
            for part in clean_text.split(";"):
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                cookie_map[name.strip()] = value.strip()
            uid = cookie_map.get("uid") or cookie_map.get("user_id") or ""
            dy_id = cookie_map.get("sec_uid") or uid

        return ParsedCredential(dy_id=dy_id, uid=uid)

    def import_account(self, db: Session, cookie_text: str) -> Account:
        clean_cookie = self.normalize_cookie_storage(cookie_text)
        sync_result = self._extract_from_cookie(clean_cookie)
        parsed = self.parse_cookie_text(clean_cookie)
        account_candidate = sync_result.account_candidate
        friends = self._without_account_candidate(sync_result.friends, account_candidate)
        final_cookie_text = sync_result.refreshed_cookies or clean_cookie
        cookie_expires_at = self.extract_cookie_expires_at(final_cookie_text)
        now = beijing_now()

        final_display_id = (
            account_candidate.display_id
            if account_candidate and account_candidate.display_id
            else parsed.dy_id
        )
        if final_display_id and (len(final_display_id) > 30 or final_display_id.startswith("MS4w")):
            final_display_id = parsed.uid or "已托管账号"

        account = Account(
            nickname=(
                account_candidate.nickname
                if account_candidate and account_candidate.nickname
                else "抖音账号"
            ),
            dy_id=final_display_id,
            avatar_url=(
                account_candidate.avatar_url
                if account_candidate and account_candidate.avatar_url
                else ""
            ),
            cookie_text=get_secret_service().encrypt(final_cookie_text),
            status=sync_result.status,
            status_reason=sync_result.status_reason,
            last_checked_at=now,
            cookie_expires_at=cookie_expires_at,
            cookie_updated_at=now,
        )
        db.add(account)
        db.flush()
        self._sync_friends_to_db(db, account, friends)
        return account

    def update_account_cookie(self, db: Session, account: Account, cookie_text: str) -> list[Friend]:
        clean_cookie = self.normalize_cookie_storage(cookie_text)
        sync_result = self._extract_from_cookie(clean_cookie)
        parsed = self.parse_cookie_text(clean_cookie)
        friends = list(sync_result.friends)
        account_candidate = sync_result.account_candidate

        if account_candidate is None:
            account_candidate = self._find_self_candidate(account, friends, parsed)
        friends = self._without_account_candidate(friends, account_candidate)

        if account_candidate:
            account.nickname = account_candidate.nickname or account.nickname
            account.dy_id = account_candidate.display_id or account.dy_id
            account.avatar_url = account_candidate.avatar_url or account.avatar_url
        elif parsed.dy_id and not account.dy_id:
            account.dy_id = parsed.dy_id

        final_cookie_text = sync_result.refreshed_cookies or clean_cookie
        now = beijing_now()
        account.cookie_text = get_secret_service().encrypt(final_cookie_text)
        account.cookie_expires_at = self.extract_cookie_expires_at(final_cookie_text)
        account.cookie_updated_at = now
        account.status = sync_result.status
        account.status_reason = (
            f"已同步 {len(friends)} 位关注与互关好友。"
            if friends
            else sync_result.status_reason
        )
        account.last_checked_at = now
        return self._sync_friends_to_db(db, account, friends)

    def extract_cookie_expires_at(self, cookie_text: str) -> datetime | None:
        parsed_json = self._try_parse_cookie_json(cookie_text)
        if parsed_json is None:
            return None

        expires_values: list[datetime] = []
        session_cookie_names = {"sessionid", "sessionid_ss", "sid_guard", "uid_tt", "uid_tt_ss", "passport_csrf_token"}
        for item in parsed_json:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if name and name not in session_cookie_names:
                continue
            expires = item.get("expires")
            if not isinstance(expires, (int, float)) or expires <= 0:
                continue
            try:
                expires_values.append(from_beijing_epoch(float(expires)))
            except (OverflowError, OSError, ValueError):
                continue

        if expires_values:
            return min(expires_values)
        return None

    def refresh_friends(self, db: Session, account: Account) -> list[Friend]:
        cookie_text = get_secret_service().decrypt(account.cookie_text)
        sync_result = self._extract_from_cookie(cookie_text)
        parsed = self.parse_cookie_text(cookie_text)
        friends = list(sync_result.friends)
        account_candidate = sync_result.account_candidate

        if account_candidate is None:
            account_candidate = self._find_self_candidate(account, friends, parsed)
        friends = self._without_account_candidate(friends, account_candidate)

        if account_candidate:
            account.nickname = account_candidate.nickname or account.nickname
            account.dy_id = account_candidate.display_id or account.dy_id
            account.avatar_url = account_candidate.avatar_url or account.avatar_url
        elif parsed.dy_id and not account.dy_id:
            account.dy_id = parsed.dy_id

        if sync_result.refreshed_cookies:
            account.cookie_text = get_secret_service().encrypt(sync_result.refreshed_cookies)
            account.cookie_updated_at = beijing_now()
            account.cookie_expires_at = self.extract_cookie_expires_at(sync_result.refreshed_cookies)

        account.status = sync_result.status
        account.status_reason = (
            f"已同步 {len(friends)} 位关注与互关好友。"
            if friends
            else sync_result.status_reason
        )
        account.last_checked_at = beijing_now()
        return self._sync_friends_to_db(db, account, friends)

    def check_account_status(self, db: Session, account: Account) -> AccountCheckResult:
        """主动检测并保活单个账号的 Cookie。"""
        if not account.cookie_text:
            account.status = AccountStatus.invalid
            account.status_reason = "缺少 Cookie 凭证"
            db.commit()
            return AccountCheckResult(
                account_id=account.id,
                nickname=account.nickname,
                dy_id=account.dy_id,
                status=account.status,
                status_reason=account.status_reason,
                cookie_expires_at=account.cookie_expires_at,
                cookie_updated_at=account.cookie_updated_at,
                friends_count=len(account.friends),
            )

        cookie_text = get_secret_service().decrypt(account.cookie_text)
        sync_result = self._extract_from_cookie(cookie_text)
        account.status = sync_result.status
        account.status_reason = sync_result.status_reason
        account.last_checked_at = beijing_now()

        if sync_result.refreshed_cookies:
            account.cookie_text = get_secret_service().encrypt(sync_result.refreshed_cookies)
            account.cookie_updated_at = beijing_now()
            account.cookie_expires_at = self.extract_cookie_expires_at(sync_result.refreshed_cookies)

        if sync_result.account_candidate:
            account.nickname = sync_result.account_candidate.nickname or account.nickname
            account.avatar_url = sync_result.account_candidate.avatar_url or account.avatar_url
            if sync_result.account_candidate.display_id and not sync_result.account_candidate.display_id.startswith("MS4w"):
                account.dy_id = sync_result.account_candidate.display_id

        if sync_result.friends:
            self._sync_friends_to_db(db, account, sync_result.friends)

        db.commit()
        db.refresh(account)
        return AccountCheckResult(
            account_id=account.id,
            nickname=account.nickname,
            dy_id=account.dy_id,
            status=account.status,
            status_reason=account.status_reason,
            cookie_expires_at=account.cookie_expires_at,
            cookie_updated_at=account.cookie_updated_at,
            friends_count=len(account.friends),
        )

    def check_all_accounts(self, db: Session) -> list[AccountCheckResult]:
        """批量检测并保活所有托管账号。"""
        accounts = db.execute(select(Account).options(selectinload(Account.friends))).scalars().all()
        results: list[AccountCheckResult] = []
        for account in accounts:
            results.append(self.check_account_status(db, account))
        return results

    def add_custom_friend(
        self, db: Session, account: Account, payload: FriendCreateRequest
    ) -> Friend:
        """手动为账号添加好友。"""
        now = beijing_now()
        schedule_window = validate_schedule_window(payload.schedule_window)

        existing = (
            db.query(Friend)
            .filter(Friend.account_id == account.id, Friend.friend_dy_id == payload.friend_dy_id.strip())
            .first()
        )
        if existing:
            existing.friend_nickname = payload.friend_nickname.strip()
            if payload.friend_avatar:
                existing.friend_avatar = payload.friend_avatar.strip()
            existing.is_active = payload.is_active
            existing.schedule_window = schedule_window
            existing.frequency_days = payload.frequency_days
            existing.cooldown_minutes = payload.cooldown_minutes
            existing.retry_limit = payload.retry_limit
            existing.retry_cooldown_minutes = payload.retry_cooldown_minutes
            if payload.is_active:
                existing.next_run_at = compute_friend_next_run_at(
                    schedule_window=schedule_window,
                    now=get_local_now(),
                    frequency_days=payload.frequency_days,
                    cooldown_minutes=payload.cooldown_minutes,
                    last_run_at=existing.last_run_at,
                )
            else:
                existing.next_run_at = None

            if existing.message:
                existing.message.message_type = payload.message_type
                existing.message.message_content = payload.message_content
            else:
                existing.message = Message(
                    friend_id=existing.id,
                    message_type=payload.message_type,
                    message_content=payload.message_content,
                )
            db.commit()
            db.refresh(existing)
            return existing

        friend = Friend(
            account_id=account.id,
            friend_dy_id=payload.friend_dy_id.strip(),
            friend_nickname=payload.friend_nickname.strip(),
            friend_avatar=(payload.friend_avatar or "").strip(),
            is_active=payload.is_active,
            schedule_window=schedule_window,
            frequency_days=payload.frequency_days,
            cooldown_minutes=payload.cooldown_minutes,
            retry_limit=payload.retry_limit,
            retry_cooldown_minutes=payload.retry_cooldown_minutes,
            last_synced_at=now,
        )
        if payload.is_active:
            friend.next_run_at = compute_friend_next_run_at(
                schedule_window=schedule_window,
                now=get_local_now(),
                frequency_days=payload.frequency_days,
                cooldown_minutes=payload.cooldown_minutes,
            )
        db.add(friend)
        db.flush()

        msg = Message(
            friend_id=friend.id,
            message_type=payload.message_type,
            message_content=payload.message_content or DEFAULT_MESSAGE,
        )
        db.add(msg)
        db.commit()
        db.refresh(friend)
        return friend

    def batch_import_friends(
        self, db: Session, account: Account, payload: FriendBatchImportRequest
    ) -> int:
        """批量导入好友（支持多行粘贴昵称/抖音号/sec_uid）。"""
        lines = [line.strip() for line in payload.raw_text.splitlines() if line.strip()]
        if not lines:
            return 0

        schedule_window = validate_schedule_window(payload.schedule_window)
        now = beijing_now()
        imported_count = 0

        for line in lines:
            # 支持常见分隔符：空格、逗号、制表符
            tokens = re.split(r"[\s,\t|]+", line)
            tokens = [t.strip() for t in tokens if t.strip()]
            if not tokens:
                continue

            if len(tokens) >= 2:
                nickname = tokens[0]
                dy_id = tokens[1]
            else:
                raw = tokens[0]
                nickname = raw
                dy_id = raw

            existing = (
                db.query(Friend)
                .filter(Friend.account_id == account.id, Friend.friend_dy_id == dy_id)
                .first()
            )
            if existing:
                existing.friend_nickname = nickname
                existing.is_active = payload.is_active
                existing.schedule_window = schedule_window
                existing.frequency_days = payload.frequency_days
                existing.cooldown_minutes = payload.cooldown_minutes
                existing.retry_limit = payload.retry_limit
                existing.retry_cooldown_minutes = payload.retry_cooldown_minutes
                if payload.is_active:
                    existing.next_run_at = compute_friend_next_run_at(
                        schedule_window=schedule_window,
                        now=get_local_now(),
                        frequency_days=payload.frequency_days,
                        cooldown_minutes=payload.cooldown_minutes,
                        last_run_at=existing.last_run_at,
                    )
                if existing.message:
                    existing.message.message_type = payload.message_type
                    existing.message.message_content = payload.message_content
                else:
                    existing.message = Message(
                        friend_id=existing.id,
                        message_type=payload.message_type,
                        message_content=payload.message_content,
                    )
            else:
                friend = Friend(
                    account_id=account.id,
                    friend_dy_id=dy_id,
                    friend_nickname=nickname,
                    friend_avatar="",
                    is_active=payload.is_active,
                    schedule_window=schedule_window,
                    frequency_days=payload.frequency_days,
                    cooldown_minutes=payload.cooldown_minutes,
                    retry_limit=payload.retry_limit,
                    retry_cooldown_minutes=payload.retry_cooldown_minutes,
                    last_synced_at=now,
                )
                if payload.is_active:
                    friend.next_run_at = compute_friend_next_run_at(
                        schedule_window=schedule_window,
                        now=get_local_now(),
                        frequency_days=payload.frequency_days,
                        cooldown_minutes=payload.cooldown_minutes,
                    )
                db.add(friend)
                db.flush()
                db.add(
                    Message(
                        friend_id=friend.id,
                        message_type=payload.message_type,
                        message_content=payload.message_content or DEFAULT_MESSAGE,
                    )
                )
            imported_count += 1

        db.commit()
        db.refresh(account)
        return imported_count

    def update_friend(self, db: Session, friend: Friend, payload: FriendUpdateRequest) -> Friend:
        """修改指定好友的配置（昵称、抖音号、头像、计划策略与消息）。"""
        if payload.friend_nickname is not None:
            friend.friend_nickname = payload.friend_nickname.strip()
        if payload.friend_dy_id is not None:
            friend.friend_dy_id = payload.friend_dy_id.strip()
        if payload.friend_avatar is not None:
            friend.friend_avatar = payload.friend_avatar.strip()
        if payload.is_active is not None:
            friend.is_active = payload.is_active
        if payload.schedule_window is not None:
            friend.schedule_window = validate_schedule_window(payload.schedule_window)
        if payload.frequency_days is not None:
            friend.frequency_days = max(1, payload.frequency_days)
        if payload.cooldown_minutes is not None:
            friend.cooldown_minutes = max(0, payload.cooldown_minutes)
        if payload.retry_limit is not None:
            friend.retry_limit = max(0, payload.retry_limit)
        if payload.retry_cooldown_minutes is not None:
            friend.retry_cooldown_minutes = max(1, payload.retry_cooldown_minutes)

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

        if payload.message_type is not None or payload.message_content is not None:
            if friend.message is None:
                friend.message = Message(
                    friend_id=friend.id,
                    message_type=payload.message_type or MessageType.fixed,
                    message_content=payload.message_content or DEFAULT_MESSAGE,
                )
            else:
                if payload.message_type is not None:
                    friend.message.message_type = payload.message_type
                if payload.message_content is not None:
                    friend.message.message_content = payload.message_content

        db.commit()
        db.refresh(friend)
        return friend

    def delete_friend(self, db: Session, friend: Friend) -> None:
        """删除指定好友。"""
        db.delete(friend)
        db.commit()

    def batch_delete_friends(self, db: Session, friend_ids: list[int]) -> int:
        """批量删除好友。"""
        if not friend_ids:
            return 0
        friends = db.query(Friend).filter(Friend.id.in_(friend_ids)).all()
        count = len(friends)
        for friend in friends:
            db.delete(friend)
        db.commit()
        return count

    def normalize_cookie_storage(self, cookie_text: str) -> str:
        """规范化 Cookie 存储格式为统一结构。"""
        parsed = self._to_playwright_cookies(cookie_text)
        return json.dumps(parsed, ensure_ascii=False)

    def _extract_from_cookie(self, cookie_text: str) -> SyncResult:
        parsed = self.parse_cookie_text(cookie_text)
        cookies = self._to_playwright_cookies(cookie_text)
        candidates: dict[str, UserCandidate] = {}
        refreshed_cookies: str | None = None
        exe_path = get_browser_executable_path()

        with sync_playwright() as playwright:
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-infobars",
                    "--window-size=1440,960",
                    "--mute-audio",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad",
                    "--disable-renderer-backgrounding",
                ],
            }
            if exe_path:
                launch_kwargs["executable_path"] = exe_path

            browser = playwright.chromium.launch(**launch_kwargs)

            context = browser.new_context(
                viewport={"width": 1440, "height": 960},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            context.add_init_script(PLAYWRIGHT_STEALTH_SCRIPT)
            context.add_cookies(cookies)
            page = context.new_page()

            try:
                # 访问个人主页建立上下文
                page.goto("https://www.douyin.com/user/self", timeout=50000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                extracted_data = page.evaluate(
                    """async () => {
                    // 1. 获取专属 IM 互关关系链 (仅互关好友与火花好友)
                    let spotData = {};
                    try {
                        const resp = await fetch('/aweme/v1/web/im/spotlight/relation/', {
                            headers: { 'Accept': 'application/json' }
                        });
                        if (resp.ok) spotData = await resp.json();
                    } catch (e) {}

                    const ownerSecUid = spotData.owner_sec_uid || '';

                    // 2. 获取本人资料
                    let selfUser = {};
                    if (ownerSecUid) {
                        try {
                            const profileResp = await fetch(`/aweme/v1/web/user/profile/other/?sec_user_id=${ownerSecUid}`);
                            if (profileResp.ok) {
                                const pData = await profileResp.json();
                                selfUser = pData.user || {};
                            }
                        } catch (e) {}
                    }

                    // Fallback DOM 本人资料
                    const domNickname = document.querySelector('[data-e2e="user-info-nickname"]')?.innerText?.trim();
                    const domDyId = document.querySelector('[data-e2e="user-info-id"]')?.innerText?.replace('抖音号：', '')?.trim();
                    const domAvatar = document.querySelector('[data-e2e="user-avatar"] img')?.src || '';

                    return {
                        selfAccount: {
                            nickname: selfUser.nickname || domNickname || '抖音账号',
                            display_id: selfUser.unique_id || selfUser.short_id || domDyId || '',
                            uid: selfUser.uid || '',
                            sec_uid: ownerSecUid,
                            avatar_url: selfUser.avatar_thumb?.url_list?.[0] || domAvatar || ''
                        },
                        spotlightFollowings: spotData.followings || []
                    };
                }"""
                )

                self_acc = extracted_data.get("selfAccount", {})
                self_uid = str(self_acc.get("uid") or parsed.uid or "self").strip()
                self_dy_id = str(self_acc.get("display_id") or parsed.dy_id or "").strip()
                self_sec_uid = str(self_acc.get("sec_uid") or "").strip()

                # 记录本人候选
                candidates[self_uid] = UserCandidate(
                    uid=self_uid,
                    display_id=self_dy_id,
                    nickname=self_acc.get("nickname") or "抖音账号",
                    avatar_url=self_acc.get("avatar_url") or "",
                    remark="",
                    source="self_profile",
                    self_score=100,
                )

                # 提取严格互相关注好友
                followings = extracted_data.get("spotlightFollowings", [])
                for u in followings:
                    nick = str(u.get("nickname") or "").strip()
                    if not nick:
                        continue
                    # 过滤系统服务号与官方推送号
                    if any(k in nick for k in SYSTEM_BOT_KEYWORDS):
                        continue

                    # 严格校验是否为互相关注 (social_relation_type == 1 表示双方互相关注好友)
                    # 彻底剔除单向关注 (type 5)、推荐 (type 4)、陌生人 (type 0)
                    rel_type = u.get("social_relation_type")
                    if rel_type is not None and rel_type != 1:
                        continue

                    uid = str(u.get("uid") or "").strip()
                    sec_uid = str(u.get("sec_uid") or "").strip()
                    disp_id = str(u.get("unique_id") or u.get("short_id") or uid).strip()

                    # 排除本人
                    if uid == self_uid or sec_uid == self_sec_uid or (disp_id and disp_id == self_dy_id):
                        continue

                    avatar = ""
                    if isinstance(u.get("avatar_thumb"), dict):
                        url_list = u["avatar_thumb"].get("url_list", [])
                        if url_list:
                            avatar = url_list[0]

                    candidates[uid or disp_id] = UserCandidate(
                        uid=uid or disp_id,
                        display_id=disp_id,
                        nickname=nick,
                        avatar_url=avatar,
                        remark=str(u.get("remark_name") or "").strip(),
                        source="spotlight_relation",
                        self_score=0,
                    )

                try:
                    ctx_cookies = context.cookies()
                    if ctx_cookies:
                        refreshed_cookies = json.dumps(ctx_cookies, ensure_ascii=False)
                except Exception:
                    pass

            except PlaywrightTimeoutError as exc:
                browser.close()
                raise ValueError(f"加载抖音页面超时，请检查网络或代理连接: {exc}") from exc
            finally:
                browser.close()

        account_candidate = self._pick_account_candidate(candidates, parsed)
        friends = self._pick_friend_candidates(candidates, account_candidate, parsed)

        if account_candidate is None and not friends:
            return SyncResult(
                account_candidate=None,
                friends=[],
                status=AccountStatus.invalid,
                status_reason="未能从该 Cookie 读取到有效的账号资料，请确认 Cookie 是否完整且有效。",
                refreshed_cookies=refreshed_cookies,
            )

        if friends:
            return SyncResult(
                account_candidate=account_candidate,
                friends=friends,
                status=AccountStatus.healthy,
                status_reason=f"已成功同步 {len(friends)} 位互关好友。",
                refreshed_cookies=refreshed_cookies,
            )

        return SyncResult(
            account_candidate=account_candidate,
            friends=[],
            status=AccountStatus.unknown,
            status_reason="账号资料已加载，但未检测到互关好友（可使用手动添加或批量导入好友）。",
            refreshed_cookies=refreshed_cookies,
        )

    def _sync_friends_to_db(
        self, db: Session, account: Account, incoming_friends: list[UserCandidate]
    ) -> list[Friend]:
        db.refresh(account, attribute_names=["friends"])
        current_friends = (
            db.query(Friend)
            .options(selectinload(Friend.message))
            .filter(Friend.account_id == account.id)
            .all()
        )
        existing_by_dy_id = {friend.friend_dy_id: friend for friend in current_friends}
        incoming_display_ids = {item.display_id for item in incoming_friends if item.display_id}

        # 1. 自动清除数据库中历史残留的系统服务号/官方推送垃圾好友 (如 抖音火山版、头条 等)
        for dy_id, friend in list(existing_by_dy_id.items()):
            if any(k in (friend.friend_nickname or "") for k in SYSTEM_BOT_KEYWORDS):
                db.delete(friend)
                existing_by_dy_id.pop(dy_id, None)

        default_window = get_default_schedule_window(db)
        now = beijing_now()

        # 2. 插入或更新最新纯互关好友
        for item in incoming_friends:
            if not item.display_id:
                continue
            existing = existing_by_dy_id.get(item.display_id)
            if existing is None:
                existing = Friend(
                    account_id=account.id,
                    friend_dy_id=item.display_id,
                    friend_nickname=item.nickname or item.display_id,
                    friend_avatar=item.avatar_url,
                    schedule_window=default_window,
                    is_active=False,
                    last_synced_at=now,
                )
                db.add(existing)
                db.flush()
                db.add(
                    Message(
                        friend_id=existing.id,
                        message_type=MessageType.fixed,
                        message_content=DEFAULT_MESSAGE,
                    )
                )
                existing_by_dy_id[item.display_id] = existing
            else:
                if item.nickname:
                    existing.friend_nickname = item.nickname
                if item.avatar_url:
                    existing.friend_avatar = item.avatar_url
                existing.last_synced_at = now

        db.flush()
        return (
            db.query(Friend)
            .options(selectinload(Friend.message))
            .filter(Friend.account_id == account.id)
            .all()
        )

    def _find_self_candidate(
        self, account: Account, friends: list[UserCandidate], parsed: ParsedCredential
    ) -> UserCandidate | None:
        known_ids = {value for value in (account.dy_id, parsed.dy_id, parsed.uid) if value}
        for friend in friends:
            if friend.uid in known_ids or friend.display_id in known_ids:
                return friend

        nickname = self._normalize_name(account.nickname)
        if not nickname:
            return None

        nickname_matches = [
            friend for friend in friends if self._normalize_name(friend.nickname) == nickname
        ]
        if len(nickname_matches) == 1 and (not account.dy_id or not account.avatar_url):
            return nickname_matches[0]
        return None

    def _without_account_candidate(
        self, friends: list[UserCandidate], account_candidate: UserCandidate | None
    ) -> list[UserCandidate]:
        if account_candidate is None:
            return friends

        return [
            friend
            for friend in friends
            if friend.uid != account_candidate.uid
            and friend.display_id != account_candidate.display_id
        ]

    def _normalize_name(self, value: str | None) -> str:
        return re.sub(r"\s+", "", value or "").casefold()

    def _pick_account_candidate(
        self, candidates: dict[str, UserCandidate], parsed: ParsedCredential
    ) -> UserCandidate | None:
        if parsed.uid and parsed.uid in candidates:
            return candidates[parsed.uid]

        high_score = sorted(
            candidates.values(),
            key=lambda item: (item.self_score, bool(item.avatar_url), bool(item.display_id)),
            reverse=True,
        )
        if high_score and high_score[0].self_score > 0:
            return high_score[0]

        return None

    def _pick_friend_candidates(
        self,
        candidates: dict[str, UserCandidate],
        account_candidate: UserCandidate | None,
        parsed: ParsedCredential,
    ) -> list[UserCandidate]:
        excluded_uids = {parsed.uid} if parsed.uid else set()
        excluded_display_ids = {parsed.dy_id} if parsed.dy_id else set()
        if account_candidate is not None:
            excluded_uids.add(account_candidate.uid)
            if account_candidate.display_id:
                excluded_display_ids.add(account_candidate.display_id)

        friends: list[UserCandidate] = []
        for candidate in candidates.values():
            if candidate.uid in excluded_uids:
                continue
            if candidate.display_id in excluded_display_ids:
                continue
            if not candidate.display_id or not candidate.nickname:
                continue
            # 严格过滤系统号与官方号
            if any(k in candidate.nickname for k in SYSTEM_BOT_KEYWORDS):
                continue
            friends.append(candidate)

        friends.sort(key=lambda item: (item.nickname.lower(), item.display_id.lower()))
        return friends

    def _to_playwright_cookies(self, cookie_text: str) -> list[dict[str, Any]]:
        parsed_json = self._try_parse_cookie_json(cookie_text)
        if parsed_json is not None:
            cookies: list[dict[str, Any]] = []
            for item in parsed_json:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                value = str(item.get("value", "")).strip()
                if not name or not value:
                    continue
                cookie: dict[str, Any] = {"name": name, "value": value}
                domain = str(item.get("domain", "")).strip()
                if not domain or "douyin.com" in domain:
                    cookie["domain"] = ".douyin.com"
                else:
                    cookie["domain"] = domain
                cookie["path"] = "/"

                same_site = str(item.get("sameSite", "")).strip().lower()
                if same_site in ("strict",):
                    cookie["sameSite"] = "Strict"
                elif same_site in ("lax", "unspecified"):
                    cookie["sameSite"] = "Lax"
                elif same_site in ("none", "no_restriction"):
                    cookie["sameSite"] = "None"

                secure = item.get("secure")
                if isinstance(secure, bool):
                    cookie["secure"] = secure
                else:
                    cookie["secure"] = True

                expires = item.get("expires")
                if isinstance(expires, (int, float)) and expires > 0:
                    cookie["expires"] = expires
                cookies.append(cookie)
            if cookies:
                return cookies

        cookies = []
        clean_text = cookie_text.strip()
        if clean_text.lower().startswith("cookie:"):
            clean_text = clean_text[7:].strip()
        for part in clean_text.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            cleaned_name = name.strip()
            cleaned_value = value.strip()
            if not cleaned_name or not cleaned_value:
                continue
            cookies.append(
                {
                    "name": cleaned_name,
                    "value": cleaned_value,
                    "domain": ".douyin.com",
                    "path": "/",
                    "secure": True,
                }
            )
        if not cookies:
            raise ValueError("Cookie 内容为空或格式不正确，请重新复制并粘贴。")
        return cookies

    def _extract_avatar_url(self, obj: dict[str, Any]) -> str:
        candidates = [
            obj.get("avatar_url"),
            obj.get("avatar_thumb"),
            obj.get("avatar_medium"),
            obj.get("avatar_larger"),
            obj.get("avatar_168x168"),
        ]
        for candidate in candidates:
            url = self._normalize_avatar(candidate)
            if url:
                return url
        return ""

    def _normalize_avatar(self, candidate: object) -> str:
        if isinstance(candidate, str):
            url = candidate.strip()
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http"):
                return url
        if isinstance(candidate, dict):
            url_list = candidate.get("url_list")
            if isinstance(url_list, list) and len(url_list) > 0:
                return self._normalize_avatar(url_list[0])

            for key in ("url_list", "url", "uri"):
                value = candidate.get(key)
                if value:
                    res = self._normalize_avatar(value)
                    if res:
                        return res
        return ""

    def _try_parse_cookie_json(self, cookie_text: str) -> list[dict[str, Any]] | None:
        stripped = cookie_text.strip()
        if not (stripped.startswith("[") or stripped.startswith("{")):
            return None
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                if "cookies" in parsed and isinstance(parsed["cookies"], list):
                    return parsed["cookies"]
                return [{"name": k, "value": str(v), "domain": ".douyin.com", "path": "/"} for k, v in parsed.items()]
        except json.JSONDecodeError:
            pass
        return None

    def _dismiss_non_login_dialogs(self, page: Any) -> None:
        """自动关闭网页中的通知、引导及非登录遮罩弹窗。"""
        non_login_texts = ["我知道了", "知道了", "好的", "确定", "确认", "稍后再说", "关闭", "取消"]
        for text in non_login_texts:
            try:
                loc = page.get_by_text(text, exact=True).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=1000)
            except Exception:
                continue
        close_selectors = [
            ".semi-modal-close",
            "button[aria-label='Close']",
            "button[aria-label='关闭']",
            "[aria-label='Close']",
            "[aria-label='关闭']",
            ".modal-close-icon",
        ]
        for sel in close_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=1000)
            except Exception:
                continue


credential_service = CredentialService()
