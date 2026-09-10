FROM python:3.9-slim

WORKDIR /app

# 安裝系統相容依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 建立非 root 使用者執行服務（一般容器安全實務，不綁定特定平台）
RUN useradd -m -u 1000 appuser
ENV PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8080

CMD ["sh", "-c", "uvicorn line_server:app --host 0.0.0.0 --port ${PORT:-8080}"]
