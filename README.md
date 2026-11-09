# 🎵 Song Elo

Telegram-бот, который оценивает песни по шкале Elo (1500 = средняя песня).
Стартовую оценку новой песни даёт Claude по критериям, дальше рейтинг двигают баттлы пользователей.

## Команды

| Команда | Что делает |
|---|---|
| `/rate <песня>` | Находит песню в Spotify и выдаёт Elo с объяснением |
| `/battle` | Две случайные песни — выбери лучшую кнопкой |
| `/top` | Топ-20 песен по общему рейтингу |
| `/mytop` | Личный рейтинг по твоим баттлам |
| `/compare <песня1> \| <песня2>` | Прогноз: кто победит и с какой вероятностью |

## Как считается рейтинг

**Elo после баттла:** `E = 1 / (1 + 10^((Rb − Ra) / 400))`, `R' = R + K·(S − E)`.
K = 48, пока у песни < 10 матчей, потом K = 32 (у каждой песни свой K).

**Стартовая оценка (`/rate`):**
1. ≥ 10 баттлов → показывается рейтинг из баттлов.
2. Иначе Claude оценивает 6 критериев по 1–10: мелодия, вокал, продакшн, оригинальность, эмоции, культурное влияние.
   Elo считает сам бот по среднему баллу (1 → 800, 5 → 1500, 10 → 2200, между ними линейно);
   число `elo` из ответа модели только сохраняется для отладки.
3. Если `confidence` < `LLM_MIN_CONFIDENCE` — бот честно говорит «не знаю» и предлагает кнопку «Отправить в баттлы».
4. Оценка LLM кэшируется в БД и становится стартовым рейтингом; дальше его меняют только баттлы.

**Антинакрутка:**
- один голос на пару песен от пользователя в сутки (UTC) — уникальный индекс в БД;
- пара выдаётся как `battle_offer` в БД, в кнопке только его id — подделать пару или проголосовать дважды нельзя;
- лимит голосов в минуту (`BATTLES_PER_MINUTE`) и вызовов `/rate`/`/compare` (`RATES_PER_MINUTE`, они тратят LLM).

## Ключи

1. **Telegram** — создай бота у [@BotFather](https://t.me/BotFather), получи токен.
2. **Spotify** — [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) → Create app → Client ID и Client Secret.
3. **LLM для стартовой оценки** (необязательно), один из двух:
   - **Google Gemini** — бесплатный тариф: [aistudio.google.com](https://aistudio.google.com) → Get API key → `GEMINI_API_KEY`.
     Если задан, используется он. Модель — `GEMINI_MODEL`.
   - **Claude** — [console.anthropic.com](https://console.anthropic.com) → API Keys (нужен баланс).
   Если `ANTHROPIC_API_KEY` пустой, бот работает бесплатно: ИИ-оценка выключена, каждая песня из `/rate`
   сразу попадает в баттлы со стартом 1500, и рейтинг формируют только голоса.

```bash
cp .env.example .env
# заполни .env своими ключами
```

## Запуск через Docker

```bash
docker compose up -d --build
docker compose logs -f bot
```

Миграции применяются автоматически при старте контейнера.

## Запуск без Docker

Нужны Python 3.11+ и PostgreSQL.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# создать базу (пример)
sudo -u postgres psql -c "CREATE USER songelo WITH PASSWORD 'change-me';"
sudo -u postgres psql -c "CREATE DATABASE songelo OWNER songelo;"

alembic upgrade head
python -m bot.main
```

## Тесты

```bash
pytest
```

Покрыты формула Elo, перевод баллов в Elo, парсинг JSON от LLM (code-fence, текст вокруг, мусор, пропущенные критерии, «не знаю») и rate limiter.

## Структура

```
bot/        main.py, config.py, middlewares.py, keyboards.py, texts.py, handlers/
services/   elo.py, llm_rater.py, spotify.py, songs.py, rate_limit.py
db/         models.py, session.py, migrations/
tests/      pytest
```

## Первый запуск

В пустой базе баттлов нет — сначала оцени несколько песен через `/rate`
(уверенно оценённые ИИ сразу попадают в пул баттлов).
