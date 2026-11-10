"""
backend/core/settings.py
-------------------------
Typed, validated backend settings. FAILS CLOSED: outside ENV=local the app
refuses to start with weak/unsafe security configuration.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    env: Literal["local", "staging", "prod"] = "local"
    data_source: Literal["demo", "redshift"] = "demo"

    # ── Auth ──────────────────────────────────────────────────────────────────
    app_auth_method: Literal["none", "basic"] = "none"
    app_auth_basic_user: str = ""
    app_auth_basic_password_hash: SecretStr = SecretStr("")  # bcrypt hash, never plaintext
    app_secret_key: SecretStr = SecretStr("")

    # ── Network ───────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    rate_limit_per_minute: int = Field(default=240, ge=1)
    # Behind the dashboard proxy / a load balancer every request has the proxy's address. Only enable this when a
    # TRUSTED proxy sets X-Forwarded-For (otherwise clients could spoof it to dodge the limit).
    trust_forwarded_for: bool = False
    max_query_param_length: int = Field(default=200, ge=10)
    export_max_rows: int = Field(default=100_000, ge=1)

    # ── Redshift (read-only service user) ─────────────────────────────────────
    # redshift = production (redshift_connector, TLS). postgres = CI / compose smoke stack stand-in only.
    warehouse_driver: Literal["redshift", "postgres"] = "redshift"
    warehouse_ssl: bool = True
    redshift_host: str = ""
    redshift_port: int = 5439
    redshift_db: str = ""
    redshift_user: str = ""
    redshift_password: SecretStr = SecretStr("")
    statement_timeout_ms: int = Field(default=30_000, ge=1000)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def is_local(self) -> bool:
        return self.env == "local"

    @model_validator(mode="after")
    def _fail_closed(self) -> "Settings":
        problems: list[str] = []
        if not self.is_local:
            if self.app_auth_method == "none":
                problems.append("APP_AUTH_METHOD=none is only allowed when ENV=local")
            if len(self.app_secret_key.get_secret_value()) < 32:
                problems.append("APP_SECRET_KEY must be set (>= 32 chars) outside ENV=local")
            if "*" in self.cors_origin_list or "*" in self.allowed_host_list:
                problems.append("Wildcard CORS_ORIGINS / ALLOWED_HOSTS are forbidden outside local")
            if self.data_source == "demo":
                problems.append("DATA_SOURCE=demo is only allowed when ENV=local")
        if self.env == "prod" and (self.warehouse_driver != "redshift" or not self.warehouse_ssl):
            problems.append("ENV=prod requires WAREHOUSE_DRIVER=redshift with WAREHOUSE_SSL=true")
        if self.app_auth_method == "basic":
            if not self.app_auth_basic_user or not self.app_auth_basic_password_hash.get_secret_value():
                problems.append("basic auth needs APP_AUTH_BASIC_USER and APP_AUTH_BASIC_PASSWORD_HASH")
            elif not self.app_auth_basic_password_hash.get_secret_value().startswith("$2"):
                problems.append("APP_AUTH_BASIC_PASSWORD_HASH must be a bcrypt hash, not plaintext")
        if self.data_source == "redshift" and not (
            self.redshift_host and self.redshift_db and self.redshift_user
        ):
            problems.append("DATA_SOURCE=redshift needs REDSHIFT_HOST/DB/USER")
        if problems:
            raise ValueError("Unsafe configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
