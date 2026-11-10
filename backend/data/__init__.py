from __future__ import annotations

from backend.core.settings import get_settings
from backend.data.base import DataSource


def get_source() -> DataSource:
    """FastAPI dependency: the configured data source."""
    if get_settings().data_source == "redshift":
        from backend.data.redshift_source import RedshiftDataSource

        return RedshiftDataSource()
    from backend.data.demo_source import get_demo_source

    return get_demo_source()
