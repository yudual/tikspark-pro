# TikSpark Pro 架构说明

> 本文档描述当前（重构后）代码结构与职责边界。改代码前先看这里，保持"一页一事、一路由一资源"。

## 1. 页面地图

导航分三组，共 7 个页面。每个页面只做一件事。

| 分组 | 页面 | 路径 | 职责 | 数据源 API |
|------|------|------|------|-----------|
| 工作台 | 运行看板 | `/dashboard` | 关键指标 + 引擎状态条 + 最近异常记录 + 快捷入口 | `/api/dashboard/*` |
| 工作台 | 执行与任务 | `/run` | 手动执行表单 + 任务队列列表 | `/api/run/*` |
| 工作台 | 运行日志 | `/logs` | 每次执行的历史结果（分页） | `/api/logs` |
| 配置 | 账号管理 | `/accounts` | 账号增删改查、Cookie 导入/更新、好友管理 | `/api/accounts` |
| 配置 | 消息配置 | `/messages` | 好友消息：固定文本 / 随机话术库 / 批量应用 | `/api/messages` |
| 配置 | 自动计划 | `/auto-schedule` | 自动开关、计划列表、7 天预览、批量策略 | `/api/schedule` |
| 系统 | 系统设置 | `/settings` | 环境变量只读展示、调度开关说明 | `/api/system/settings` |

约定：

- "手动执行"入口唯一在 `/run`，其他页面只放跳转链接。
- 策略编辑（时段/间隔/重试）唯一入口是自动计划页的批量策略表单。
- 总览页只展示摘要，完整列表一律跳到对应页面。

## 2. API 地图

所有接口前缀 `/api`，除 `/health` 外均要求 `Authorization: Bearer <TIKSPARK_ADMIN_TOKEN>`。

### dashboard（总览）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dashboard/summary` | 指标汇总 + 最近 8 条日志 |
| GET | `/api/dashboard/system-status` | 内存状态机实时状态 |

### run（执行与任务）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/run/tasks` | 触发执行（可选 account_id / friend_id） |
| GET | `/api/run/tasks` | 任务队列分页列表（筛选：账号/状态/来源） |

### logs（运行日志）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs` | 执行历史分页（筛选：账号） |

### schedule（自动计划）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/schedule` | 自动计划摘要 + 前 8 项 |
| GET | `/api/schedule/preview` | 未来 N 天计划预览 |
| PATCH | `/api/schedule/settings` | 自动开关（数据库级） |
| POST | `/api/schedule/regenerate` | 重算过期/全部计划 |
| PATCH | `/api/schedule/batch-strategy` | 批量策略应用 |

### accounts / messages / system

- `/api/accounts`：账号与好友资源（Cookie 导入 `POST /api/accounts`、Cookie 更新 `PUT /api/accounts/{id}/cookie`、好友刷新 `POST /api/accounts/{id}/refresh-friends` 等）。
- `/api/messages`：消息配置（单条更新、批量应用）。
- `/api/system/settings`：只读环境变量展示，绝不返回令牌或密钥内容。

## 3. 数据模型

| 表 | 职责 | 说明 |
|----|------|------|
| accounts | 抖音账号 | 含加密 Cookie、状态、代理、过期时间 |
| friends | 账号下好友 | 含自动计划策略、连续失败计数 |
| messages | 好友消息配置 | 每个好友一条（固定文本或随机话术库） |
| run_logs | 执行历史 | 每次执行的结果记录 |
| dispatch_tasks | 执行队列 | 每次触发生成的任务，有状态流转 |
| app_settings | 键值配置 | 自动开关、迁移标志 |
| dispatch_locks | 派发锁 | 防止重复派发 |

语义区分：

- **执行队列（dispatch_tasks）**：一次触发产生的任务，状态流转 pending → running → success/failed。
- **执行历史（run_logs）**：每次执行的结果账本，只增不改。
- 两者按 friend 关联；前端分别由 `/run` 和 `/logs` 展示，不混用。

## 4. 核心流程

```
导入 Cookie → 账号管理（刷新好友，激活目标）
       ↓
配置消息 → 消息配置（固定文本 / 话术库）
       ↓
配置计划 → 自动计划（时段 / 间隔 / 重试策略，开启自动开关）
       ↓
扫描调度 → scheduler（APScheduler 定时扫描到点好友）
       ↓
执行队列 → dispatch_service（错峰等待 → 浏览器发送 → 写 dispatch_tasks + run_logs）
       ↓
人工确认 → 运行看板（异常记录）/ 运行日志（完整历史）
```

## 5. 关键约定

### 时间

- 所有数据库时间字段统一为**北京时间 naive datetime（UTC+8，无时区）**，见 `backend/app/time_utils.py`。
- 调度窗口、下次执行时间、任务时间都按这个约定计算和存储。
- 前端用浏览器本地时区展示（国内用户即北京时间）。
- 不要往数据库里混写 UTC naive。

### 调度开关（两个，职责不同）

| 开关 | 位置 | 作用 |
|------|------|------|
| `TIKSPARK_SCHEDULER_ENABLED` | 环境变量 | 决定调度进程是否启动 |
| `auto_schedule_enabled` | 数据库（自动计划页） | 扫描到点后是否真的入队执行 |

### 安全

- Cookie 以 `backend/data/secret.key` 加密后入库；数据库和密钥必须一起备份。
- API 一律 Bearer Token 保护；系统设置接口只暴露配置标志，不暴露值。

## 6. 目录结构

```
backend/app/
  main.py            # FastAPI 入口，组装 router
  routers/           # 按资源拆分：dashboard / accounts / messages / run / logs / schedule / system
  services/          # 业务服务：
    credential_service.py   # Cookie 解析 + 账号/好友嗅探
     execution_service.py    # Playwright 浏览器发送；支持 [火花] 占位符（自动点表情面板发续火花表情）
    dispatch_service.py     # 执行队列编排（错峰、重试）
    dispatch_task_service.py# 任务表 + 派发锁 CRUD
    schedule_service.py     # 计划时间计算
    scheduler.py            # APScheduler 定时扫描
    secret_service.py       # Cookie 加密
    app_settings_service.py # 键值配置
  models.py          # 数据模型
  schemas.py         # Pydantic 出入参
  state.py           # 内存状态机（供总览/状态接口）
  time_utils.py      # 时间约定
  database.py        # 建表 + 迁移
  tests/             # API 冒烟测试

frontend/src/
  App.vue            # 侧边栏导航（三组）+ 管理员令牌
  router.ts          # 路由表
  api/client.ts      # API 封装
  views/             # 7 个页面
  components/        # 公共组件：AccountSelect / RunStatusTag
  utils/format.ts    # 时间/时长格式化

legacy/              # 旧 Flask 版本存档（不再运行）
backups/             # 重构前数据库备份（不入 git）
```

## 7. 验证命令

```bash
# 后端语法与 API 冒烟
python -m compileall -q backend
python -m unittest discover -s backend/tests -v

# 前端构建（含类型检查）
cd frontend && npm run build

# 本地启动
TIKSPARK_ADMIN_TOKEN=<token> TIKSPARK_SCHEDULER_ENABLED=false \
  python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010
```

页面冒烟（无账号数据时所有页面不得报错、不得空白）用 Playwright 打开全部 7 个路由检查标题和 console。
