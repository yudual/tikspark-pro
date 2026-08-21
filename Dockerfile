FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

WORKDIR /app

# 1. 复制后端与预构建前端静态资源（免去 VPS 上跑 Node.js 构建，极大节省内存与 IO）
COPY backend/ /app/backend/
COPY frontend/dist/ /app/frontend/dist/
COPY main.py /app/main.py

# 2. 国内镜像源安装 Python 依赖
RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r backend/requirements.txt

EXPOSE 8010

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
