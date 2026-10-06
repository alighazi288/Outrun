"""The tool menu Orchestrate imports meets its rules: OpenAPI 3.0, one server, every tool named
and described, no 3.1-only keywords left."""

from __future__ import annotations

import json

import pytest

from backend.api.main import create_app
from backend.api.tools_spec import AGENT_TOOLS, agent_tools_spec
from backend.store import REPO_ROOT


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    app = create_app(log_path=tmp_path_factory.mktemp("log") / "log.jsonl")
    return agent_tools_spec(app.openapi(), public_url="https://example.test")


def _ops(spec):
    return [op for ops in spec["paths"].values() for op in ops.values()]


def test_openapi_30_with_one_server(tools):
    assert tools["openapi"].startswith("3.0")
    assert tools["servers"] == [{"url": "https://example.test"}]


def test_exactly_the_agent_tools_each_described(tools):
    assert {op["operationId"] for op in _ops(tools)} == AGENT_TOOLS
    for op in _ops(tools):
        assert op.get("description"), f"{op['operationId']} needs a description"


def test_no_openapi_31_keywords_left(tools):
    text = json.dumps(tools)
    assert '"type": "null"' not in text
    assert '"const"' not in text


def test_every_reference_resolves(tools):
    names = set(tools["components"]["schemas"])
    for ref in json.dumps(tools).split('"$ref": "#/components/schemas/')[1:]:
        assert ref.split('"', 1)[0] in names


def test_committed_file_is_up_to_date(tools, tmp_path):
    """agents/tools.openapi.json must match the code. If this fails: make openapi."""
    committed = json.loads((REPO_ROOT / "agents" / "tools.openapi.json").read_text())
    app = create_app(log_path=tmp_path / "log.jsonl")
    assert committed == agent_tools_spec(app.openapi(), public_url=committed["servers"][0]["url"])
