FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build


FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

WORKDIR /app

COPY backend/ /app/backend/
COPY main.py /app/main.py
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r backend/requirements.txt

EXPOSE 8010

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
