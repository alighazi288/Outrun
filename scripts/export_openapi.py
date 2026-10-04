"""Write the API contracts:

- backend/openapi.json: the full API, for the dashboard (OpenAPI 3.1, as FastAPI writes it)
- agents/tools.openapi.json: the agent tools only, for `orchestrate tools import`
  (OpenAPI 3.0, pointed at the public API; see backend/api/tools_spec.py)

    uv run python scripts/export_openapi.py        # or: make openapi

Re-run whenever an endpoint or schema changes, and commit the result.
"""

from __future__ import annotations

import json

from backend.api.main import create_app
from backend.api.tools_spec import agent_tools_spec
from backend.store import REPO_ROOT

if __name__ == "__main__":
    spec = create_app().openapi()
    full = REPO_ROOT / "backend" / "openapi.json"
    full.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Wrote {full} ({len(spec['paths'])} paths)")

    tools = agent_tools_spec(spec)
    out = REPO_ROOT / "agents" / "tools.openapi.json"
    out.write_text(json.dumps(tools, indent=2) + "\n")
    names = sorted(op["operationId"] for ops in tools["paths"].values() for op in ops.values())
    print(f"Wrote {out} (OpenAPI {tools['openapi']}, server {tools['servers'][0]['url']}, "
          f"tools: {', '.join(names)})")
