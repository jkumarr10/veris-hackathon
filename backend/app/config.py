from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Baseten OpenAI-compatible endpoint settings.
    baseten_api_key: str | None = None
    baseten_model: str | None = None
    baseten_base_url: str = "https://inference.baseten.co/v1"

    # Optional direct OpenAI fallback.
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.3"

    # Default to real Kaggle generation dataset. Yield agent auto-resolves matching weather CSV.
    default_panel_csv: str = "data/Plant_1_Generation_Data.csv"
    default_cleaning_cost_usd: float = 5000.0
    default_lookahead_days: int = 7
    default_energy_price_per_kwh: float = 0.11


settings = Settings()
