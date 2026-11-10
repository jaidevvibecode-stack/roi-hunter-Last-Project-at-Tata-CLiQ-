"""
ingestion/common/config.py
--------------------------
Centralised configuration via pydantic-settings.
All env var names are listed in .env.example — never hardcode values here.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MetaSettings(BaseSettings):
    """Meta (Facebook) Marketing API credentials and parameters."""

    model_config = SettingsConfigDict(env_prefix="META_", extra="ignore")

    access_token: str = Field(default="", description="System User access token")
    app_id: str = Field(default="", description="Meta App ID")
    app_secret: str = Field(default="", description="Meta App Secret")
    business_id: str = Field(default="", description="Meta Business Manager ID")

    # Comma-separated lists — parsed into Python lists by validator
    ad_account_ids_raw: str = Field(
        default="",
        alias="META_AD_ACCOUNT_IDS",
        description="Comma-separated ad account IDs, e.g. act_123,act_456",
    )
    catalog_ids_raw: str = Field(
        default="",
        alias="META_CATALOG_IDS",
        description="Comma-separated catalog IDs",
    )
    api_version: str = Field(default="v22.0", description="Pinned Graph API version")
    # Conversion attribution. Default = the ad accounts' own (unified) setting, i.e. what Ads Manager shows.
    # To pin explicit windows instead (e.g. "7d_click" to match the 7-day-click models), set
    # META_USE_UNIFIED_ATTRIBUTION=false and META_ATTRIBUTION_WINDOWS=7d_click[,1d_view]. Verify in spike P0.3.
    use_unified_attribution: bool = Field(default=True)
    attribution_windows: str = Field(default="", description="Comma-separated, used only when unified is false")

    # Concurrency: default 2 async jobs per account (DESIGN §7.1)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=10)

    @field_validator("ad_account_ids_raw", mode="before")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def ad_account_ids(self) -> list[str]:
        return [a.strip() for a in self.ad_account_ids_raw.split(",") if a.strip()]

    @property
    def catalog_ids(self) -> list[str]:
        return [c.strip() for c in self.catalog_ids_raw.split(",") if c.strip()]

    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_ids)


class MixpanelSettings(BaseSettings):
    """Mixpanel service account credentials."""

    model_config = SettingsConfigDict(env_prefix="MIXPANEL_", extra="ignore")

    project_id: str = Field(default="")
    service_account_user: str = Field(default="")
    service_account_secret: str = Field(default="")
    # US | EU | IN — affects export API host
    region: str = Field(default="US", pattern="^(US|EU|IN)$")

    @property
    def export_host(self) -> str:
        """Raw Export API host depending on data-residency region."""
        return {
            "US": "data.mixpanel.com",
            "EU": "data-eu.mixpanel.com",
            "IN": "data-in.mixpanel.com",
        }[self.region]

    def is_configured(self) -> bool:
        return bool(self.project_id and self.service_account_user and self.service_account_secret)


class RedshiftSettings(BaseSettings):
    """Amazon Redshift connection settings."""

    model_config = SettingsConfigDict(env_prefix="REDSHIFT_", extra="ignore")

    host: str = Field(default="")
    port: int = Field(default=5439)
    db: str = Field(default="")
    user: str = Field(default="")
    password: str = Field(default="")
    iam_role_arn: str = Field(
        default="", description="IAM role ARN for COPY from S3"
    )

    def is_configured(self) -> bool:
        return bool(self.host and self.db and self.user and self.password)


class S3Settings(BaseSettings):
    """S3 staging bucket for raw Parquet files."""

    model_config = SettingsConfigDict(env_prefix="S3_", extra="ignore")

    raw_bucket: str = Field(default="")
    raw_prefix: str = Field(default="roi-hunter/raw")
    aws_region: str = Field(
        default="ap-south-1", alias="AWS_REGION"
    )

    def is_configured(self) -> bool:
        return bool(self.raw_bucket)


class ReportingSettings(BaseSettings):
    """Reporting currency, timezone, and default attribution parameters."""

    model_config = SettingsConfigDict(extra="ignore")

    reporting_currency: str = Field(default="INR", alias="REPORTING_CURRENCY")
    reporting_tz: str = Field(default="Asia/Kolkata", alias="REPORTING_TZ")
    default_attribution_model: str = Field(
        default="M1",
        alias="DEFAULT_ATTRIBUTION_MODEL",
        pattern="^M[1-4]$",
    )
    default_lookback_days: Annotated[int, Field(ge=1, le=28)] = Field(
        default=7, alias="DEFAULT_LOOKBACK_DAYS"
    )


class Settings(BaseSettings):
    """Top-level settings aggregator. Use `get_settings()` everywhere."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    meta: MetaSettings = Field(default_factory=MetaSettings)
    mixpanel: MixpanelSettings = Field(default_factory=MixpanelSettings)
    redshift: RedshiftSettings = Field(default_factory=RedshiftSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    app_auth_method: str = Field(default="none", alias="APP_AUTH_METHOD")
    alert_slack_webhook: str = Field(default="", alias="ALERT_SLACK_WEBHOOK")
    alert_email_to: str = Field(default="", alias="ALERT_EMAIL_TO")


# ── Module-level singleton ────────────────────────────────────────────────────
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached settings singleton (reads .env once)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
