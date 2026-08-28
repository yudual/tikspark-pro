# TikSpark Pro 不稳定因素完整总结

> 生成时间：2026-08-28 17:30 (CST, Asia/Shanghai)  
> 机器：阿里云 120.55.2.149 (aliyun-2c2g, 2C1.6G, 无Swap)  
> 容器：tikspark_api :8010 (Up 30h, 2026-08-27T03:32:46Z 启动)  
> 账号：双持金枪客 (healthy, Cookie 63个, 2026-08-27 07:07 最后更新)

---

## 0. 今日定性

- 过去24h：**27/27 失败**，`summary` 全为 `未找到好友`，`source` 全 `auto`
- 涉及好友：9个 `is_active=1` 全部命中（I / StanZc / 云衫霞裳 / 云野＆ / 叫我蛋蛋 / 堂吉诃德 / 用户573492，/ 菠萝 / 醉落·梦千），各 3 次
- 机器/容器/Cookie 解密均正常，非宕机；最后成功 `2026-08-27 07:07:13 (friend 6)`，之后断崖全败
- 关键日志：`missed by 0:01:05~0:07:29` / `skipped: maximum number of running instances reached (1)` ×4

**结论**：网页版定位链路系统性失效 + 调度自堵 + 无分类重试，共同导致全挂。

---

## 1. 执行器定位缺陷（P0 - 今日根因）

| # | 问题 | 位置 | 后果 |
|---|------|------|------|
| 1-1 | 只在 `https://www.douyin.com/chat` 左侧“最近会话”列表里找人，非全量好友 | `execution_service.py:_find_friend` | 3天未互聊即沉底，App好友正常也报`未找到好友` |
| 1-2 | 定位链路 `可视区→滚动8轮→搜昵称→搜ID→刷新`，搜不到即失败 | 同上 348-430 | 任一环节抖动即全挂 |
| 1-3 | DOM 容器选择器硬编码 6套 `(.im-user-list / [class*=user-list] ...)` | `CONTACT_CONTAINER_SELECTORS` | 抖音一改版失配即全挂 |
| 1-4 | 搜索框 `SEARCH_SELECTORS` 仅 5套 `placeholder*=搜索` | 同上 260 | 文案一改即搜不动 |
| 1-5 | 昵称模糊 `normalize_friend_name` 去括号/标点/emoji，对 `用户573492，`/`StanZc` 容错低 | `_find_visible_match` | 昵称一改即挂 |
| 1-6 | ID 搜索仅当 `not startswith MS4w and dy_id != name`，大量 `MS4w...` 加密串走不到此步 | `_find_friend` | 加密 ID 好友无兜底 |
| 1-7 | 火花表情靠 `emojiEmojiItememojiItemDesc 含“火花”` 定位，找不到走 `🔥` 文字兜底 | `_find_spark_item/_fallback_spark_text` | 火花样式一改即降级，验证仅看输入框清空易误判 |

**修复方向**：
- 加 ID 直连兜底：`https://www.douyin.com/chat/<dy_id>` 直开会话，绕过列表搜索（最稳）
- 短期人工：抖音 App 用 `双持金枪客` 给 9 人各发1条，顶回“最近聊天”
- 加空白页检测：`len(page.content()) < 500` 重试；搜索失败后强制 `clear_search_box` 已有但需加强

---

## 2. 调度 / 并发自堵

| # | 问题 | 证据 |
|---|------|------|
| 2-1 | `IntervalTrigger 60s + max_instances=1 + coalesce=True`，单轮串行 9人 × (40s执行+60-300s jitter) = 15-40分钟 | 日志 `missed by 7m / skipped` |
| 2-2 | 双重锁：内存 `Lock()` + DB `dispatch_locks TTL 3600s` | `dispatch_task_service.py:12` |
| 2-3 | 单线程 `for friend: _run_friend_task_with_timeout`，一人卡30s堵全部 | `FRIEND_FIND_DEADLINE 30s`, 实测38-45s |
| 2-4 | 超时用 `Thread daemon + join(300)`，daemon 内浏览器未回收 | `dispatch_service.py:135-165` |

**修复**：`scheduler_scan_interval 60→300`；`dispatch_jitter 60-300→10-30`；锁TTL 3600→300；超时线程内 `browser.close()`；或改队列并行

---

## 3. Playwright / 反爬 / 机器

