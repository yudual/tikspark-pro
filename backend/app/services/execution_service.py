from __future__ import annotations

import json
import random
import re
import time
from typing import NamedTuple

from playwright.sync_api import Locator, Page, sync_playwright

import os
import shutil

from ..models import Account, Friend
from .secret_service import get_secret_service


def get_browser_executable_path() -> str | None:
    for path in ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]:
        if os.path.exists(path):
            return path
    return shutil.which("google-chrome-stable") or shutil.which("google-chrome") or shutil.which("chromium")

LOGIN_DIALOG_MARKERS = ("扫码登录", "验证码登录", "登录/注册", "密码登录")
DISMISS_BUTTON_TEXTS = ("取消", "暂不", "知道了", "关闭", "稍后再说", "继续逛逛", "暂不开启")
DIALOG_SELECTORS = (".semi-modal-content", '[role="dialog"]', ".semi-toast", '[class*="modal"]')
INPUT_SELECTORS = (
    'div[contenteditable="true"]',
    '[role="textbox"]',
    "textarea",
    ".chat-input",
    "[class*='chat-input']",
    "[class*='editor-input']",
    "[class*='message-editor']",
)
SEARCH_SELECTORS = (
    'input[placeholder*="搜索"]',
    'input[placeholder*="查找"]',
    'input[placeholder*="好友"]',
    'input[type="search"]',
    '[class*="search-input"] input',
)
SEND_BUTTON_SELECTORS = (
    'button:has-text("发送")',
    '[data-e2e*="send"]',
    '[class*="send-btn"]',
    '[class*="sendBtn"]',
    '[class*="send_btn"]',
    '.semi-button-primary:has-text("发送")',
)
MESSAGE_CONTENT_SELECTORS = (
    ".message-content",
    ".chat-message",
    ".im-message",
    "[class*='message-text']",
    "[class*='messageContent']",
    "[class*='msg-content']",
    "[data-e2e*='message']",
)
EMOJI_BUTTON_SELECTORS = (
    "svg.messageMsgInputiconAction",
    '[data-e2e*="emoji"]',
    '[aria-label*="表情"]',
    '[title*="表情"]',
    ".emoji-btn",
    '[class*="emoji-btn"]',
    '[class*="emojiButton"]',
    '[class*="emoji-icon"]',
)
SPARK_ITEM_SELECTORS = (
    ".emojiEmojiItememojiItem",
    'img[alt*="火花"]',
    '[title*="火花"]',
    '[aria-label*="火花"]',
    'img[src*="huohua"]',
    'img[src*="fire"]',
    'img[src*="spark"]',
    '[style*="huohua"]',
    '[class*="emoji-item"]:has-text("火花")',
)
CONTACT_CONTAINER_SELECTORS = (
    ".im-user-list",
    '[class*="user-list"]',
    '[class*="conversation-list"]',
    '[class*="session-list"]',
    '[class*="contact-list"]',
    '[class*="chat-list"]',
)

EMOJI_PANEL_WAIT_SECONDS = 6
FRIEND_FIND_DEADLINE_SECONDS = 30
INPUT_WAIT_DEADLINE_SECONDS = 15

SPARK_STICKER_TOKEN = "[火花]"

PLAYWRIGHT_STEALTH_SCRIPT = """
(() => {
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });

        window.chrome = {
            app: {
                isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
            },
            runtime: {
                OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
                OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
                PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
                RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
            }
        };

        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en'],
        });

        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });

        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    } catch (e) {}
})();
"""


def normalize_friend_name(name: str | None) -> str:
    """去除特殊符号、空格、emoji，以便进行容错模糊匹配。"""
    if not name:
        return ""
    # 去除括号备注部分，如 "张三 (同事)" -> "张三"
    cleaned = re.sub(r"[\(（\[【].*?[\)）\]】]", "", name)
    # 去除空白与标点
    cleaned = re.sub(r"[\s\-_@#\$%^&*\+=\|:;\"'<>,.?/~`！￥…—]+", "", cleaned)
    # 去除常见 emoji 编码段
    cleaned = re.sub(r"[\U00010000-\U0010ffff\uD800-\uDBFF\uDC00-\uDFFF\u2600-\u27BF]", "", cleaned)
    return cleaned.strip().casefold()


