# 1Panel 小白部署指南

这个项目现在支持“一个容器、一个端口”部署：后端会自动托管前端页面，部署后访问 `http://服务器IP:8010` 就能打开管理后台。

## 准备

1. 云服务器已安装 1Panel。
2. 服务器安全组或防火墙放行 `8010` 端口。
3. 把整个项目文件夹上传到服务器，比如 `/opt/tiksparkpro`。

## 在 1Panel 部署

1. 打开 1Panel。
2. 进入“容器”或“应用商店 / 编排”里的 Compose 管理入口。
3. 新建 Compose 项目。
4. 选择项目目录为你上传的目录，例如 `/opt/tiksparkpro`。
5. Compose 文件选择项目里的 `docker-compose.yml`。
6. 点击启动。

第一次启动会安装 Python 依赖、构建前端页面，时间会比较久，等日志里出现 `Uvicorn running on http://0.0.0.0:8010` 就可以访问。

## 管理员令牌

`docker-compose.yml` 里默认有：

```text
TIKSPARK_ADMIN_TOKEN=change-this-token
```

上线前请把 `change-this-token` 改成你自己的长一点的随机字符串。打开页面后，点击右上角“管理员令牌”，填写同一个值即可解锁接口。

## 上线前检查

部署成功后，建议按这个顺序检查：

1. 打开 `http://服务器IP:8010/health`，确认返回 `status: ok`。
2. 确认 `auth_required` 是 `true`。如果是 `false`，说明还没有配置管理员令牌。
3. 打开管理后台，右上角填写管理员令牌。
4. 先保持 `TIKSPARK_SCHEDULER_ENABLED=false`，不要急着开自动调度。
5. 到“账号管理”更新或确认 Cookie 状态。
6. 到“消息配置”确认固定文本或随机话术库。
7. 到“自动续火花计划”确认时间段、未来计划和过期任务。
8. 到“手动执行”先小范围测试一个好友。
9. 到“任务中心”和“任务日志”确认结果正常。
10. 全部确认后，再把 `TIKSPARK_SCHEDULER_ENABLED=true`，重启 Compose。

项目根目录有 `.env.example`，里面列出了常用环境变量。你可以照着填到 1Panel 的 Compose 环境变量里。

## 访问地址

浏览器打开：

```text
http://服务器IP:8010
```

如果你绑定了域名，也可以在 1Panel 里用反向代理把域名转发到容器的 `8010` 端口。

## 自动任务开关

默认部署时自动调度是关闭的：

```text
TIKSPARK_SCHEDULER_ENABLED=false
```

这样更适合第一次上云，先确认账号、消息、任务配置都没问题。确认后再把 `docker-compose.yml` 里的值改成：

```text
TIKSPARK_SCHEDULER_ENABLED=true
```

然后在 1Panel 里重新部署或重启 Compose 项目。

## 必须备份的数据

请定期备份这个目录：

```text
backend/data
```

里面通常包含：

- `tikspark.db`：账号、好友、消息、任务记录。
- `secret.key`：Cookie 加密密钥。

这两个文件要一起备份。只有数据库没有 `secret.key`，之前保存的 Cookie 可能无法解密。

## 常见问题

如果页面打不开，先检查：

- 服务器 `8010` 端口是否放行。
- 1Panel Compose 项目是否正在运行。
- 日志里是否有 Python 依赖安装失败、前端构建失败或数据库权限错误。

如果任务不自动执行，检查：

- `TIKSPARK_SCHEDULER_ENABLED` 是否为 `true`。
- 账号 Cookie 是否有效。
- 自动续火花配置是否启用。
- 任务中心是否有失败日志。
