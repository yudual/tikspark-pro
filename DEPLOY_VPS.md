# VPS 极速部署指南（国内低配机型专项优化）

> **针对国内阿里云/腾讯云 1C1G / 1C2G 等低配、弱 IO、小带宽 VPS 深度优化：**
> 1. **前端已预编译构建（Zero-Build）**：无需在 VPS 上安装 Node.js 或执行吃内存卡死机、吃 IO 的 `npm build`。
> 2. **国内镜像加速**：Playwright Chromium 与 PyPI 自动走国内清华/淘宝镜像，避免小带宽拉取超时。
> 3. **SQLite WAL 优化**：大幅减轻磁盘读写锁竞争与高 IO 延迟。

---

## 方案 A：国内低配 VPS 极速脚本部署（推荐，内存占用 < 150MB）

适合 1C1G、1C2G 等性能有限的国内 VPS，速度最快、省内存：

```bash
# 1. 克隆代码（仓库内已包含预编译好的前端资源）
git clone https://github.com/yudual/tikspark-pro.git
cd tikspark-pro

# 2. 赋予执行权限并一键安装（自动走国内清华/淘宝镜像）
chmod +x deploy_vps_quick.sh
./deploy_vps_quick.sh
```

脚本执行完成后会提示启动命令，例如后台守护运行：
```bash
nohup env TIKSPARK_ADMIN_TOKEN=你的自定义安全令牌 .venv/bin/python main.py > tikspark.log 2>&1 &
```

---

## 方案 B：Docker 容器化部署（免前端构建加速版）

Dockerfile 已优化为**直接复制预编译前端静态文件**，无需在容器内下载 Node.js 与构建前端：

```bash
# 1. 克隆代码
git clone https://github.com/yudual/tikspark-pro.git
cd tikspark-pro

# 2. 修改 docker-compose.yml 里的管理员令牌
# TIKSPARK_ADMIN_TOKEN=改成你的长随机串

# 3. 极速构建并启动（数十秒内即可完成）
docker compose up -d --build
```

---

## 方案 C：使用 Release 独立离线包（零 Git 依赖）

如果您不想在 VPS 上克隆 Git 仓库，可直接下载本地生成的发布包 `tikspark-pro-release.tar.gz`（体积仅 ~450KB）：

```bash
# 1. 解压发布包
tar -xzf tikspark-pro-release.tar.gz
cd tikspark-pro

# 2. 执行快速部署
./deploy_vps_quick.sh
```

---

## 开放防火墙与访问

1. **云厂商安全组**：在阿里云/腾讯云控制台放行 **TCP 8010** 端口。
2. **VPS 防火墙**（若开启了 ufw）：
   ```bash
   sudo ufw allow 8010
   ```
3. 打开浏览器访问：`http://你的VPS公网IP:8010`，在右上角填入管理员访问令牌解锁即可。

---

## 数据备份（重要）

数据与 Cookie 密钥持久化在 `backend/data/` 目录下（`tikspark.db` 和 `secret.key`）：
```bash
# 一键备份数据库与解密密钥
tar czf tikspark-backup-$(date +%F).tar.gz backend/data/
```