def split_spark_content(content: str) -> list[tuple[str, str]]:
    """把消息内容拆成文本段与 [火花] 表情段。

    返回 [("text", "早呀 "), ("spark", ""), ("text", "！")] 这样的有序分段，
    纯文本内容只会得到一个 text 段，方便执行器逐段处理。
    """
    segments: list[tuple[str, str]] = []
    remainder = content or ""
    while remainder:
        index = remainder.find(SPARK_STICKER_TOKEN)
        if index < 0:
            segments.append(("text", remainder))
            break
        if index > 0:
            segments.append(("text", remainder[:index]))
        segments.append(("spark", ""))
        remainder = remainder[index + len(SPARK_STICKER_TOKEN):]
    return segments


class ExecutionResult(NamedTuple):
    success: bool
    summary: str
    details: str
    refreshed_cookies: str | None = None


class ExecutionService:
    def send_message(self, account: Account, friend: Friend, content: str) -> ExecutionResult:
        if not account.cookie_text:
            return ExecutionResult(False, "缺少凭证", "账号没有配置 Cookie 凭证")

        try:
            cookie_text = get_secret_service().decrypt(account.cookie_text)
        except ValueError as exc:
            return ExecutionResult(False, "凭证解密失败", str(exc))

        cookies = self._parse_cookies(cookie_text)
        refreshed_cookies: str | None = None

        with sync_playwright() as playwright:
            browser_args = [
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
            ]
            proxy_settings = None
            if account.proxy_url:
                proxy_settings = {"server": account.proxy_url}

            exe_path = get_browser_executable_path()
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": browser_args,
                "proxy": proxy_settings,
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
            # 注入防反爬脚本
            context.add_init_script(PLAYWRIGHT_STEALTH_SCRIPT)
            context.add_cookies(cookies)
            page = context.new_page()

            def _get_context_cookies() -> str | None:
                try:
                    c = context.cookies()
                    if c:
                        return json.dumps(c, ensure_ascii=False)
                except Exception:
                    pass
                return None

            try:
                # 1. 访问消息页面
                page.goto("https://www.douyin.com/chat", timeout=60000, wait_until="domcontentloaded")
                time.sleep(random.uniform(2.0, 3.5))

                # 1.5 关闭非登录弹窗
                self._dismiss_dialogs(page)

                # 检查 WAF / 滑块验证码 / 空白页
                waf_issue = self._check_waf_or_captcha(page)
                if waf_issue:
                    return ExecutionResult(
                        False,
                        "页面被风控拦截",
                        waf_issue,
                        refreshed_cookies=_get_context_cookies(),
                    )

                # 检查登录状态
                if self._check_login_required(page):
                    return ExecutionResult(
                        False,
                        "账号凭证已失效",
                        "检测到抖音网页弹出登录对话框，Cookie 凭证已过期或被风控失效，请重新获取并更新 Cookie。",
                        refreshed_cookies=_get_context_cookies(),
                    )

                # 2. 寻找好友（左侧列表匹配 -> 滚动加载 -> 搜索框检索 -> 主页发私信直连兜底）
                target_name = friend.friend_nickname
                target_dy_id = friend.friend_dy_id
                active_page = page

                friend_item = self._find_friend(page, target_name, target_dy_id)
                if friend_item is not None:
                    try:
                        friend_item.click(timeout=4000)
                    except Exception:
                        page.evaluate("(el) => el.click()", friend_item.element_handle())
                    time.sleep(random.uniform(1.5, 2.5))
                else:
                    # 左侧列表中未定位到（常见于几天未聊天的 App 好友），尝试通过用户个人主页或搜索直连唤起私信会话
                    opened_page = self._open_user_profile_and_chat(page, context, target_name, target_dy_id)
                    if not opened_page:
                        waf_issue = self._check_waf_or_captcha(page)
                        for p in context.pages:
                            if not waf_issue:
                                waf_issue = self._check_waf_or_captcha(p)
                        if waf_issue:
                            return ExecutionResult(
                                False,
                                "页面被风控拦截",
                                waf_issue,
                                refreshed_cookies=_get_context_cookies(),
                            )
                        return ExecutionResult(
                            False,
                            "未找到好友",
                            f"在消息列表与用户主页均未定位到好友 {target_name} ({target_dy_id})，请确认好友是否在抖音私信列表中或抖音号/ID是否正确。",
                            refreshed_cookies=_get_context_cookies(),
                        )
                    active_page = opened_page

                # 3. 输入并发送消息：文本拟人打字，[火花] 占位符走表情面板直接发送（带自动文字兜底）
                input_box = self._find_input_box(active_page)
                if not input_box:
                    return ExecutionResult(
                        False,
                        "未找到输入框",
                        "无法定位到私信聊天输入框",
                        refreshed_cookies=_get_context_cookies(),
                    )

                segments = split_spark_content(content)
                pending_text: list[str] = []
                spark_count = 0
                fallback_spark_used = False

                for kind, value in segments:
                    if kind == "text" and value:
                        pending_text.append(value)
                        try:
                            input_box.click(timeout=2000)
                        except Exception:
                            pass
                        input_box.focus()
                        # 模拟真人输入
                        for char in value:
                            active_page.keyboard.type(char, delay=random.randint(40, 150))
                    elif kind == "spark":
                        # 先发送已打好的文字，保持消息顺序
                        if pending_text:
                            text_content = "".join(pending_text)
                            if not self._flush_text_message(active_page, input_box, text_content):
                                return ExecutionResult(
                                    False,
                                    "发送文本失败",
                                    f"已向 {target_name} 输入文本 {text_content!r} 但未能确认发送结果。",
                                    refreshed_cookies=_get_context_cookies(),
                                )
                            pending_text = []
                            time.sleep(random.uniform(0.8, 1.5))

                        ok, reason, used_fallback = self._send_spark_sticker(active_page, input_box)
                        if not ok:
                            return ExecutionResult(
                                False,
                                "发送火花表情失败",
                                reason,
                                refreshed_cookies=_get_context_cookies(),
                            )
                        spark_count += 1
                        if used_fallback:
                            fallback_spark_used = True

                if pending_text:
                    text_content = "".join(pending_text)
                    if not self._flush_text_message(active_page, input_box, text_content):
                        return ExecutionResult(
                            False,
                            "发送文本失败",
                            f"已向 {target_name} 输入文本 {text_content!r} 但未能确认发送结果。",
                            refreshed_cookies=_get_context_cookies(),
                        )

                # 4. 抓取浏览器当前上下文中的最新 Cookie，实现会话自动保活
                refreshed_cookies = _get_context_cookies()

                evidence = []
                if segments:
                    if any(kind == "spark" for kind, _ in segments):
                        if fallback_spark_used:
                            evidence.append(f"火花表情(已自动文字兜底)x{spark_count}")
                        else:
                            evidence.append(f"续火花表情x{spark_count}")
                    text_parts = "".join(v for k, v in segments if k == "text" and v)
                    if text_parts:
                        evidence.append(f"文本: {text_parts}")

                return ExecutionResult(
                    True,
                    "发送成功",
                    f"成功向 {target_name} 发送。{('；'.join(evidence)) if evidence else '消息已发送'}",
                    refreshed_cookies=refreshed_cookies,
                )

            except Exception as e:
                return ExecutionResult(
                    False,
                    "执行异常",
                    str(e),
                    refreshed_cookies=_get_context_cookies(),
                )
            finally:
                browser.close()


    def _check_waf_or_captcha(self, page: Page) -> str | None:
        """检查页面是否被 WAF 拦截、滑块验证码或页面空白。"""
        try:
            content = page.content()
            if len(content) < 500:
                return "检测到页面内容异常过短或空白，可能被抖音 WAF 安全风控拦截或网络慢。"

            captcha_selectors = (
                "#captcha_container",
                ".captcha-verify-image",
                ".captcha_verify_container",
                "[class*='captcha']",
                "[id*='captcha']",
                ".verify-bar",
                ".sec-captcha",
                "iframe[src*='captcha']",
            )
            for selector in captcha_selectors:
                loc = page.locator(selector).first
                if loc.count() and loc.is_visible():
                    return "检测到抖音安全验证码/滑块风控拦截，请人工在浏览器中完成验证或配置代理 IP。"
        except Exception:
            pass
        return None

    def _open_user_profile_and_chat(self, page: Page, context: Any, target_name: str, dy_id: str) -> Page | None:
        """多级兜底：如果最近会话列表中找不到好友，通过直连会话、个人主页或用户搜索唤起私信会话。

        支持处理 target='_blank' 产生的弹出新标签页。
        """
        if not dy_id and not target_name:
            return None

        chat_btn_selectors = [
            'button:has-text("私信")',
            'button:has-text("发私信")',
            'div[role="button"]:has-text("私信")',
            'div[role="button"]:has-text("发私信")',
            '[data-e2e="user-chat-button"]',
            '[data-e2e="user-info-chat"]',
            '[class*="chat-btn"]',
            '[class*="message-btn"]',
            '[class*="chatBtn"]',
            '[class*="msg-btn"]',
            '.semi-button:has-text("私信")',
        ]

        def _try_click_chat_button(target_page: Page) -> bool:
            self._dismiss_dialogs(target_page)
            for sel in chat_btn_selectors:
                try:
                    btn = target_page.locator(sel).first
                    if btn.count() and btn.is_visible():
                        btn.click(timeout=3000)
                        time.sleep(random.uniform(1.5, 2.5))
                        return True
                except Exception:
                    continue
            return False

        try:
            # 策略 A: 若 ID 是加密 sec_uid（以 MS4w 开头或超长串），优先直连 /chat 会话或个人主页
            if dy_id and (dy_id.startswith("MS4w") or len(dy_id) >= 20):
                # 尝试直连会话
                try:
                    direct_chat_url = f"https://www.douyin.com/chat?to_sec_uid={dy_id}"
                    page.goto(direct_chat_url, timeout=35000, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2.0, 3.0))
                    self._dismiss_dialogs(page)
                    if self._find_input_box(page):
                        return page
                except Exception:
                    pass

                # 尝试进入个人主页点击私信
                try:
                    user_url = f"https://www.douyin.com/user/{dy_id}"
                    page.goto(user_url, timeout=35000, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2.0, 3.5))
                    self._dismiss_dialogs(page)
                    _try_click_chat_button(page)
                    for p in context.pages:
                        if self._find_input_box(p):
                            return p
                except Exception:
                    pass

            # 策略 B: 尝试通过抖音全站用户搜索定位好友
            # 优先使用真实昵称搜索；若有自定义抖音号(非内部纯数字UID)也可作为备选
            search_candidates: list[str] = []
            if target_name:
                search_candidates.append(target_name)
            if dy_id and not dy_id.startswith("MS4w") and not (dy_id.isdigit() and len(dy_id) >= 10) and dy_id != target_name:
                search_candidates.append(dy_id)

            for search_query in search_candidates:
                clean_query = normalize_friend_name(search_query) or search_query.strip()
                if not clean_query:
                    continue
                search_url = f"https://www.douyin.com/search/{clean_query}?type=user"
                page.goto(search_url, timeout=35000, wait_until="domcontentloaded")
                time.sleep(random.uniform(2.5, 4.0))
                self._dismiss_dialogs(page)

                # 1. 尝试直接点击搜索卡片中的"私信"按钮
                if _try_click_chat_button(page):
                    for p in context.pages:
                        if self._find_input_box(p):
                            return p

                # 2. 尝试点击匹配的用户卡片进入主页
                norm_name = normalize_friend_name(target_name)
                candidate_locators = page.locator("[class*='user-info'], [class*='user-item'], [class*='search-result-card']").all()[:6]
                for candidate in candidate_locators:
                    try:
                        card_text = candidate.inner_text(timeout=1000) or ""
                        if target_name in card_text or (norm_name and norm_name in normalize_friend_name(card_text)):
                            page_count_before = len(context.pages)
                            candidate.click(timeout=3000)
                            time.sleep(2.5)

                            # 检查是否产生了新 Tab
                            active_tab = context.pages[-1] if len(context.pages) > page_count_before else page
                            self._dismiss_dialogs(active_tab)
                            _try_click_chat_button(active_tab)
                            for p in context.pages:
                                if self._find_input_box(p):
                                    return p
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    def _check_login_required(self, page: Page) -> bool:
        """检查页面是否出现了登录遮罩或登录表单。"""
        try:
            for marker in LOGIN_DIALOG_MARKERS:
                marker_loc = page.get_by_text(marker, exact=True).first
                if marker_loc.count() and marker_loc.is_visible():
                    return True
        except Exception:
            pass
        return False


    def _dismiss_dialogs(self, page: Page) -> None:
        """关闭非登录弹窗，绝不触碰登录弹窗。"""
        deadline = time.time() + 8
        while time.time() < deadline:
            dismissed = False
            for selector in DIALOG_SELECTORS:
                try:
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
                                close = dialog.locator('[aria-label="Close"], .semi-modal-close, [class*="close"]').first
                                if close.count() and close.is_visible():
                                    close.click(timeout=2000)
                                    dismissed = True
                        except Exception:
                            continue
                except Exception:
                    continue
            if not dismissed:
                return
            time.sleep(0.5)

    def _find_visible_match(self, page: Page, text: str) -> Locator | None:
        """优先精准匹配，其次模糊/包含匹配。"""
        if not text:
            return None
        # 1. 精准文本
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

        # 2. 归一化模糊匹配（处理特殊符号、备注括号、emoji）
        norm_target = normalize_friend_name(text)
        if norm_target and len(norm_target) >= 2:
            try:
                # 遍历消息列表项
                items = page.locator(
                    "[class*='user-item'], [class*='conversation'], [class*='chat-item'], [class*='session'], .semi-table-row"
                ).all()
                for item in items:
                    if not item.is_visible():
                        continue
                    item_text = item.inner_text(timeout=500) or ""
                    if text in item_text or norm_target in normalize_friend_name(item_text):
                        return item
            except Exception:
                pass

        return None

    def _clear_search_box(self, page: Page) -> None:
        """清空搜索框并恢复好友列表全量状态。"""
        for selector in SEARCH_SELECTORS:
            try:
                box = page.locator(selector).first
                if box.count() and box.is_visible():
                    box.click(timeout=1000)
                    page.keyboard.press("ControlOrMeta+A")
                    page.keyboard.press("Backspace")
                    box.fill("")
                    page.keyboard.press("Escape")
                    time.sleep(0.6)
                    return
            except Exception:
                continue

    def _try_search(self, page: Page, query: str) -> bool:
        """在私信搜索框中检索好友。"""
        if not query:
            return False
        clean_query = normalize_friend_name(query) or query.strip()
        if not clean_query:
            return False

        for selector in SEARCH_SELECTORS:
            box = page.locator(selector).first
            try:
                if box.count() and box.is_visible():
                    box.click(timeout=2000)
                    page.keyboard.press("ControlOrMeta+A")
                    page.keyboard.press("Backspace")
                    box.fill(clean_query)
                    page.keyboard.press("Enter")
                    time.sleep(1.8)
                    return True
            except Exception:
                continue
        return False

    def _scroll_friend_list(self, page: Page) -> None:
        """精准滚动左侧联系人列表区域。"""
        try:
            # 1. 尝试直接给列表容器滚动
            for selector in CONTACT_CONTAINER_SELECTORS:
                container = page.locator(selector).first
                if container.count() and container.is_visible():
                    page.evaluate("(el) => el.scrollTop += 500", container.element_handle())
                    return
        except Exception:
            pass

        # 2. 坐标滚轮兜底（左侧列表通常在 x: 180 处）
        try:
            page.mouse.move(180, 400)
            page.mouse.wheel(0, 500)
        except Exception:
            pass

    def _find_friend(self, page: Page, name: str, dy_id: str) -> Locator | None:
        """多策略定位好友：
        1. 当前可视区域查找
        2. 滚动好友列表查找
        3. 搜索框检索昵称查找（失败后自动清空搜索框）
        4. 搜索框检索 ID 查找（非加密长串才搜）
        5. 刷新重试
        """
        deadline = time.time() + FRIEND_FIND_DEADLINE_SECONDS
        searched = False
        scrolled_rounds = 0

        while time.time() < deadline:
            # 策略 1: 可视区域直接匹配
            match = self._find_visible_match(page, name)
            if match:
                return match

            # 策略 2: 滚动左侧列表
            if scrolled_rounds < 8:
                self._scroll_friend_list(page)
                scrolled_rounds += 1
                time.sleep(0.5)
                continue

            # 策略 3: 使用昵称搜索
            if not searched:
                # 提取纯净昵称搜索
                search_term = normalize_friend_name(name) or name.strip()
                if search_term and self._try_search(page, search_term):
                    match = self._find_visible_match(page, name)
                    if match:
                        return match
                    # 搜索后未找到，必须清空搜索框以恢复列表
                    self._clear_search_box(page)

                # 策略 4: 如果 ID 看起来是正常抖音号（不是加密长串），尝试用 ID 搜
                if dy_id and not dy_id.startswith("MS4w") and len(dy_id) < 30 and dy_id != name:
                    if self._try_search(page, dy_id):
                        match = self._find_visible_match(page, name) or self._find_visible_match(page, dy_id)
                        if match:
                            return match
                        self._clear_search_box(page)

                searched = True
                continue

            # 最后一轮：重新加载页面兜底
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
                try:
                    loc = page.locator(selector).first
                    if loc.count() and loc.is_visible():
                        return loc
                except Exception:
                    continue
            time.sleep(0.6)
        return None

    def _flush_text_message(self, page: Page, input_box: Locator, content: str) -> bool:
        """发送已输入到输入框的文本（回车 + 点击发送按钮 + 智能取证）。"""
        time.sleep(random.uniform(0.4, 0.8))
        # 1. 回车触发
        page.keyboard.press("Enter")
        time.sleep(0.6)

        # 2. 发送按钮兜底触发
        for selector in SEND_BUTTON_SELECTORS:
            try:
                btn = page.locator(selector).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=1500)
                    break
            except Exception:
                continue

        time.sleep(1.2)
        verified, _ = self._verify_message_sent(page, input_box, content)
        return verified

    def _send_spark_sticker(self, page: Page, input_box: Locator) -> tuple[bool, str, bool]:
        """打开输入框旁的表情面板，点击续火花表情；如果表情面板未找到，自动降级为文字表情兜底发送。

        返回 (成功与否, 结果说明, 是否使用了文字兜底)
        """
        button = self._find_emoji_button(page)
        if button is None:
            # 按钮未定位到，降级文字兜底
            return self._fallback_spark_text(page, input_box, "未定位到表情按钮")

        try:
            button.click(timeout=2500)
        except Exception:
            try:
                page.evaluate("(el) => el.click()", button.element_handle())
            except Exception:
                return self._fallback_spark_text(page, input_box, "点击表情按钮失败")

        time.sleep(0.8)
        item = self._find_spark_item(page)
        if item is None:
            # 表情面板里没有火花（如火花断掉或改版），降级文字兜底
            # 尝试关闭表情面板
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return self._fallback_spark_text(page, input_box, "表情面板未找到火花表情")

        baseline = self._count_message_emojis(page)
        try:
            item.click(timeout=3000)
        except Exception:
            try:
                page.evaluate("(el) => el.click()", item.element_handle())
            except Exception:
                return self._fallback_spark_text(page, input_box, "点击火花表情失败")

        deadline = time.time() + 8
        while time.time() < deadline:
            if self._count_message_emojis(page) > baseline:
                return True, "已确认发送续火花专属表情包。", False
            time.sleep(0.6)

        # 超时未确认表情包增量，为保证续火花成功，走文字表情补充兜底
        return self._fallback_spark_text(page, input_box, "火花表情发送确认超时")

    def _fallback_spark_text(self, page: Page, input_box: Locator, original_reason: str) -> tuple[bool, str, bool]:
        """表情包发送受阻时的安全保底方案：向输入框发送 🔥 符号及续火花文本。"""
        fallback_msg = "🔥"
        try:
            input_box.click(timeout=1500)
            input_box.focus()
            for char in fallback_msg:
                page.keyboard.type(char, delay=random.randint(30, 80))
            page.keyboard.press("Enter")
            time.sleep(1.0)
            for selector in SEND_BUTTON_SELECTORS:
                try:
                    btn = page.locator(selector).first
                    if btn.count() and btn.is_visible():
                        btn.click(timeout=1000)
                        break
                except Exception:
                    continue
            return True, f"{original_reason}，已自动以 🔥 表情字符兜底发送成功。", True
        except Exception as exc:
            return False, f"{original_reason}，且文字兜底发送失败: {exc}", True

    def _find_emoji_button(self, page: Page) -> Locator | None:
        deadline = time.time() + EMOJI_PANEL_WAIT_SECONDS
        while time.time() < deadline:
            for selector in EMOJI_BUTTON_SELECTORS:
                try:
                    for candidate in page.locator(selector).all():
                        if candidate.is_visible():
                            return candidate
                except Exception:
                    continue
            time.sleep(0.4)
        return None

    def _find_spark_item(self, page: Page) -> Locator | None:
        deadline = time.time() + EMOJI_PANEL_WAIT_SECONDS
        while time.time() < deadline:
            try:
                for item in page.locator(".emojiEmojiItememojiItem").all():
                    try:
                        if not item.is_visible():
                            continue
                        desc = item.locator(".emojiEmojiItememojiItemDesc").inner_text(timeout=500) or ""
                        if "火花" in desc:
                            return item
                    except Exception:
                        continue
            except Exception:
                pass

            for selector in SPARK_ITEM_SELECTORS:
                try:
                    for candidate in page.locator(selector).all():
                        if candidate.is_visible():
                            return candidate
                except Exception:
                    continue
            time.sleep(0.4)
        return None

    def _count_message_emojis(self, page: Page) -> int:
        """统计聊天区已发表情（.MessageItemEmojiimage 等），用于确认表情是否发出。"""
        total = 0
        try:
            total += page.locator(".MessageItemEmojiimage, [class*='message-emoji'], [class*='emoji-sticker']").count()
        except Exception:
            pass
        return total

    def _verify_message_sent(self, page: Page, input_box: Locator, content: str) -> tuple[bool, str]:
        normalized_content = content.strip()
        if not normalized_content:
            return True, "内容为空"

        deadline = time.time() + 6
        latest_reason = "等待页面回写发送结果。"

        while time.time() < deadline:
            input_cleared = self._is_input_cleared(input_box, normalized_content)
            message_visible = self._is_message_visible(page, normalized_content)

            if input_cleared or message_visible:
                return True, "已确认消息发送成功。"

            time.sleep(0.6)

        # 宽容判定：若输入框已清空且未报错，通常已完成发送
        if self._is_input_cleared(input_box, normalized_content):
            return True, "输入框已清空，判定发送完成。"

        return False, latest_reason

    def _is_input_cleared(self, input_box: Locator, content: str) -> bool:
        try:
            if input_box.count() == 0:
                return True
        except Exception:
            return True

        candidates: list[str] = []
        try:
            raw_text = input_box.text_content(timeout=800) or ""
            candidates.append(raw_text.strip())
        except Exception:
            pass

        try:
            inner_text = input_box.inner_text(timeout=800) or ""
            candidates.append(inner_text.strip())
        except Exception:
            pass

        try:
            input_value = input_box.input_value(timeout=800) or ""
            candidates.append(input_value.strip())
        except Exception:
            pass

        if not candidates:
            return True

        normalized_content = content.strip()
        return all(candidate == "" or candidate != normalized_content for candidate in candidates)

    def _is_message_visible(self, page: Page, content: str) -> bool:
        for selector in MESSAGE_CONTENT_SELECTORS:
            try:
                locator = page.locator(selector).get_by_text(content, exact=False).first
                if locator.is_visible(timeout=800):
                    return True
            except Exception:
                pass

        try:
            locator = page.get_by_text(content, exact=False).first
            return locator.is_visible(timeout=800)
        except Exception:
            return False

    def _parse_cookies(self, cookie_text: str) -> list[dict]:
        """解析 Cookie 字符串或 JSON 数据为 Playwright 格式。"""
        stripped = cookie_text.strip()
        if stripped.lower().startswith("cookie:"):
            stripped = stripped[7:].strip()

        try:
            data = json.loads(stripped)
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if "cookies" in data and isinstance(data["cookies"], list):
                    items = data["cookies"]
                else:
                    items = [{"name": k, "value": str(v), "domain": ".douyin.com", "path": "/"} for k, v in data.items()]

            if items:
                clean_cookies = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    val = str(item.get("value", "")).strip()
                    if not name or not val:
                        continue
                    domain = str(item.get("domain", "")).strip()
                    if not domain or "douyin.com" in domain:
                        domain = ".douyin.com"

                    c = {
                        "name": name,
                        "value": val,
                        "domain": domain,
                        "path": "/",
                    }
                    same_site = str(item.get("sameSite", "")).strip().lower()
                    if same_site in ("strict",):
                        c["sameSite"] = "Strict"
                    elif same_site in ("lax", "unspecified"):
                        c["sameSite"] = "Lax"
                    elif same_site in ("none", "no_restriction"):
                        c["sameSite"] = "None"

                    if "expires" in item and isinstance(item["expires"], (int, float)) and item["expires"] > 0:
                        c["expires"] = item["expires"]
                    c["secure"] = item.get("secure", True) if isinstance(item.get("secure"), bool) else True
                    clean_cookies.append(c)
                if clean_cookies:
                    return clean_cookies
        except Exception:
            pass

        cookies = []
        for part in stripped.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name_clean = name.strip()
            val_clean = value.strip()
            if name_clean and val_clean:
                cookies.append({
                    "name": name_clean,
                    "value": val_clean,
                    "domain": ".douyin.com",
                    "path": "/",
                    "secure": True,
                })
        return cookies


execution_service = ExecutionService()
