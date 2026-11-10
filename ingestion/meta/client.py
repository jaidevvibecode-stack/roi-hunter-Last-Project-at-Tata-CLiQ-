"""
ingestion/meta/client.py
-------------------------
Thin wrapper around the facebook-business SDK.
Initialises the SDK once; provides a session/API object to callers.

Never logs the access token.
Pins the Graph API version from config (DESIGN §3 item 10).
"""
from __future__ import annotations

import logging
from functools import lru_cache

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.api import FacebookAdsApi

from ingestion.common.config import MetaSettings, get_settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _init_api(api_version: str, access_token: str) -> FacebookAdsApi:
    """
    Initialise the Facebook SDK once per process.
    lru_cache ensures we don't re-initialise on repeated calls.
    """
    api = FacebookAdsApi.init(
        access_token=access_token,
        api_version=api_version,
    )
    log.info("Meta SDK initialised", extra={"api_version": api_version})
    return api


def get_api() -> FacebookAdsApi:
    """Return the initialised FacebookAdsApi singleton."""
    cfg: MetaSettings = get_settings().meta
    if not cfg.is_configured():
        raise RuntimeError(
            "Meta credentials not configured. "
            "Set META_ACCESS_TOKEN and META_AD_ACCOUNT_IDS in .env"
        )
    return _init_api(api_version=cfg.api_version, access_token=cfg.access_token)


def get_ad_account(account_id: str) -> AdAccount:
    """Return an AdAccount object. account_id may or may not have 'act_' prefix."""
    get_api()  # ensure initialised
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    return AdAccount(account_id)
