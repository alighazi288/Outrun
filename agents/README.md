# agents/: watsonx Orchestrate agents (built with Bob)

Agent definitions live here as ADK YAML files, because **IBM closes the cloud
account when the program ends.** Git is the only copy that survives.

## The core rule

**Agents never produce numbers.** Every probability, deadline, ETA and route comes from an engine
through an API tool. Agents read messy input, call tools, and explain results. If an agent needs a
number it doesn't have, it calls a tool; if no tool has it, it says so.

## Two agents

Both run on `groq/openai/gpt-oss-120b`, Orchestrate's default and IBM's recommended model for the
`react_core` agent style. IBM Granite 4 (`watsonx/ibm/granite-4-h-small`) is in our instance, but
failed a plain help request in that style (Oct 4), so the model line stays swappable.

| Agent | Job | Tools (operationIds in `agents/tools.openapi.json`) |
|---|---|---|
| **Dispatch** (the manager's entry point) | Explains the plan and the fire situation using tool outputs only. Flags escalations (`unreachable`). Asks the manager to approve or change the plan and records the answer. **Never records `approve` on its own.** | `get_fire_outlook`, `get_residents_at_risk`, `get_vehicle_runs`, `get_current_plan`, `record_decision`, `list_decisions` |
| **Intake** (Dispatch's collaborator) | Turns messy text into validated records: help requests ("my dad's on oxygen, 2nd floor") and fire reports ("flames behind the houses on Mariposa"). Asks a follow-up if location or needs are unclear. The backend fills in every number. | `submit_help_request`, `submit_fire_report` |

Why only two:
- Help requests and fire reports are one job (text → record) with two record types.
- Alerts are code (below).
- Add a supervisor only if Orchestrate needs one to route between the two.

## Alerts are code, not AI

Public alerts are fixed English and Spanish sentences written and reviewed by people (Spanish
reviewed by a fluent speaker), with blanks filled from engine numbers. They're formatted as CAP
(Common Alerting Protocol) with status **Draft**, and a human sends them. This is a stretch item for
week 5, if we're ahead.

## Connecting Orchestrate to our backend

Orchestrate calls our API over the internet, so the API needs a public URL. It runs on Render's free tier, set up by `render.yaml`. A Cloudflare quick tunnel
(`cloudflared tunnel --url http://localhost:8000`) is for development ONLY.

Orchestrate imports `agents/tools.openapi.json`, not `backend/openapi.json`: it needs OpenAPI 3.0,
one server URL and a description per endpoint, and only the agent tools. `make openapi` writes it
(`backend/api/tools_spec.py`).

```bash
make openapi                                      # refresh agents/tools.openapi.json
uv tool install ibm-watsonx-orchestrate           # the `orchestrate` CLI (ADK)
set -a; source .env; set +a                       # WXO_INSTANCE_URL, WXO_API_KEY from .env
orchestrate env add -n outrun -u "$WXO_INSTANCE_URL" --type ibm_iam
orchestrate env activate outrun --api-key "$WXO_API_KEY"
orchestrate tools import -k openapi -f agents/tools.openapi.json
orchestrate agents import -f agents/intake.yaml
orchestrate agents import -f agents/dispatch.yaml
```

## Agent files

- `intake.yaml`: `outrun_intake`. Passes addresses, never coordinates or times; the backend looks
  them up (`backend/geocode.py`, US Census geocoder) and returns errors that say what to ask.
- `dispatch.yaml`: `outrun_dispatch`, with Intake as collaborator (import Intake first). Reads
  `get_vehicle_runs` for runs in progress and `get_current_plan` for new assignments.

Check a file offline before importing (uses the ADK's own validator):

```bash
~/.local/share/uv/tools/ibm-watsonx-orchestrate/bin/python -c "from ibm_watsonx_orchestrate.agent_builder.agents import Agent; print(Agent.from_spec('agents/dispatch.yaml').name)"
```

The IBM login from `env activate` lasts about an hour; run it again when a command says the token
expired.

## How the agents are tested

- No AI runs inside the evaluation runs.
- **Intake** is tested by comparing its output on the real published fire-report text against hand-checked records, field by field.
- **Dispatch** is tested by an automatic check that every number in its explanations appears in the tool outputs.