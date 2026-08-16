from __future__ import annotations

import random
import time
from typing import NamedTuple

from playwright.sync_api import Locator, Page, sync_playwright

from ..models import Account, Friend
from .secret_service import get_secret_service


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
                time.sleep(random.uniform(3, 5))

                # 2. 寻找好友
                # 抖音网页版的好友列表搜索通常需要点击搜索框或直接在侧边栏滚动查找
                # 这里我们采用“搜索框精准匹配” + “列表兜底”策略
                
                target_name = friend.friend_nickname
                target_dy_id = friend.friend_dy_id

                # 尝试通过侧边栏点击
                friend_selector = f"text='{target_name}'"
                friend_item = page.locator(friend_selector).first
                
                if not friend_item.is_visible():
                    # 尝试用 dy_id (短号) 搜索
                    try:
                        search_box = page.locator('input[placeholder*="搜索"]').first
                        if search_box.is_visible():
                            search_box.click()
                            page.keyboard.type(target_dy_id, delay=100)
                            page.keyboard.press("Enter")
                            time.sleep(2)
                            # 搜索结果中的第一项
                            friend_item = page.locator(f"text='{target_name}'").first
                    except:
                        pass

                if not friend_item.is_visible():
                    # 最后的兜底：滚动列表
                    for _ in range(5):
                        page.mouse.wheel(0, 500)
                        time.sleep(0.5)
                        if friend_item.is_visible(): break

                if not friend_item.is_visible():
                    return ExecutionResult(False, "未找到好友", f"在列表中未找到 {target_name} ({target_dy_id})")

                friend_item.click()
                time.sleep(random.uniform(1.5, 3.0))

                # 3. 输入消息 (拟人化输入)
                input_selectors = [
                    'div[contenteditable="true"]',
                    'textarea',
                    '[role="textbox"]',
                    '.chat-input'
                ]
                
                input_box = None
                for selector in input_selectors:
                    loc = page.locator(selector).first
                    if loc.is_visible():
                        input_box = loc
                        break
                
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
