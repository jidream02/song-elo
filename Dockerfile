FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

RUN useradd --create-home bot && chown -R bot /app
USER bot

# Сначала применяем миграции, потом запускаем бота
CMD ["sh", "-c", "alembic upgrade head && python -m bot.main"]
