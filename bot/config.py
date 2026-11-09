from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    database_url: str = "postgresql+asyncpg://songelo:songelo@localhost:5432/songelo"

    spotify_client_id: str
    spotify_client_secret: str

    anthropic_api_key: str = ""  # пусто — ИИ-оценка выключена, рейтинг только из баттлов
    claude_model: str = "claude-sonnet-5-5"
    gemini_api_key: str = ""  # если задан — используется Gemini (бесплатный тариф AI Studio)
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_min_confidence: float = 0.4  # ниже — «не знаю песню», оценку не выдумываем

    battles_per_minute: int = 10  # голосов в минуту на пользователя
    rates_per_minute: int = 5  # /rate и /compare (тратят LLM) в минуту
    ai_ratings_per_day: int = 30  # новых ИИ-оценок на человека за 24 часа


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
