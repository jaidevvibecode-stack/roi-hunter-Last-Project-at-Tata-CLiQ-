"""Print pip requirements for one pyproject extra (or the base set) — lets Dockerfiles install dependencies
without installing the project itself (the services read ./config relative to the repo root).
  python scripts/print_requirements.py api > /tmp/req.txt
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

here = Path(__file__).resolve().parent
pyproject = next(p for p in (here / "pyproject.toml", here.parent / "pyproject.toml") if p.exists())  # repo layout or Docker layout
proj = tomllib.loads(pyproject.read_text())["project"]
extra = sys.argv[1] if len(sys.argv) > 1 else ""
SELF = proj["name"]


def expand(name: str, seen: set[str]) -> list[str]:
    out: list[str] = []
    for req in proj.get("optional-dependencies", {}).get(name, []):
        if req.startswith(SELF + "["):  # self-reference to other extras
            for e in req[len(SELF) + 1 : -1].split(","):
                if e not in seen:
                    seen.add(e)
                    out += expand(e, seen)
        else:
            out.append(req)
    return out


reqs = list(proj["dependencies"]) + (expand(extra, {extra}) if extra else [])
print("\n".join(dict.fromkeys(reqs)))
