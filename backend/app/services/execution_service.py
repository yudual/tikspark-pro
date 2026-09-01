from __future__ import annotations

import base64
import gc
import json
import logging
import math
import os
import random
import re
import shutil
import time
from typing import Any, NamedTuple

from playwright.sync_api import Locator, Page, Response, sync_playwright

from ..models import Account, Friend
from .secret_service import get_secret_service

logger = logging.getLogger(__name__)

CREATOR_CHAT_URL = "https://creator.douyin.com/creator-micro/data/following/chat"
CONSUMER_CHAT_URL = "https://www.douyin.com/chat"

LOGIN_DIALOG_MARKERS = ("扫码登录", "验证码登录", "登录/注册", "密码登录", "请先登录")
DISMISS_BUTTON_TEXTS = ("取消", "暂不", "知道了", "关闭", "稍后再说", "继续逛逛", "暂不开启", "我知道了", "好的", "确定", "确认")
DIALOG_SELECTORS = (".semi-modal-content", '[role="dialog"]', ".semi-toast", '[class*="modal"]', ".semi-modal-wrap")

INPUT_SELECTORS = (
    'div[contenteditable="true"]',
    '[role="textbox"]',
    "textarea",
    ".chat-input",
    "[class*='chat-input']",
    "[class*='editor-input']",
    "[class*='message-editor']",
    "[class*='chatInput']",
    "[class*='msg-input']",
    "#sub-app div[contenteditable='true']",
)

SEND_BUTTON_SELECTORS = (
    'button:has-text("发送")',
    '[data-e2e*="send"]',
    '[class*="send-btn"]',
    '[class*="sendBtn"]',
    '[class*="send_btn"]',
    '.semi-button-primary:has-text("发送")',
    'button[type="submit"]',
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
    '[class*="emoji_btn"]',
    '#sub-app [class*="emoji"]',
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
    '[class*="emoji-item"] img[src*="huohua"]',
    '[class*="emojiItem"]',
)

FRIEND_ROW_SELECTORS = (
    '#sub-app li[role="listitem"]:has([class*="item-header-name-"])',
    '#sub-app li.semi-list-item:has([class*="item-header-name-"])',
    '#sub-app li[role="listitem"]',
    '#sub-app li.semi-list-item',
    'xpath=//*[@id="sub-app"]//div[contains(@class, "semi-list-item-body")]',
    "[class*='user-item']",
    "[class*='conversation-item']",
    "[class*='chat-item']",
    "[class*='session-item']",
    ".semi-table-row",
)

SCROLLABLE_FRIENDS_SELECTORS = (
    '#sub-app [role="grid"]',
    '#sub-app .ReactVirtualized__Grid',
    '#sub-app [class*="semi-list"] ul',
    '#sub-app ul > div',
    'xpath=//*[@id="sub-app"]/div/div[1]/div[2]/div[2]/div/div/div[3]/div/div/div/ul/div',
    'xpath=//*[@id="sub-app"]//ul/div',
    'xpath=//*[@id="sub-app"]//div[contains(@class, "semi-list")]//ul/..',
    '[class*="session-list"]',
    '[class*="contact-list"]',
    '[class*="chat-list"]',
)

SPARK_STICKER_TOKEN = "[火花]"

