# VPS 部署指南（Docker 方式）

> 目标：把 TikSpark Pro 部署到任意 Linux VPS，单容器单端口 8010。
> 前置：VPS 有公网 IP，2 核 / 2G 内存以上（浏览器自动化吃资源）。

## 1. 安装 Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo docker version   # 确认安装成功
```

## 2. 拉取代码

```bash
git clone https://github.com/<你的用户名>/tikspark-pro.git
cd tikspark-pro
```

## 3. 必改配置（编辑 docker-compose.yml）

```yaml
environment:
  - TIKSPARK_ADMIN_TOKEN=改成你的长随机串   # 必改，网页右上角要填同一个
  - TIKSPARK_SCHEDULER_ENABLED=false        # 先保持 false，上线确认后再开
```

## 4. 构建并启动

```bash
docker compose up -d --build
docker compose logs -f
```

看到 `Uvicorn running on http://0.0.0.0:8010` 即成功。Ctrl+C 退出日志。

## 5. 放行端口

- 云厂商安全组：放行 TCP 8010
- VPS 内（如有 ufw）：`sudo ufw allow 8010`

## 6. 访问与验证

1. 浏览器打开 `http://VPS公网IP:8010`
2. 右上角"管理员令牌"填第 3 步的 token
3. `curl http://VPS公网IP:8010/health` 应返回 `{"status":"ok","auth_required":true}`
4. 导入 Cookie → 配置消息 → 在"执行与任务"手动执行一次验证

## 7. 上线检查清单

- [ ] 管理员令牌已改且页面能解锁
- [ ] 手动执行一次真实发送成功（看运行日志）
- [ ] 账号状态 healthy，Cookie 过期时间正常
- [ ] 自动计划里开关、时段、策略已配置
- [ ] 确认无误后把 `TIKSPARK_SCHEDULER_ENABLED` 改为 `true` 并重启：`docker compose up -d`

## 8. 数据与备份（重要）

- 数据持久化在 `backend/data/`（compose 已挂载卷），含 `tikspark.db` 和 `secret.key`
- **两个文件必须一起备份**，只备份数据库无法解密 Cookie
- 备份示例：
  ```bash
  tar czf tikspark-backup-$(date +%F).tar.gz backend/data/
  ```

## 9. 常用运维命令

```bash
docker compose ps              # 状态
docker compose logs -f         # 日志
docker compose restart         # 重启
docker compose pull && docker compose up -d --build   # 更新代码后重建
```

## 10. 可选：HTTPS

用 Caddy 反代（自动证书）：

```bash
sudo apt install -y caddy
# /etc/caddy/Caddyfile:
# 你的域名 {
#     reverse_proxy 127.0.0.1:8010
# }
sudo systemctl restart caddy
```

## 故障排查

| 现象 | 处理 |
|------|------|
| 页面打不开 | 安全组/ufw 是否放行 8010；`docker compose logs` 有无报错 |
| 构建失败 | VPS 网络是否能访问 npm/pypi 镜像；`docker compose build --no-cache` 重试 |
| 发送失败"未找到好友" | 确认 Cookie 有效、好友在列表；看运行日志原因 |
| 自动任务不跑 | `TIKSPARK_SCHEDULER_ENABLED` 是否 true；自动计划页开关是否开启 |
