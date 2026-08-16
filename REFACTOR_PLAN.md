# TikSpark Pro 重构方案（REFACTOR_PLAN）

> 目标：解决"项目乱、菜单面板重复、逻辑不清晰"的问题。
> 原则：重构期间不改变业务行为，只改变代码和页面的组织方式；每阶段可独立验证、可回滚。
> 状态：✅ 已执行完毕（2026-08-16）。Phase 0-4 全部完成并验收，提交历史见 git log。

---

## 1. 现状诊断（证据）

### 1.1 新旧两套代码并存（最乱的根源）

| 文件 | 状态 | 说明 |
|------|------|------|
| `backend/app/`（FastAPI 新版） | 当前唯一运行入口 | `docker-compose.yml`、`main.py` 只跑它 |
| `web_app.py` | 死代码（旧 Flask 版） | 1619 行，含用户/积分/邮箱验证码/Celery/Redis，全部未使用 |
| `templates/`（旧 Jinja 模板） | 死代码 | 旧 Flask 的页面模板，未使用 |
| `scheduler.py`（根目录） | 死代码 | 旧 Flask 调度入口，只 import `web_app` |
| `requirements.txt`（根目录，UTF-16 编码） | 死代码 | 旧 Flask 依赖 |
| `requirements_web.txt` | 死代码 | 旧 Flask 依赖 |
| `main.py` | 新版入口 | 保留 |
| `README.md` | 内容过时 | 还是上游旧项目介绍，不是本项目的部署说明 |

> 注意：本项目目录**没有 git 仓库**，任何删除都不可恢复。旧文件必须先移入 `legacy/` 备份目录，不能直接删除。

### 1.2 前端：8 个菜单互相重叠

| 页面 | 当前内容 | 重复问题 |
|------|----------|----------|
| 总览 dashboard | 指标 + 完整引擎状态卡 + 完整计划卡 + 最近日志列表 | 把引擎页、计划页、日志页的内容全塞进来 |
| 调度引擎状态 engine-status | system-status 全量实时详情 | 与总览的引擎卡 100% 重复；且"引擎状态"是技术概念，不该占菜单 |
| 自动计划 auto-schedule | 开关 + 计划列表 + 7 天预览 + 批量策略 + 每行策略 | 与总览的计划卡重复；一页内有两套策略表单 |
| 手动执行 manual-run | 选账号/好友 → 立即执行 | 执行入口 |
| 任务中心 tasks | dispatch_tasks 列表 | 与"运行日志"语义重叠，用户分不清 |
| 运行日志 logs | run_logs 列表 | 与任务中心展示相似表格 |
| 账号管理 accounts | 账号卡片 + 导入 Cookie + 好友对话框 | 正常 |
| 消息配置 messages | 固定/随机话术 + 批量应用 | 正常 |

其他重复：

- `formatDateTime` 等工具函数在 5 个页面重复定义。
- 账号下拉筛选在 4 个页面各自实现一份。
- 引擎状态标签映射在 2 个页面重复定义。
- 菜单 8 项平铺，无分组，无心智主线。

### 1.3 后端：路由和服务职责不清

- `routers/dashboard.py` 一个文件 554 行，同时管理 5 类资源：状态、执行、计划、日志、任务。
- `run_logs`（执行历史）和 `dispatch_tasks`（执行队列）两张表并存，前端两个页面各展示一张，语义无说明。
- 时间存储混乱：部分表用 `utcnow()`，部分表用 `utcnow() + 8小时`（北京时间硬编码），还专门写过时区迁移代码。
- 状态机分散三处：内存 `global_state` + 数据库 `dispatch_locks` + 线程锁 `_dispatch_lock`。
- 自动调度有**两个开关**：环境变量 `TIKSPARK_SCHEDULER_ENABLED`（进程级）和数据库 `auto_schedule_enabled`（页面级），语义混淆。
- 服务层 9 个文件职责边界没有文档；根目录 `scheduler.py` 与 `backend/app/services/scheduler.py` 同名，极易认错。

---

## 2. 目标：信息架构

按用户心智主线组织：**账号 → 消息 → 计划 → 执行 → 结果**。

### 2.1 新导航（7 项，分 3 组）

```
工作台
  总览          /dashboard     只放：关键指标 + 引擎状态条 + 异常日志(仅失败/复核) + 快捷入口
  执行与任务    /run           手动执行表单 + 任务列表（合并 manual-run 与 tasks）
  运行日志      /logs          执行历史（原样保留）

配置
  账号管理      /accounts      账号 + Cookie + 好友（原样保留）
  消息配置      /messages      固定/随机话术 + 批量应用（原样保留）
  自动计划      /auto-schedule 开关 + 计划 + 预览（策略表单收敛为一份）

系统
  系统设置      /settings      新增：管理员令牌 / 调度开关 / 环境变量说明（只读展示）
```