PLAYWRIGHT_STEALTH_SCRIPT = """
(() => {
    try {
        // 1. 隐藏 webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });

        // 2. 伪装 platform 为 Win32，与 User-Agent 保持一致（防止 Linux 暴露）
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32',
        });

        // 3. 伪装硬件特征
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8,
        });
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8,
        });
        Object.defineProperty(navigator, 'vendor', {
            get: () => 'Google Inc.',
        });

        // 4. 伪装 WebGL 渲染器（防止暴露 Google SwiftShader / Mesa）
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) {
                return 'Google Inc. (NVIDIA)';
            }
            if (parameter === 37446) {
                return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            }
            return getParameter.apply(this, arguments);
        };
        if (typeof WebGL2RenderingContext !== 'undefined') {
            const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) {
                    return 'Google Inc. (NVIDIA)';
                }
                if (parameter === 37446) {
                    return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                }
                return getParameter2.apply(this, arguments);
            };
        }

        // 5. 伪装 window.chrome
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

        // 6. 伪装语言与插件
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


def get_browser_executable_path() -> str | None:
    for path in ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]:
        if os.path.exists(path):
            return path
    return shutil.which("google-chrome-stable") or shutil.which("google-chrome") or shutil.which("chromium")


def normalize_friend_name(name: str | None) -> str:
    """去除特殊符号、空格、emoji，以便进行容错模糊匹配。"""
    if not name:
        return ""
    # 去除括号备注部分，如 "张三 (同事)" -> "张三"
    cleaned = re.sub(r"[\(（\[【].*?[\)）\]】]", "", name)
    # 去除空白与标点
    cleaned = re.sub(r"[\s\-_@#\$%^&*\+=\|:;\"'<>,.?/~`！￥…—\u200b\u200c\u200d\ufeff\xa0]+", "", cleaned)
    # 去除常见 emoji 编码段
    cleaned = re.sub(r"[\U00010000-\U0010ffff\uD800-\uDBFF\uDC00-\uDFFF\u2600-\u27BF]", "", cleaned)
    return cleaned.strip().casefold()


def split_spark_content(content: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    remainder = content or ""
    while remainder:
        index = remainder.find(SPARK_STICKER_TOKEN)
        if index == -1:
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
    def _parse_cookies(self, cookie_text: str) -> list[dict[str, Any]]:
        cookies: list[dict[str, Any]] = []
        clean = (cookie_text or "").strip()
        if not clean:
            return cookies

        try:
            parsed = json.loads(clean)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("name") and item.get("value") is not None:
                        c = {"name": str(item["name"]).strip(), "value": str(item["value"]).strip()}
                        domain = str(item.get("domain", "")).strip()
                        c["domain"] = domain if domain else ".douyin.com"
                        c["path"] = str(item.get("path", "/")).strip() or "/"
                        if item.get("sameSite") in ("Strict", "Lax", "None"):
                            c["sameSite"] = item["sameSite"]
                        if isinstance(item.get("secure"), bool):
                            c["secure"] = item["secure"]
                        if isinstance(item.get("expires"), (int, float)) and item["expires"] > 0:
                            c["expires"] = item["expires"]
                        cookies.append(c)
                if cookies:
                    return cookies
        except Exception:
            pass

        if clean.lower().startswith("cookie:"):
            clean = clean[7:].strip()
        for part in clean.split(";"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            name = k.strip()
            value = v.strip()
            if name:
                cookies.append({"name": name, "value": value, "domain": ".douyin.com", "path": "/"})
        return cookies

    def _dismiss_dialogs(self, page: Page) -> int:
        """关闭非登录弹窗，绝不触碰登录弹窗。"""
        dismissed_count = 0
        for _ in range(3):
            action_taken = False
            for selector in DIALOG_SELECTORS:
                try:
                    for dialog in page.locator(selector).all():
                        try:
                            if not dialog.is_visible():
                                continue
                            text = (dialog.inner_text(timeout=500) or "").replace("\n", " ")
                            if any(marker in text for marker in LOGIN_DIALOG_MARKERS):
                                continue
                            clicked = False
                            for button_text in DISMISS_BUTTON_TEXTS:
                                button = dialog.get_by_text(button_text, exact=True).first
                                if button.count() and button.is_visible():
                                    button.click(timeout=1000)
                                    clicked = True
                                    action_taken = True
                                    dismissed_count += 1
                                    break
                            if not clicked:
                                close = dialog.locator('[aria-label="Close"], .semi-modal-close, [class*="close"]').first
                                if close.count() and close.is_visible():
                                    close.click(timeout=1000)
                                    action_taken = True
                                    dismissed_count += 1
                        except Exception:
                            continue
                except Exception:
                    continue
            if not action_taken:
                break
            time.sleep(0.3)
        return dismissed_count

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

    def _is_captcha_page(self, page: Page) -> bool:
        try:
            title = (page.title() or "").strip()
            if "验证码" in title or "安全验证" in title or "中间页" in title:
                return True
            for frame in page.frames:
                if not frame.url or frame.url == "about:blank":
                    continue
                if any(k in frame.url for k in ("verifycenter/captcha", "rmc.bytedance.com")):
                    return True
            for sel in ("#captcha_container", ".captcha-verify-image", "#captcha_verify_image", ".captcha_verify_container"):
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    return True
        except Exception:
            pass
        return False

    def _try_solve_slider_captcha(self, page: Page) -> bool:
        # 轻量化尝试，若无验证码直接返回
        if not self._is_captcha_page(page):
            return True
        return False

    def _check_waf_or_captcha(self, page: Page) -> str | None:
        try:
            if self._is_captcha_page(page):
                return "检测到抖音安全验证码/滑块风控拦截，请人工在浏览器中完成验证或配置代理 IP。"
            content = page.content()
            if len(content) < 400:
                return "检测到页面内容异常过短或空白，可能被抖音 WAF 安全风控拦截或网络慢。"
        except Exception:
            pass
        return None

    def _open_creator_friends_tab(self, page: Page) -> bool:
        """在创作者中心私信页面打开【好友/互关】选项卡。"""
        self._dismiss_dialogs(page)
        sub_app = page.locator('#sub-app')
        candidates = [
            page.get_by_text("朋友私信", exact=True),
            page.get_by_text("好友私信", exact=True),
            sub_app.get_by_text("朋友", exact=True),
            sub_app.get_by_text("好友", exact=True),
            sub_app.get_by_text("互关", exact=True),
            page.locator('xpath=//*[@id="sub-app"]/div/div/div[1]/div[2]'),
            page.locator('xpath=//*[@id="sub-app"]//*[contains(text(), "好友") or contains(text(), "互关") or contains(text(), "朋友")]'),
        ]
        for candidate in candidates:
            try:
                first_item = candidate.first
                if first_item.count() and first_item.is_visible():
                    first_item.click(timeout=2000)
                    time.sleep(1.0)
                    return True
            except Exception:
                continue
        return False

    def _find_friend_in_creator_or_chat(self, page: Page, name: str, dy_id: str, sec_uid: str = "") -> Locator | None:
        """在页面联系人列表中通过精准文本、归一化模糊匹配定位好友行。"""
        if not name and not dy_id and not sec_uid:
            return None

        norm_name = normalize_friend_name(name)
        norm_dy_id = normalize_friend_name(dy_id)

        # 1. 尝试直接点击已可见好友项
        deadline = time.time() + 25
        scrolled_rounds = 0

        while time.time() < deadline:
            # 尝试各种好友项选择器
            for row_sel in FRIEND_ROW_SELECTORS:
                try:
                    for item in page.locator(row_sel).all():
                        if not item.is_visible():
                            continue
                        item_text = (item.inner_text(timeout=300) or "").strip()
                        if not item_text:
                            continue
                        norm_item_text = normalize_friend_name(item_text)
                        # 精准匹配或归一化包含
                        if (name and name in item_text) or (norm_name and norm_name in norm_item_text) or (norm_dy_id and norm_dy_id in norm_item_text):
                            return item
                except Exception:
                    continue

            # 滚动联系人列表以加载更多
            if scrolled_rounds < 12:
                scrolled = False
                for scroll_sel in SCROLLABLE_FRIENDS_SELECTORS:
                    try:
                        container = page.locator(scroll_sel).first
                        if container.count() and container.is_visible():
                            page.evaluate("(el) => el.scrollTop += 600", container.element_handle())
                            scrolled = True
                            break
                    except Exception:
                        continue
                if not scrolled:
                    try:
                        page.mouse.move(180, 400)
                        page.mouse.wheel(0, 500)
                    except Exception:
                        pass
                scrolled_rounds += 1
                time.sleep(0.6)
            else:
                break

        return None

    def _find_friend(self, page: Page, name: str, dy_id: str, sec_uid: str = "") -> Locator | None:
        return self._find_friend_in_creator_or_chat(page, name, dy_id, sec_uid)

    def _find_visible_match(self, page: Page, text: str) -> Locator | None:
        if not text:
            return None
        try:
            loc = page.get_by_text(text, exact=True).first
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            pass
        return None

    def _clear_search_box(self, page: Page) -> None:
        pass

    def _try_search(self, page: Page, query: str) -> bool:
        return False

    def _scroll_friend_list(self, page: Page) -> None:
        for scroll_sel in SCROLLABLE_FRIENDS_SELECTORS:
            try:
                container = page.locator(scroll_sel).first
                if container.count() and container.is_visible():
                    page.evaluate("(el) => el.scrollTop += 500", container.element_handle())
                    return
            except Exception:
                continue

    def _open_user_profile_and_chat(
        self, page: Page, context: Any, target_name: str, dy_id: str, sec_uid: str = ""
    ) -> Page | None:
        """通过 sec_uid 直达会话或个人主页唤起私信。"""
        effective_sec_uid = (sec_uid or "").strip()
        if not effective_sec_uid and dy_id and (dy_id.startswith("MS4w") or len(dy_id) >= 20):
            effective_sec_uid = dy_id.strip()

        if effective_sec_uid:
            try:
                direct_url = f"https://www.douyin.com/chat?to_sec_uid={effective_sec_uid}"
                page.goto(direct_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2.0)
                self._dismiss_dialogs(page)
                if self._find_input_box(page):
                    return page
            except Exception:
                pass

        return None

    def _find_input_box(self, page: Page) -> Locator | None:
        deadline = time.time() + 10
        while time.time() < deadline:
            for selector in INPUT_SELECTORS:
                try:
                    loc = page.locator(selector).first
                    if loc.count() and loc.is_visible():
                        return loc
                except Exception:
                    continue
            time.sleep(0.5)
        return None

    def _find_emoji_button(self, page: Page) -> Locator | None:
        for selector in EMOJI_BUTTON_SELECTORS:
            try:
                loc = page.locator(selector).first
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    def _find_spark_item(self, page: Page) -> Locator | None:
        for selector in SPARK_ITEM_SELECTORS:
            try:
                for item in page.locator(selector).all():
                    if item.is_visible():
                        return item
            except Exception:
                continue
        return None

    def _is_input_cleared(self, input_box: Locator, original_text: str) -> bool:
        try:
            curr = (input_box.inner_text(timeout=300) or "").strip()
            return original_text not in curr
        except Exception:
            return True

    def _is_message_visible(self, page: Page, text: str) -> bool:
        try:
            loc = page.get_by_text(text, exact=False).first
            return bool(loc.count() and loc.is_visible())
        except Exception:
            return False

    def _detect_send_failure(self, page: Page) -> str:
        fail_markers = [
            "发送失败",
            "未成功发送",
            "由于对方的隐私设置",
            "你已被对方拉黑",
            "请先关注对方",
            "请先添加对方为好友",
            "发送频繁",
            "发送受限",
            "账号异常",
            "请进行安全验证",
            "操作过于频繁",
        ]
        try:
            for marker in fail_markers:
                loc = page.get_by_text(marker, exact=False).first
                if loc.count() and loc.is_visible():
                    return f"系统提示：{marker}"
        except Exception:
            pass
        return ""

    def _get_outgoing_message_count(self, page: Page) -> int:
        selectors = [
            "[class*='box-item-'][class*='is-me']",
            "[class*='message-send']",
            "[class*='message-right']",
            "[class*='message_right']",
            "[class*='message-self']",
            "[class*='messageSelf']",
            "[class*='self-message']",
        ]
        for sel in selectors:
            try:
                cnt = page.locator(sel).count()
                if cnt > 0:
                    return cnt
            except Exception:
                continue
        return 0

    def _type_into_input_box(self, page: Page, input_box: Locator, text: str) -> tuple[bool, str]:
        if not text:
            return True, ""
        try:
            input_box.click(timeout=1500)
            input_box.focus()
            for char in text:
                page.keyboard.type(char, delay=random.randint(20, 60))
        except Exception:
            pass

        time.sleep(0.3)
        current_text = ""
        try:
            current_text = page.evaluate("(el) => (el.innerText || el.textContent || el.value || '').trim()", input_box.element_handle())
        except Exception:
            pass

        if text in current_text or (current_text and len(current_text) > 0):
            return True, ""

        # DOM 写入兜底
        try:
            page.evaluate(
                """([el, val]) => {
                el.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, val);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
                [input_box.element_handle(), text],
            )
            time.sleep(0.3)
            current_text = page.evaluate("(el) => (el.innerText || el.textContent || el.value || '').trim()", input_box.element_handle())
            if current_text:
                return True, ""
        except Exception as exc:
            return False, f"输入框写入异常: {exc}"

        return False, "未能将文字写入抖音输入框"

    def _flush_text_message(
        self, page: Page, input_box: Locator, content: str, send_receipt: dict[str, Any]
    ) -> tuple[bool, str]:
        """发送文本消息，结合网络层响应回执与 DOM 进行严格递交确认。"""
        send_receipt["seen"] = False
        send_receipt["ok"] = False
        send_receipt["error"] = ""

        typed_ok, err = self._type_into_input_box(page, input_box, content)
        if not typed_ok:
            return False, err

        time.sleep(random.uniform(0.3, 0.6))
        page.keyboard.press("Enter")
        time.sleep(0.4)

        for selector in SEND_BUTTON_SELECTORS:
            try:
                btn = page.locator(selector).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=1000)
                    break
            except Exception:
                continue

        # 等待网络回执与状态
        deadline = time.time() + 6
        while time.time() < deadline:
            time.sleep(0.6)
            fail_reason = self._detect_send_failure(page)
            if fail_reason:
                return False, fail_reason

            if send_receipt.get("seen"):
                if send_receipt.get("ok"):
                    return True, "已获得抖音服务端发信成功回执。"
                return False, f"抖音接口返回发送失败: {send_receipt.get('error', '未知原因')}"

            if self._is_input_cleared(input_box, content):
                # 输入框已被清空且无报错
                time.sleep(0.8)
                if send_receipt.get("ok") or not self._detect_send_failure(page):
                    return True, "消息已提交并清空输入框。"

        if send_receipt.get("seen") and not send_receipt.get("ok"):
            return False, f"抖音发信接口报错: {send_receipt.get('error')}"

        fail_reason = self._detect_send_failure(page)
        if fail_reason:
            return False, fail_reason

        # 检查输入框是否清空
        if self._is_input_cleared(input_box, content):
            return True, "消息已提交并清空输入框。"

        return False, f"向输入框提交文本 {content!r} 后未能确认发出，请确认账号私信状态。"

    def _send_spark_sticker(
        self, page: Page, input_box: Locator, send_receipt: dict[str, Any]
    ) -> tuple[bool, str, bool]:
        """打开表情面板点击续火花表情，结合网络层回执与 🔥 符号兜底。"""
        send_receipt["seen"] = False
        send_receipt["ok"] = False
        button = self._find_emoji_button(page)

        if button is not None:
            try:
                button.click(timeout=1500)
            except Exception:
                try:
                    page.evaluate("(el) => el.click()", button.element_handle())
                except Exception:
                    pass

            time.sleep(0.6)
            item = self._find_spark_item(page)
            if item is not None:
                try:
                    item.click(timeout=2000)
                except Exception:
                    try:
                        page.evaluate("(el) => el.click()", item.element_handle())
                    except Exception:
                        pass

                deadline = time.time() + 5
                while time.time() < deadline:
                    time.sleep(0.5)
                    fail_reason = self._detect_send_failure(page)
                    if fail_reason:
                        return False, fail_reason, False
                    if send_receipt.get("seen") and send_receipt.get("ok"):
                        return True, "已确认发送续火花专属表情包（已获得服务端确认）。", False

            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

        # 表情未发出，严格以 🔥 字符兜底
        fallback_ok, reason = self._flush_text_message(page, input_box, "🔥", send_receipt)
        if fallback_ok:
            return True, "已自动以 🔥 表情字符兜底发送并确认成功。", True
        return False, reason, False

    def send_message(self, account: Account, friend: Friend, content: str) -> ExecutionResult:
        if not account.cookie_text:
            return ExecutionResult(False, "缺少凭证", "账号没有配置 Cookie 凭证")

        try:
            cookie_text = get_secret_service().decrypt(account.cookie_text)
        except ValueError as exc:
            return ExecutionResult(False, "凭证解密失败", str(exc))

        cookies = self._parse_cookies(cookie_text)
        if not cookies:
            return ExecutionResult(False, "凭证无效", "未能解析到有效 Cookie")

        # 网络层消息回执捕获器
        send_receipt: dict[str, Any] = {
            "seen": False,
            "ok": False,
            "status_code": None,
            "error": "",
            "server_msg_id": "",
        }

        # 小鸡弱 VPS 极端低资源浏览器参数
        browser_args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-renderer-backgrounding",
            "--window-size=1280,800",
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

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            context.add_init_script(PLAYWRIGHT_STEALTH_SCRIPT)
            context.add_cookies(cookies)
            page = context.new_page()
            page.set_default_navigation_timeout(40000)
            page.set_default_timeout(20000)

            def _handle_response(resp: Response) -> None:
                try:
                    url = resp.url
                    if "/v1/message/send" in url or "imapi.douyin.com" in url or "/web/im/" in url:
                        if resp.status == 200:
                            data = resp.json()
                            status_code = data.get("status_code", data.get("err_no", data.get("code")))
                            if status_code in (0, "0", None) and (data.get("server_message_id") or data.get("data") or data.get("msg_id")):
                                send_receipt["seen"] = True
                                send_receipt["ok"] = True
                                send_receipt["status_code"] = 0
                            else:
                                send_receipt["seen"] = True
                                send_receipt["ok"] = False
                                send_receipt["error"] = str(data.get("status_msg") or data.get("message") or f"状态码: {status_code}")
                except Exception:
                    pass

            page.on("response", _handle_response)

            def _get_context_cookies() -> str | None:
                try:
                    c = context.cookies()
                    if c:
                        return json.dumps(c, ensure_ascii=False)
                except Exception:
                    pass
                return None

            try:
                # 1. 优先访问创作者平台私信页面（包含互关好友全量列表，不易触发消费端搜索风控）
                target_name = friend.friend_nickname
                target_dy_id = friend.friend_dy_id
                target_sec_uid = getattr(friend, "sec_uid", "") or ""
                if not target_sec_uid and target_dy_id and (target_dy_id.startswith("MS4w") or len(target_dy_id) >= 20):
                    target_sec_uid = target_dy_id

                active_page = page
                opened = False

                # 尝试 A: 访问创作者中心
                try:
                    page.goto(CREATOR_CHAT_URL, timeout=35000, wait_until="domcontentloaded")
                    time.sleep(2.0)
                    self._dismiss_dialogs(page)

                    if not self._check_login_required(page):
                        # 打开【好友/互关】Tab
                        self._open_creator_friends_tab(page)
                        friend_item = self._find_friend_in_creator_or_chat(page, target_name, target_dy_id, target_sec_uid)
                        if friend_item is not None:
                            try:
                                friend_item.click(timeout=3000)
                            except Exception:
                                page.evaluate("(el) => el.click()", friend_item.element_handle())
                            time.sleep(1.5)
                            opened = True
                except Exception:
                    pass

                # 尝试 B: 若创作者中心未打开，fallback 访问消费端私信主页
                if not opened:
                    try:
                        fallback_chat_url = CONSUMER_CHAT_URL
                        if target_sec_uid:
                            fallback_chat_url = f"{CONSUMER_CHAT_URL}?to_sec_uid={target_sec_uid}"
                        page.goto(fallback_chat_url, timeout=35000, wait_until="domcontentloaded")
                        time.sleep(2.0)
                        self._dismiss_dialogs(page)

                        if self._check_login_required(page):
                            return ExecutionResult(
                                False,
                                "账号凭证已失效",
                                "检测到抖音网页弹出登录对话框，Cookie 凭证已过期或被风控失效，请重新获取并更新 Cookie。",
                                refreshed_cookies=_get_context_cookies(),
                            )

                        waf_issue = self._check_waf_or_captcha(page)
                        if waf_issue:
                            return ExecutionResult(False, "页面被风控拦截", waf_issue, refreshed_cookies=_get_context_cookies())

                        friend_item = self._find_friend_in_creator_or_chat(page, target_name, target_dy_id, target_sec_uid)
                        if friend_item is not None:
                            try:
                                friend_item.click(timeout=3000)
                            except Exception:
                                page.evaluate("(el) => el.click()", friend_item.element_handle())
                            time.sleep(1.5)
                            opened = True
                        elif self._find_input_box(page):
                            opened = True
                    except Exception as e:
                        logger.warning("Consumer chat navigation failed: %s", e)

                if not opened and not self._find_input_box(page):
                    return ExecutionResult(
                        False,
                        "未找到好友",
                        f"在创作者中心与私信列表中均未定位到好友 {target_name} ({target_dy_id})，请确认该好友是否在互关列表中。",
                        refreshed_cookies=_get_context_cookies(),
                    )

                # 2. 定位输入框
                input_box = self._find_input_box(active_page)
                if not input_box:
                    return ExecutionResult(
                        False,
                        "未找到输入框",
                        "无法定位到私信聊天输入框",
                        refreshed_cookies=_get_context_cookies(),
                    )

                # 3. 逐段发送文本与表情
                segments = split_spark_content(content)
                pending_text: list[str] = []
                spark_count = 0
                fallback_spark_used = False

                for kind, value in segments:
                    if kind == "text" and value:
                        pending_text.append(value)
                        try:
                            input_box.click(timeout=1500)
                        except Exception:
                            pass
                        for char in value:
                            active_page.keyboard.type(char, delay=random.randint(20, 60))
                    elif kind == "spark":
                        if pending_text:
                            text_content = "".join(pending_text)
                            flush_ok, flush_err = self._flush_text_message(active_page, input_box, text_content, send_receipt)
                            if not flush_ok:
                                return ExecutionResult(
                                    False,
                                    "发送文本失败",
                                    f"向 {target_name} 发送文本失败: {flush_err}",
                                    refreshed_cookies=_get_context_cookies(),
                                )
                            pending_text = []
                            time.sleep(random.uniform(0.5, 1.0))

                        ok, reason, used_fallback = self._send_spark_sticker(active_page, input_box, send_receipt)
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
                    flush_ok, flush_err = self._flush_text_message(active_page, input_box, text_content, send_receipt)
                    if not flush_ok:
                        return ExecutionResult(
                            False,
                            "发送文本失败",
                            f"向 {target_name} 发送文本失败: {flush_err}",
                            refreshed_cookies=_get_context_cookies(),
                        )

                # 4. 构建证据描述
                evidence: list[str] = []
                if spark_count > 0:
                    if fallback_spark_used:
                        evidence.append(f"火花表情(已自动文字兜底)x{spark_count}")
                    else:
                        evidence.append(f"续火花表情x{spark_count}")
                if len(segments) > spark_count:
                    evidence.append("文本内容已发出")

                refreshed_cookies = _get_context_cookies()
                return ExecutionResult(
                    True,
                    "发送成功",
                    f"成功向 {target_name} 发送。{('；'.join(evidence)) if evidence else '消息已确认发送'}",
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
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
                # 显式回收垃圾，为弱 VPS 释放内存
                gc.collect()


execution_service = ExecutionService()
