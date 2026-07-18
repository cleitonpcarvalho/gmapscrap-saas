from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://gmapscrap:gmapscrap@localhost:5432/gmapscrap"
    app_username: str = "cleiton.carvalho@automasoluct.com.br"
    app_password: str = "change-this-password"
    session_secret: str = "change-this-local-secret"
    session_cookie_secure: bool = False
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    chrome_bin: str | None = None
    chromedriver_bin: str | None = None
    selenium_headless: bool = True
    public_base_url: str = "http://localhost:8000"
    contact_email: str = "contato@automasoluct.com.br"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
