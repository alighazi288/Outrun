# agents/: watsonx Orchestrate agents (built with Bob)

Agent definitions live here as ADK YAML files, because **IBM closes the cloud
account when the program ends.** Git is the only copy that survives.

## The core rule

**Agents never produce numbers.** Every probability, deadline, ETA and route comes from an engine
through an API tool. Agents read messy input, call tools, and explain results. If an agent needs a
number it doesn't have, it calls a tool; if no tool has it, it says so.

## Two agents

Both run on the same IBM Granite model in our Orchestrate instance.

| Agent | Job | Tools (operationIds in `backend/openapi.json`) |
|---|---|---|
| **Dispatch** (the manager's entry point) | Explains the plan and the fire situation using tool outputs only. Flags escalations (`unreachable`). Asks the manager to approve or change the plan and records the answer. **Never records `approve` on its own.** | `get_fire_outlook`, `get_residents_at_risk`, `get_current_plan`, `record_decision`, `list_decisions` |
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

```bash
OUTRUN_PUBLIC_URL=https://<public-host> uv run python scripts/export_openapi.py
pip install ibm-watsonx-orchestrate
orchestrate env add -n outrun -u <WXO_INSTANCE_URL>
orchestrate env activate outrun --api-key <WXO_API_KEY>
orchestrate tools import -k openapi -f backend/openapi.json
orchestrate agents import -f agents/intake.yaml
orchestrate agents import -f agents/dispatch.yaml
```

## Agent file sketch

Proposed but we need to verify the field names against the current ADK docs.

```yaml
spec_version: v1
kind: native
name: outrun_dispatch
description: Explains the evacuation plan to the emergency manager and records their decision.
instructions: >
  Always call tools before answering. Quote only numbers returned by tools; never estimate.
  Explain routes vehicle by vehicle with the reason given for each person, and list everyone in
  `unreachable` as needing escalation. Never call record_decision until the manager explicitly
  says approve, modify or reject.
llm: watsonx/ibm/<granite-model-available-in-our-instance>
style: default
collaborators:
  - outrun_intake
tools:
  - get_fire_outlook
  - get_residents_at_risk
  - get_current_plan
  - record_decision
  - list_decisions
```

## How the agents are tested

- No AI runs inside the evaluation runs.
- **Intake** is tested by comparing its output on the real published fire-report text against hand-checked records, field by field.
- **Dispatch** is tested by an automatic check that every number in its explanations appears in the tool outputs.