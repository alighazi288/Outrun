"""Write backend/openapi.json: the API contract the dashboard and Orchestrate agents use.

    uv run python scripts/export_openapi.py
    # for Orchestrate, point the spec at the public API:
    OUTRUN_PUBLIC_URL=https://<your-host> uv run python scripts/export_openapi.py

Re-run whenever an endpoint or schema changes, and commit the result.
"""

from __future__ import annotations

import json

from backend.api.main import create_app
from backend.store import REPO_ROOT

if __name__ == "__main__":
    spec = create_app().openapi()
    out = REPO_ROOT / "backend" / "openapi.json"
    out.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Wrote {out} ({len(spec['paths'])} paths, servers={spec.get('servers')})")
