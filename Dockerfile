FROM python:3.9-slim

WORKDIR /app

# 安裝系統相容依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces 建議建立 UID 1000 專用使用者以確保沙盒安全
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PORT=7860

WORKDIR $HOME/app

# 安裝 Python 依賴
COPY --chown=user requirements.txt $HOME/app/
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# 複製專案程式碼
COPY --chown=user . $HOME/app/

EXPOSE 7860

CMD ["sh", "-c", "uvicorn line_server:app --host 0.0.0.0 --port ${PORT:-7860}"]
