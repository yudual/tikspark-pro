# TikSpark Pro Modernization 进度报告

本项目正在进行从旧版（`web_app.py` 单文件架构）到 **新版 FastAPI + Vue3 前后端分离架构** 的现代化重构。

## 🎯 当前重构进度：核心能力已补齐

新架构已经不仅实现了基础的数据托管，还完成了真正的**防风控自动化发送引擎**及**多账号管理能力**：

### 1. 核心自动化与防风控引擎 (Execution & Anti-Detection)
- **底层驱动**: 引入 `Playwright` 作为底层驱动，模拟真实浏览器环境（支持无头模式）。
- **环境隔离**: 账号模型已增加 `proxy_url` 字段，支持为不同账号配置独立代理 IP，实现物理环境隔离。
- **拟人化仿真**: 
  - 智能搜索与兜底滚动结合的好友定位策略。
  - 随机延迟的模拟真实键盘敲击输入（而非直接粘贴）。
- **时间错峰与队列 (Jitter)**: 默认取消“人工复核”模式。后台定时任务触发时，会自动打乱发送顺序，并在每个任务间插入 **1~5 分钟的随机休眠**，彻底打破机器人的规律性，防范批量封号。

### 2. 账号与数据解析增强 (Credential Parsing)
- **多源数据嗅探**: 导入凭证时，从网络包 (Network) 和本地存储 (Storage, DOM) 多维度提取数据，确保在复杂结构下也能拿到真实抖音号和高清头像。
- **长 ID 过滤**: 自动过滤并清理 `MS4wLj...` 等无意义加密 ID。

### 3. 前端多账号规模化管理体验 (Frontend UI/UX)
- **运行看板**: 新增了**“实时调度引擎状态”**面板（自动心跳轮询），可实时查看后台任务执行到了哪一步、是在等待防风控还是在发送消息。
- **账号管理**:
  - 新增账号编辑（可单独设置昵称和代理）。
  - 新增账号删除（级联清理数据）。
  - 列表支持按状态 Tab 分类和搜索过滤。
- **消息配置**:
  - 列表高度自适应 + 粘性表头。
  - 支持 **全局按账号筛选**，方便管理海量好友。
  - 支持 **批量应用配置**，一键将固定文本或话术库应用给选定账号的所有好友。
- **任务日志**:
  - 实现了基于后端的真实分页查询（Pagination）。
  - 支持按账号过滤日志，防止数据堆叠。
- **手动调度干预**: 支持在看板一键“立即运行续火”，也支持在好友管理或消息配置列表中，针对**单个特定好友**点击“执行”进行针对性发送。

## 🚀 本地运行方式

> 如果项目是从 `D:\tiksaprkpro` 复制到 `E:\tiksaprkpro`，不要直接复用旧的 `.venv`。
> Windows 虚拟环境会记录创建时的解释器和项目路径，复制后可能导致后端无法启动，前端则会弹出 500 或提示 8010 服务不可用。
> 处理方式：删除当前目录下的 `.venv` 后重新执行下面的后端环境安装命令。

### 1. 启动后端 (注意端口)
```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
# 为解决 Windows Playwright 异步冲突，主程序已增加 ProactorEventLoopPolicy
.\.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010 --reload
```
*API 运行于 `http://127.0.0.1:8010`*

### 2. 启动前端
```powershell
cd frontend
npm install
npm run dev
```
*Web 面板运行于 `http://127.0.0.1:5173`*

## 📁 核心架构说明

- `backend/app/services/execution_service.py`: 核心 Playwright 浏览器自动化逻辑。
- `backend/app/services/dispatch_service.py`: 任务队列与时间错峰逻辑。
- `backend/app/services/credential_service.py`: 复杂的 Cookie 解析与头像/ID清洗逻辑。
- `backend/app/state.py`: 全局状态机，用于前端轮询展示执行进度。

---

*（此文档作为 AI 会话状态及项目开发进度的总结快照，可用于后续中断重启后快速恢复上下文）*
