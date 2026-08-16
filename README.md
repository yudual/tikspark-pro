# TikSpark Pro

抖音多账号火花自动维护面板：Cookie 托管、好友管理、消息配置、自动续火计划与浏览器自动化发送。

> 本项目经历了一次重构：旧 Flask 版已归档到 `legacy/`，当前运行版本为 FastAPI + Vue3。
> 结构与约定见 [ARCHITECTURE.md](ARCHITECTURE.md)，重构过程见 [REFACTOR_PLAN.md](REFACTOR_PLAN.md)。

## 功能

- 账号管理：Cookie 导入/更新（自动解析账号和好友）、状态与过期时间、代理配置
- 消息配置：固定文本 / 随机话术库 / 批量应用
- 自动计划：续火时段、间隔天数、冷却、失败重试，7 天预览
- 执行与任务：手动触发（按账号/好友）、任务队列、执行历史
- 浏览器自动化：Playwright 模拟人工发送，防风控错峰
- 管理员令牌保护 API，Cookie 加密存储

## 本地运行

```bash
# 1. 后端依赖
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. 前端构建（Vue3 + Vite）
cd frontend
npm ci
npm run build
cd ..

# 3. 启动（默认关闭自动调度）
TIKSPARK_ADMIN_TOKEN=change-me TIKSPARK_SCHEDULER_ENABLED=false \
  .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010
```

访问 `http://127.0.0.1:8010`，右上角填入与服务器相同的管理员令牌。

## 环境变量

见 [.env.example](.env.example)。常用：

| 变量 | 说明 | 默认 |
|------|------|------|
| `TIKSPARK_ADMIN_TOKEN` | API 访问令牌（必改） | 空 |
| `TIKSPARK_SCHEDULER_ENABLED` | 是否启动调度进程 | true |
| `TIKSPARK_SCHEDULER_SCAN_INTERVAL_SECONDS` | 扫描间隔秒 | 60 |
| `TIKSPARK_MANUAL_REVIEW_MODE` | 人工复核模式（只记录不发送） | false |
| `TIKSPARK_SQLITE_PATH` | 数据库路径 | backend/data/tikspark.db |
| `TIKSPARK_SECRET_KEY_PATH` | Cookie 加密密钥路径 | backend/data/secret.key |

> 数据库和密钥必须一起备份，否则已保存的 Cookie 无法解密。

## 测试与检查

```bash
python -m compileall -q backend
python -m unittest discover -s backend/tests -v
cd frontend && npm run build
```

## 部署

云服务器部署（单容器单端口 8010）见 [DEPLOY_1PANEL.md](DEPLOY_1PANEL.md)。

## 免责声明

本项目仅供个人学习与少量关系维护使用。请遵守抖音平台规则，自行评估账号风险。
