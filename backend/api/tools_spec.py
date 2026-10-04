"""The tool menu watsonx Orchestrate imports: our API's OpenAPI spec, trimmed for the agents.

Orchestrate turns each endpoint into a tool (the operationId is the tool name). It requires
OpenAPI 3.0, exactly one server URL, and a description on every endpoint. FastAPI writes
OpenAPI 3.1, so `agent_tools_spec` converts it:

- keeps only the endpoints the agents use (AGENT_TOOLS), plus the schemas they reference
- points `servers` at the public API
- rewrites the few 3.1-only pieces into 3.0: "X or null" becomes `nullable: true`,
  `const` becomes a one-value `enum`, numeric `exclusiveMinimum` becomes the 3.0 form,
  and a list of `examples` becomes one `example`
"""

from __future__ import annotations

import copy
import os

# The live API on Render (render.yaml)
PUBLIC_API_URL = "https://outrun-api.onrender.com"

# Tools the agents may call (agents/README.md). The clock, raw state and health stay out:
# agents describe the moment the manager is looking at, they don't move time.
AGENT_TOOLS = {
    "get_fire_outlook",
    "get_residents_at_risk",
    "get_current_plan",
    "record_decision",
    "list_decisions",
    "submit_help_request",
    "submit_fire_report",
}


def agent_tools_spec(spec: dict, public_url: str | None = None) -> dict:
    """OpenAPI 3.0 spec with only the agent tools, ready for `orchestrate tools import`."""
    out = copy.deepcopy(spec)
    out["openapi"] = "3.0.3"
    out["servers"] = [{"url": public_url or os.environ.get("OUTRUN_PUBLIC_URL") or PUBLIC_API_URL}]
    out["paths"] = {}
    for path, ops in spec["paths"].items():
        kept = {m: copy.deepcopy(op) for m, op in ops.items() if op["operationId"] in AGENT_TOOLS}
        if kept:
            out["paths"][path] = kept
    used = _referenced_schemas(out["paths"], spec["components"]["schemas"])
    out["components"] = {"schemas": {k: v for k, v in out["components"]["schemas"].items()
                                     if k in used}}
    return _to_30(out)


def _referenced_schemas(node: object, schemas: dict) -> set[str]:
    """Names of every schema reachable from `node` through $ref."""
    found: set[str] = set()
    todo = [node]
    while todo:
        n = todo.pop()
        if isinstance(n, dict):
            ref = n.get("$ref", "")
            name = ref.rsplit("/", 1)[-1]
            if ref.startswith("#/components/schemas/") and name not in found:
                found.add(name)
                todo.append(schemas[name])
            todo.extend(n.values())
        elif isinstance(n, list):
            todo.extend(n)
    return found


def _to_30(node: object) -> object:
    """Rewrite OpenAPI 3.1 schema keywords into their 3.0 equivalents, recursively."""
    if isinstance(node, list):
        return [_to_30(x) for x in node]
    if not isinstance(node, dict):
        return node
    node = {k: _to_30(v) for k, v in node.items()}

    options = node.get("anyOf")
    if isinstance(options, list) and {"type": "null"} in options:
        rest = [o for o in options if o != {"type": "null"}]
        del node["anyOf"]
        if len(rest) == 1 and "$ref" in rest[0]:
            node["allOf"] = rest  # in 3.0, keys next to a $ref are ignored, so wrap it
        elif len(rest) == 1:
            node = {**rest[0], **node}
        else:
            node["anyOf"] = rest
        node["nullable"] = True
    if "const" in node:
        node["enum"] = [node.pop("const")]
    for key, bound in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        if isinstance(node.get(key), int | float) and not isinstance(node[key], bool):
            node[bound] = node[key]
            node[key] = True
    if isinstance(node.get("examples"), list) and "type" in node:
        examples = node.pop("examples")
        if examples:
            node["example"] = examples[0]
    return node
