"""Write the API's OpenAPI schema to frontend/openapi.json (no server needed). Used by `npm run gen:api` and CI."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ENV", "local")
os.environ.setdefault("DATA_SOURCE", "demo")


def build() -> str:
    from backend.main import create_app

    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    out = ROOT / "frontend" / "openapi.json"
    out.write_text(build())
    print(f"wrote {out.relative_to(ROOT)}")  # noqa: T201
