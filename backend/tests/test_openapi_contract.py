"""The frontend's generated API types must match the live API schema (run `npm run gen:api` after changing endpoints)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _build() -> str:
    spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "scripts" / "export_openapi.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.build()  # type: ignore[no-any-return]


def test_committed_openapi_matches_app():
    assert (ROOT / "frontend" / "openapi.json").read_text() == _build(), "run: cd frontend && npm run gen:api"


def test_every_route_has_a_declared_response_model():
    import json

    spec = json.loads(_build())
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            content = op["responses"]["200"]["content"]
            if "application/json" not in content:   # e.g. the streaming CSV export
                continue
            schema = content["application/json"]["schema"]
            assert schema != {} and "$ref" in schema, f"{method.upper()} {path} has no response model"


def test_generated_ts_types_cover_every_schema():
    import json

    ts = (ROOT / "frontend" / "lib" / "api-types.ts").read_text()
    for name in json.loads(_build())["components"]["schemas"]:
        if not name.startswith(("HTTPValidation", "Validation")):
            assert f"{name}: {{" in ts, f"{name} missing from frontend/lib/api-types.ts (run npm run gen:api)"
