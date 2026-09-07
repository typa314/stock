FROM python:3.9-slim

WORKDIR /app

# 安裝系統相容依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案程式碼
COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn line_server:app --host 0.0.0.0 --port ${PORT}"]
