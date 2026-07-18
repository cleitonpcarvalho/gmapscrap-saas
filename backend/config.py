from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://gmapscrap:gmapscrap@localhost:5432/gmapscrap"
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_sslmode: str = ""
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
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "gmapscrap"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
