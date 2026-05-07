# Railway / 容器部署：自动读取平台注入的 PORT
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

ENV FLASK_DEBUG=false \
    SERVER_HOST=0.0.0.0

EXPOSE 5002

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5002} --workers 2 --threads 4 --timeout 120 app:app"]
