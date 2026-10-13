FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/vbot.sqlite3

WORKDIR /app
RUN useradd --create-home --uid 10001 bot && mkdir -p /data && chown bot:bot /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY vbot ./vbot
COPY scripts ./scripts
COPY config ./config

USER bot
CMD ["python", "-m", "vbot"]
