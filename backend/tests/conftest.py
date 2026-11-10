from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.settings import get_settings
from backend.main import create_app


@pytest.fixture
def window() -> str:
    end = date.today() - timedelta(days=1)
    return f"start_date={end - timedelta(days=29)}&end_date={end}"


@pytest.fixture
def client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())