### 2.2 页面职责（一页只做一件事）

| 页面 | 删掉的内容 | 保留的内容 |
|------|-----------|-----------|
| 总览 | 完整引擎卡、完整计划卡、全部日志列表 | 4 个指标、单行状态条（引擎模式/当前步骤/下次扫描）、异常日志 5 条、快捷按钮 |
| 执行与任务 | — | 上：账号/好友选择 + 立即执行；下：任务列表（分页 + 筛选，原 tasks 页） |
| 自动计划 | 每行独立的 5 字段策略表单 | 开关 + 计划列表 + 7 天预览 + 一份批量策略表单 |
| 引擎状态 | 整页删除 | 合并进总览的状态条 |

### 2.3 后端 API 收敛

把 `dashboard.py` 拆分，每个资源一个 router：

```
GET    /api/dashboard/summary         → 保留（总览指标）
GET    /api/dashboard/system-status   → 保留（总览状态条）
POST   /api/dashboard/run-tasks       → /api/run/tasks       （执行）
GET    /api/dashboard/tasks           → /api/run/tasks       （任务列表）
GET    /api/dashboard/logs            → /api/logs            （运行日志）
GET    /api/dashboard/auto-schedule*  → /api/schedule/*      （自动计划）
```

`accounts`、`messages` 路由不变。前端 `client.ts` 同步修改。

### 2.4 语义统一（文档 + 文案）

- `dispatch_tasks` = **执行队列**（本次要跑的任务，有状态流转）
- `run_logs` = **执行历史**（每次执行的结果记录）
- 前端文案、页面副标题、代码注释统一使用这两套说法，不再出现"任务中心/运行日志"这种分不清的并列。
- 两个调度开关写进架构文档：`TIKSPARK_SCHEDULER_ENABLED` 决定调度进程是否启动；页面开关决定是否真的入队执行。

---

## 3. 实施阶段

### Phase 0：建立安全基线（先做，1 天）

1. 在项目根目录初始化 git 仓库，提交当前完整代码作为基线。
2. 备份 `backend/data/`（含账号 Cookie 的数据库和密钥）。
3. 记录当前服务端口、环境变量和启动方式。

### Phase 1：死代码清理 + 前端页面收敛（纯组织，不改行为）

1. 把 `web_app.py`、`templates/`、根 `scheduler.py`、根 `requirements*.txt` 移入 `legacy/`。
2. 删除 engine-status 页面；总览瘦身；新建"执行与任务"页合并 manual-run + tasks。
3. 导航分组；新增系统设置页（只读展示环境变量）。
4. 验收：`npm run build` + 后端启动 + Playwright 冒烟全部页面。

### Phase 2：后端路由收敛（不改行为）

1. 拆分 dashboard router 为 run/logs/schedule 三个 router。
2. 同步修改前端 `client.ts`。
3. 验收：全部页面功能回归（无账号数据也要求页面不报错）。

### Phase 3：模型与时间统一（需数据备份）

1. 统一时间存储为 UTC，展示时前端本地化；修正 `RunLog`/`DispatchTask` 的 `utcnow()+8h`。
2. 评估是否合并 `dispatch_tasks` 与 `run_logs`（若合并需写迁移脚本，从简则保留两张表）。
3. 验收：迁移前后数据核对。

### Phase 4：工程化与文档

1. 抽取公共组件与工具：`AccountSelect.vue`、`StatusTag.vue`、`src/utils/format.ts` 等。
2. 清理 `styles.css` 中重复类。
3. 写 `ARCHITECTURE.md`：页面地图、API 地图、数据模型说明、调度流程。
4. 补充后端 API 冒烟测试（pytest）和前端 build 检查。

---

## 4. 风险与对策

| 风险 | 对策 |
|------|------|
| 无 git，删错不可恢复 | Phase 0 先建 git 基线；旧文件移 `legacy/` 不删除 |
| 数据库含真实账号 Cookie | 每次涉及 schema 的改动前备份 `backend/data/` |
| 重构改坏功能 | 每阶段结束跑 build + 页面冒烟；行为不变原则 |
| 前端页面多、联动多 | 先收敛导航和总览，其他页面先保持原样，逐页确认 |

---

## 5. 验收标准

- 菜单 7 项、3 组，每个页面职责一句话能说清。
- 总览不再出现完整引擎卡/计划卡/日志列表。
- "执行"入口唯一（执行与任务页），其他页面只有跳转链接。
- 后端 router 按资源拆分，`dashboard.py` 不再管理 5 类资源。
- 项目根目录一眼能看出：新代码在 `backend/app/`，旧代码在 `legacy/`，部署说明在 README。
- 所有页面在无账号数据时不报错、不空白。
