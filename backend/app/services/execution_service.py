from __future__ import annotations

import random
import time
from typing import NamedTuple

from playwright.sync_api import Locator, Page, sync_playwright

from ..models import Account, Friend
from .secret_service import get_secret_service

LOGIN_DIALOG_MARKERS = ("扫码登录", "验证码登录", "登录/注册", "密码登录")
DISMISS_BUTTON_TEXTS = ("取消", "暂不", "知道了", "关闭", "稍后再说", "继续逛逛")
DIALOG_SELECTORS = (".semi-modal-content", '[role="dialog"]', ".semi-toast")
INPUT_SELECTORS = ('div[contenteditable="true"]', '[role="textbox"]', "textarea", ".chat-input")
SEARCH_SELECTORS = ('input[placeholder*="搜索"]', 'input[placeholder*="查找"]', 'input[type="search"]')
FRIEND_FIND_DEADLINE_SECONDS = 25
INPUT_WAIT_DEADLINE_SECONDS = 12


class ExecutionResult(NamedTuple):
    success: bool
    summary: str
    details: str


class ExecutionService:
    def send_message(self, account: Account, friend: Friend, content: str) -> ExecutionResult:
        if not account.cookie_text:
            return ExecutionResult(False, "缺少凭证", "账号没有配置 Cookie 凭证")

        try:
            cookie_text = get_secret_service().decrypt(account.cookie_text)
        except ValueError as exc:
            return ExecutionResult(False, "Stored credential unavailable", str(exc))

        cookies = self._parse_cookies(cookie_text)
        
        with sync_playwright() as playwright:
            browser_args = ["--disable-blink-features=AutomationControlled"]
            proxy_settings = None
            if account.proxy_url:
                proxy_settings = {"server": account.proxy_url}

            browser = playwright.chromium.launch(
                headless=True,
                args=browser_args,
                proxy=proxy_settings
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

            try:
                # 1. 访问消息页面
                page.goto("https://www.douyin.com/chat", timeout=60000, wait_until="domcontentloaded")
                time.sleep(random.uniform(2, 4))

                # 1.5 关闭非登录弹窗（如“是否保存登录信息”），避免遮挡列表和输入框
                self._dismiss_dialogs(page)

                # 2. 寻找好友（轮询等待列表加载 + 搜索 + 滚动，三重策略）
                target_name = friend.friend_nickname
                target_dy_id = friend.friend_dy_id

                friend_item = self._find_friend(page, target_name, target_dy_id)
                if friend_item is None:
                    return ExecutionResult(
                        False,
                        "未找到好友",
                        f"在列表中未找到 {target_name} ({target_dy_id})",
                    )

                friend_item.click()
                time.sleep(random.uniform(1.5, 3.0))

                # 3. 输入消息 (拟人化输入)
                input_box = self._find_input_box(page)
                if not input_box:
                    return ExecutionResult(False, "未找到输入框", "无法定位到聊天输入框")

                input_box.focus()
                # 模拟真人一个字一个字打
                for char in content:
                    page.keyboard.type(char, delay=random.randint(50, 200))
                
                time.sleep(random.uniform(0.5, 1.2))
                
                # 4. 发送 (按下回车)
                page.keyboard.press("Enter")
                time.sleep(1.5)

                # 5. 发送结果取证
                verified, evidence = self._verify_message_sent(page, input_box, content)
                if verified:
                    return ExecutionResult(True, "发送成功", f"成功向 {target_name} 发送: {content}。{evidence}")
                return ExecutionResult(
                    False,
                    "发送结果未确认",
                    f"已尝试向 {target_name} 发送: {content}，但未找到可靠的页面发送证据。{evidence}",
                )

            except Exception as e:
                return ExecutionResult(False, "执行异常", str(e))
            finally:
                browser.close()

    def _dismiss_dialogs(self, page: Page) -> None:
        """关闭非登录弹窗，绝不触碰登录弹窗。"""
        deadline = time.time() + 10
        while time.time() < deadline:
            dismissed = False
            for selector in DIALOG_SELECTORS:
                for dialog in page.locator(selector).all():
                    try:
                        if not dialog.is_visible():
                            continue
                        text = (dialog.inner_text(timeout=1000) or "").replace("\n", " ")
                        if any(marker in text for marker in LOGIN_DIALOG_MARKERS):
                            continue
                        clicked = False
                        for button_text in DISMISS_BUTTON_TEXTS:
                            button = dialog.get_by_text(button_text, exact=True).first
                            if button.count() and button.is_visible():
                                button.click(timeout=2000)
                                clicked = True
                                dismissed = True
                                break
                        if not clicked:
                            close = dialog.locator('[aria-label="Close"], .semi-modal-close').first
                            if close.count() and close.is_visible():
                                close.click(timeout=2000)
                                dismissed = True
                    except Exception:
                        continue
            if not dismissed:
                return
            time.sleep(0.6)

    def _find_visible_match(self, page: Page, text: str) -> Locator | None:
        try:
            for candidate in page.get_by_text(text, exact=True).all():
                if candidate.is_visible():
                    return candidate
        except Exception:
            pass
        try:
            for candidate in page.locator(f"text='{text}'").all():
                if candidate.is_visible():
                    return candidate
        except Exception:
            pass
        return None

    def _try_search(self, page: Page, query: str) -> None:
        for selector in SEARCH_SELECTORS:
            box = page.locator(selector).first
            try:
                if box.count() and box.is_visible():
                    box.click(timeout=2000)
                    box.fill(query)
                    page.keyboard.press("Enter")
                    time.sleep(1.5)
                    return
            except Exception:
                continue

    def _scroll_friend_list(self, page: Page) -> None:
        try:
            page.mouse.move(400, 400)
            page.mouse.wheel(0, 600)
        except Exception:
            pass

    def _find_friend(self, page: Page, name: str, dy_id: str) -> Locator | None:
        deadline = time.time() + FRIEND_FIND_DEADLINE_SECONDS
        searched = False
        scrolled_rounds = 0
        while time.time() < deadline:
            match = self._find_visible_match(page, name)
            if match:
                return match

            if not searched:
                self._try_search(page, dy_id or name)
                searched = True
                continue

            if scrolled_rounds < 12:
                self._scroll_friend_list(page)
                scrolled_rounds += 1
                time.sleep(0.6)
                continue

            # 搜索和滚动都用过，最后一轮重新加载页面兜底
            try:
                page.reload(wait_until="domcontentloaded")
                time.sleep(3)
                self._dismiss_dialogs(page)
                searched = False
                scrolled_rounds = 0
            except Exception:
                return None
        return None

    def _find_input_box(self, page: Page) -> Locator | None:
        deadline = time.time() + INPUT_WAIT_DEADLINE_SECONDS
        while time.time() < deadline:
            for selector in INPUT_SELECTORS:
                loc = page.locator(selector).first
                try:
                    if loc.count() and loc.is_visible():
                        return loc
                except Exception:
                    continue
            time.sleep(0.8)
        return None

    def _verify_message_sent(self, page: Page, input_box: Locator, content: str) -> tuple[bool, str]:
        normalized_content = content.strip()
        if not normalized_content:
            return False, "消息内容为空，无法校验。"

        deadline = time.time() + 8
        latest_reason = "等待页面回写发送结果。"

        while time.time() < deadline:
            input_cleared = self._is_input_cleared(input_box, normalized_content)
            message_visible = self._is_message_visible(page, normalized_content)

            if input_cleared and message_visible:
                return True, "已确认输入框清空，且聊天区域出现匹配文本。"
            if message_visible:
                return True, "已确认聊天区域出现匹配文本。"
            if input_cleared:
                latest_reason = "输入框已清空，但聊天区域尚未发现匹配文本。"
            else:
                latest_reason = "聊天区域和输入框都还未提供足够证据。"
            time.sleep(0.8)

        return False, latest_reason

    def _is_input_cleared(self, input_box: Locator, content: str) -> bool:
        try:
            if input_box.count() == 0:
                return True
        except Exception:
            return False

        candidates: list[str] = []
        try:
            raw_text = input_box.text_content(timeout=1000) or ""
            candidates.append(raw_text.strip())
        except Exception:
            pass

        try:
            inner_text = input_box.inner_text(timeout=1000) or ""
            candidates.append(inner_text.strip())
        except Exception:
            pass

        try:
            input_value = input_box.input_value(timeout=1000) or ""
            candidates.append(input_value.strip())
        except Exception:
            pass

        if not candidates:
            return False

        normalized_content = content.strip()
        return all(candidate == "" or candidate != normalized_content for candidate in candidates)

    def _is_message_visible(self, page: Page, content: str) -> bool:
        selectors = [
            ".message-content",
            ".chat-message",
            ".im-message",
            "[class*='message-text']",
            "[class*='messageContent']",
            "[class*='msg-content']",
            "[data-e2e*='message']",
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector).get_by_text(content, exact=True).first
                if locator.is_visible(timeout=1000):
                    return True
            except Exception:
                pass

        try:
            locator = page.get_by_text(content, exact=True).first
            return locator.is_visible(timeout=1000)
        except Exception:
            return False

    def _parse_cookies(self, cookie_text: str) -> list[dict]:
        """Parse raw cookie string into Playwright format."""
        try:
            import json
            data = json.loads(cookie_text.strip())
            if isinstance(data, list):
                # 如果是 JSON 格式，需要清洗 sameSite 等字段
                clean_cookies = []
                for item in data:
                    if not isinstance(item, dict): continue
                    c = {
                        "name": str(item.get("name", "")),
                        "value": str(item.get("value", "")),
                        "domain": str(item.get("domain", ".douyin.com")),
                        "path": str(item.get("path", "/"))
                    }
                    ss = item.get("sameSite")
                    if ss in ["Strict", "Lax", "None"]:
                        c["sameSite"] = ss
                    
                    if "expires" in item: c["expires"] = item["expires"]
                    if "secure" in item: c["secure"] = item["secure"]
                    clean_cookies.append(c)
                return clean_cookies
        except:
            pass
            
        cookies = []
        for part in cookie_text.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".douyin.com",
                "path": "/"
            })
        return cookies


execution_service = ExecutionService()
