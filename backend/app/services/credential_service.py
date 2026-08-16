from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session, selectinload

from ..models import Account, AccountStatus, Friend, Message, MessageType
from ..time_utils import beijing_now, from_beijing_epoch
from .secret_service import get_secret_service


DEFAULT_MESSAGE = "[pending] configure message content here"


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
            for part in cookie_text.split(";"):
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                cookie_map[name.strip()] = value.strip()
            uid = cookie_map.get("uid") or cookie_map.get("user_id") or ""
            dy_id = cookie_map.get("sec_uid") or uid

        return ParsedCredential(dy_id=dy_id, uid=uid)

    def import_account(self, db: Session, cookie_text: str) -> Account:
        sync_result = self._extract_from_cookie(cookie_text)
        parsed = self.parse_cookie_text(cookie_text)
        account_candidate = sync_result.account_candidate
        friends = self._without_account_candidate(sync_result.friends, account_candidate)
        cookie_expires_at = self.extract_cookie_expires_at(cookie_text)
        now = beijing_now()

        # 最终清洗：如果 display_id 依然是那串长字符，且我们有昵称，就干脆把它设为空或者更短的形式
        final_display_id = (
            account_candidate.display_id
            if account_candidate and account_candidate.display_id
            else parsed.dy_id
        )
        if final_display_id and (len(final_display_id) > 30 or final_display_id.startswith("MS4w")):
            # 尝试从 cookie 里的 uid 恢复一个短的
            final_display_id = parsed.uid or "已托管账号"

        account = Account(
            nickname=(
                account_candidate.nickname
                if account_candidate and account_candidate.nickname
                else "Imported account"
            ),
            dy_id=final_display_id,
            avatar_url=(
                account_candidate.avatar_url
                if account_candidate and account_candidate.avatar_url
                else ""
            ),
            cookie_text=get_secret_service().encrypt(cookie_text),
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

        now = beijing_now()
        account.cookie_text = get_secret_service().encrypt(cookie_text)
        account.cookie_expires_at = self.extract_cookie_expires_at(cookie_text)
        account.cookie_updated_at = now
        account.status = sync_result.status
        account.status_reason = (
            f"Synced {len(friends)} contacts from Douyin Web chat."
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
        session_cookie_names = {"sessionid", "sessionid_ss", "sid_guard", "uid_tt", "uid_tt_ss"}
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

        account.status = sync_result.status
        account.status_reason = (
            f"Synced {len(friends)} contacts from Douyin Web chat."
            if friends
            else sync_result.status_reason
        )
        account.last_checked_at = beijing_now()
        return self._sync_friends_to_db(db, account, friends)

    def _extract_from_cookie(self, cookie_text: str) -> SyncResult:
        parsed = self.parse_cookie_text(cookie_text)
        cookies = self._to_playwright_cookies(cookie_text)
        candidates: dict[str, UserCandidate] = {}
        response_candidates: list[dict[str, object]] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
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
            context.add_cookies(cookies)
            page = context.new_page()

            def capture_candidate(obj: dict[str, object], source: str) -> None:
                uid = str(obj.get("uid") or obj.get("user_id") or "").strip()
                nickname = str(obj.get("nickname") or "").strip()
                if not uid or not nickname:
                    return

                unique_id = str(obj.get("unique_id") or "").strip()
                short_id = str(obj.get("short_id") or "").strip()
                sec_uid = str(obj.get("sec_uid") or "").strip()
                
                # 判定 ID 质量：长字符串 (sec_uid) 优先级最低
                def get_best_id(u_id, s_id, sec):
                    if u_id and not u_id.startswith("MS4w"): return u_id
                    if s_id: return s_id
                    return sec or u_id

                display_id = get_best_id(unique_id, short_id, sec_uid)
                avatar_url = self._extract_avatar_url(obj)
                remark = str(obj.get("remark_name") or "").strip()
                
                self_score = 0
                for key in ("is_self", "self_user", "is_current_user", "mine", "is_owner"):
                    if obj.get(key) is True:
                        self_score += 8
                if source == "storage":
                    self_score += 2

                candidate = UserCandidate(
                    uid=uid,
                    display_id=display_id,
                    nickname=nickname,
                    avatar_url=avatar_url,
                    remark=remark,
                    source=source,
                    self_score=self_score,
                )

                existing = candidates.get(uid)
                if existing is None:
                    candidates[uid] = candidate
                    return

                # 智能合并逻辑
                # 1. 评分更高的优先
                if candidate.self_score > existing.self_score:
                    existing.self_score = candidate.self_score
                
                # 2. 如果新获取的 ID 质量更好（不是加密长串），则更新
                if existing.display_id.startswith("MS4w") and not candidate.display_id.startswith("MS4w"):
                    existing.display_id = candidate.display_id
                
                # 3. 补全缺失信息
                if not existing.avatar_url and candidate.avatar_url:
                    existing.avatar_url = candidate.avatar_url
                if not existing.nickname and candidate.nickname:
                    existing.nickname = candidate.nickname
                if not existing.remark and candidate.remark:
                    existing.remark = candidate.remark

            def extract_deep(payload: object, source: str) -> None:
                if isinstance(payload, dict):
                    capture_candidate(payload, source)
                    for value in payload.values():
                        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                            try:
                                extract_deep(json.loads(value), source)
                            except Exception:
                                continue
                        elif isinstance(value, (dict, list)):
                            extract_deep(value, source)
                elif isinstance(payload, list):
                    for item in payload:
                        extract_deep(item, source)

            def on_response(response) -> None:
                try:
                    if response.request.resource_type not in ["fetch", "xhr"]:
                        return
                    if not response.ok:
                        return
                    url = response.url
                    if "im/user/info" not in url and "user/info" not in url:
                        return
                    data = response.json()
                    response_candidates.append({"url": url, "data": data})
                    extract_deep(data, "network")
                except Exception:
                    return

            page.on("response", on_response)

            try:
                # 1. 优先尝试消息页面（获取好友列表最快）
                page.goto("https://www.douyin.com/chat", timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                
                # 滚动列表以触发网络包
                for _ in range(8):
                    page.mouse.wheel(0, 400)
                    page.wait_for_timeout(500)

                # 检查是否已经抓取到了当前账号的完整资料
                account_candidate = self._pick_account_candidate(candidates, parsed)
                
                # 如果没拿到头像或抖音号，作为 Fallback 访问个人主页
                if not account_candidate or not account_candidate.avatar_url or account_candidate.display_id.startswith("MS4w"):
                    page.goto("https://www.douyin.com/user/self", timeout=40000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    
                    # 在个人主页尝试从 DOM 或 SSR 数据中直接提取
                    extra_data = page.evaluate("""() => {
                        const data = {
                            nickname: document.querySelector('[data-e2e="user-info-nickname"]')?.innerText,
                            unique_id: document.querySelector('[data-e2e="user-info-id"]')?.innerText?.replace('抖音号：', '')?.trim(),
                            avatar_url: document.querySelector('[data-e2e="user-avatar"] img')?.src
                        };
                        if (!data.avatar_url) {
                            const avatarImg = Array.from(document.querySelectorAll('img')).find((img) => {
                                const src = img.src || '';
                                const alt = img.alt || '';
                                const className = String(img.className || '');
                                return src.includes('avatar') || src.includes('douyinpic.com') || alt.includes('头像') || className.toLowerCase().includes('avatar');
                            });
                            data.avatar_url = avatarImg?.src || '';
                        }
                        return data;
                    }""")
                    if extra_data and (extra_data.get('nickname') or extra_data.get('unique_id')):
                        # 构造一个高分候选人
                        uid = parsed.uid or "self"
                        candidates[uid] = UserCandidate(
                            uid=uid,
                            display_id=extra_data.get('unique_id') or (account_candidate.display_id if account_candidate else ""),
                            nickname=extra_data.get('nickname') or (account_candidate.nickname if account_candidate else ""),
                            avatar_url=extra_data.get('avatar_url') or (account_candidate.avatar_url if account_candidate else ""),
                            remark="",
                            source="dom_fallback",
                            self_score=100
                        )

                # 提取 Storage 数据作为补充
                storage_candidates = page.evaluate(
                    """() => {
                        const snapshots = [];
                        const collect = (source, storage) => {
                          for (let i = 0; i < storage.length; i += 1) {
                            const key = storage.key(i);
                            const value = storage.getItem(key);
                            if (!value || typeof value !== 'string') continue;
                            if (value.includes('nickname') && (value.includes('uid') || value.includes('user_id'))) {
                              snapshots.push({ source, key, value });
                            }
                          }
                        };
                        collect('localStorage', window.localStorage);
                        collect('sessionStorage', window.sessionStorage);
                        return snapshots;
                    }"""
                )
                for item in storage_candidates:
                    try:
                        extract_deep(json.loads(item["value"]), "storage")
                    except Exception:
                        continue
            except PlaywrightTimeoutError as exc:
                browser.close()
                raise ValueError(f"Timed out while loading Douyin chat page: {exc}") from exc
            finally:
                browser.close()

        account_candidate = self._pick_account_candidate(candidates, parsed)
        friends = self._pick_friend_candidates(candidates, account_candidate, parsed)

        if account_candidate is None and not friends:
            return SyncResult(
                account_candidate=None,
                friends=[],
                status=AccountStatus.invalid,
                status_reason=(
                    "Unable to read account data from this cookie. "
                    "Check that the cookie is complete and still valid."
                ),
            )

        if friends:
            return SyncResult(
                account_candidate=account_candidate,
                friends=friends,
                status=AccountStatus.healthy,
                status_reason=f"Synced {len(friends)} contacts from Douyin Web chat.",
            )

        return SyncResult(
            account_candidate=account_candidate,
            friends=[],
            status=AccountStatus.unknown,
            status_reason="Account profile loaded, but no contacts were captured from chat traffic.",
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
        incoming_ids = {item.display_id for item in incoming_friends if item.display_id}

        for friend in current_friends:
            if friend.friend_dy_id not in incoming_ids:
                db.delete(friend)

        synced: list[Friend] = []
        for item in incoming_friends:
            existing = existing_by_dy_id.get(item.display_id)
            if existing is None:
                existing = Friend(
                    account_id=account.id,
                    friend_dy_id=item.display_id,
                    friend_nickname=item.nickname or item.display_id,
                    friend_avatar=item.avatar_url,
                    last_synced_at=beijing_now(),
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
            else:
                existing.friend_nickname = item.nickname or existing.friend_nickname
                existing.friend_avatar = item.avatar_url or existing.friend_avatar
                existing.last_synced_at = beijing_now()
            synced.append(existing)

        return synced

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

        storage_candidates = [item for item in candidates.values() if item.source == "storage"]
        if storage_candidates:
            return sorted(
                storage_candidates,
                key=lambda item: (
                    item.self_score,
                    bool(item.avatar_url),
                    bool(item.display_id),
                    item.nickname,
                ),
                reverse=True,
            )[0]

        high_confidence = [item for item in candidates.values() if item.self_score > 0]
        if high_confidence:
            return sorted(
                high_confidence,
                key=lambda item: (item.self_score, bool(item.avatar_url), bool(item.display_id)),
                reverse=True,
            )[0]

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
            friends.append(candidate)

        friends.sort(key=lambda item: (item.nickname.lower(), item.display_id.lower()))
        return friends

    def _to_playwright_cookies(self, cookie_text: str) -> list[dict[str, object]]:
        parsed_json = self._try_parse_cookie_json(cookie_text)
        if parsed_json is not None:
            cookies: list[dict[str, object]] = []
            for item in parsed_json:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                value = str(item.get("value", "")).strip()
                if not name or not value:
                    continue
                cookie: dict[str, object] = {"name": name, "value": value}
                domain = str(item.get("domain", "")).strip()
                path = str(item.get("path", "/")).strip() or "/"
                if domain:
                    cookie["domain"] = domain
                    cookie["path"] = path
                else:
                    cookie["url"] = "https://www.douyin.com"
                same_site = item.get("sameSite")
                if same_site in {"Lax", "None", "Strict"}:
                    cookie["sameSite"] = same_site
                secure = item.get("secure")
                if isinstance(secure, bool):
                    cookie["secure"] = secure
                expires = item.get("expires")
                if isinstance(expires, (int, float)) and expires > 0:
                    cookie["expires"] = expires
                cookies.append(cookie)
            if cookies:
                return cookies

        cookies = []
        for part in cookie_text.split(";"):
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
                    "url": "https://www.douyin.com",
                }
            )
        if not cookies:
            raise ValueError("Cookie text is empty or malformed.")
        return cookies

    def _extract_avatar_url(self, obj: dict[str, object]) -> str:
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
            url = candidate
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http"):
                return url
        if isinstance(candidate, dict):
            # 抖音 API 经常把 URL 放在 url_list 数组里
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

    def _try_parse_cookie_json(self, cookie_text: str) -> list[dict[str, object]] | None:
        stripped = cookie_text.strip()
        if not stripped.startswith("["):
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None


credential_service = CredentialService()