| # | 问题 |
|---|------|
| 3-1 | 伪装仅 `disable-blink-features=AutomationControlled` + `PLAYWRIGHT_STEALTH_SCRIPT`，指纹固定，易被拦成 55字符空白页，但仅判 `LOGIN_DIALOG_MARKERS`，空白走 `未找到好友` 误报 |
| 3-2 | 每次 `launch(headless)` 冷启，1.6G/0 Swap，Chromium 300-500M，9连发抖动 |
| 3-3 | `goto(domcontentloaded) + sleep 2.5-4s` 固定等待，无重试 |

**修复**：加 `--disable-dev-shm-usage --single-process`；空白页重试；复用 `browserContext`；加代理IP分流

---

## 4. 重试 / 时间 / 告警

| # | 问题 |
|---|------|
| 4-1 | `failed → consecutive_failures+1 → +30min` 不分类型，`未找到好友`重试100次也找不到 |
| 4-2 | 重试 `now+30min` 无视 `schedule_window 06:00-08:00`，窗口外仍重试 |
| 4-3 | `get_local_now()=utcnow+8 (naive)` vs `APScheduler ZoneInfo Asia/Shanghai (aware)` 混用 |
| 4-4 | 无分类告警，`details` 全一句“请确认是否在私信列表中” |

**修复**：`未找到好友` 退避 6-12h；连续2次失败 Telegram 告警；分类 `风控/网络/定位失败`

---

## 5. Cookie / 账号保活

| # | 问题 | 证据 |
|---|------|------|
| 5-1 | `cookie_expires_at` 全 NULL，`extract_cookie_expires_at` 仅看5个name，实际 -1 恒 NULL | `accounts` 行 |
| 5-2 | 仅成功才 `context.cookies() → encrypt 回写`，失败不保活 | `dispatch_service.py:210` |
| 5-3 | `cookie_updated_at` 停在 2026-08-27 07:07 后无更新 | 同上 |

**修复**：失败也回写；每6h 定时 `context.cookies()` 保活；7天未更新告警

---

## 6. 数据 / 运维脆性

| # | 问题 |
|---|------|
| 6-1 | `_sync_friends_to_db`：`dy_id not in incoming_ids → delete`，网络抖动抓不全就误删好友 |
| 6-2 | 9人同挤 `06:00-08:00` 窗口，仅随机 jitter，无分批 |
| 6-3 | `dispatch_tasks` 幂等键 `auto:friend:YYYYMMDDHHMM` 分钟级，失败用 uuid，新任务无限膨胀（62失败/35成功） |
| 6-4 | 0 Swap + 公网扫描 `Invalid HTTP request` 刷日志占IO |
| 6-5 | `db Session` 跨 `Thread` 共享，非线程安全 |

**修复**：同步改软删除/二次确认；分批窗口；加 1G Swap；每线程独立 Session；`Invalid HTTP` 限流

---

## 修复优先级

| 优先级 | 动作 | 预期 |
|--------|------|------|
| P0 保命 | ID直连兜底 + 空白页重试 + 失败也刷新Cookie | 止住全挂 |
| P1 止堵 | 扫描 60→300s，jitter 60-300→10-30s，锁 3600→300s，超时回收 | 消队列积压 |
| P2 降噪 | 未找到好友退避6h + 连续2次Telegram告警 + 每日04:00保活 | 不再半夜重试堵死 |
| P3 加固 | 加1G Swap，同步软删除，Session隔离，扫描限流 | 稳定性兜底 |

---

## 附：关键文件与参数

- `backend/app/services/execution_service.py` - 定位/发送/表情
- `backend/app/services/scheduler.py` - `IntervalTrigger 60s / max_instances 1`
- `backend/app/services/dispatch_service.py` - 串行派发 / `TASK_HARD_TIMEOUT 300`
- `backend/app/services/dispatch_task_service.py` - 锁TTL 3600 / 幂等键
- `backend/app/services/credential_service.py` - Cookie保活/同步
- `backend/app/config.py` - `dispatch_jitter 60-300 / schedule_window 06:00-08:00`
- `docker-compose.yml` - `8010:8010 / ./backend/data:/app/backend/data`
- DB：`friends(15) / accounts(1) / dispatch_tasks(97) / run_logs(95)`

> 下一步：确认后直接在 `/opt/tiksparkpro` 打 patch 并 `docker compose up -d --build`，当晚验证。
