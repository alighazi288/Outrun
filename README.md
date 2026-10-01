# Outrun

A county emergency manager, during the Eaton Fire replay, sees where the fire is likely to go, who cannot leave alone, which vehicle should go where, and why. The manager approves or changes every dispatch.

The demo plays back precomputed files. The result is warning lead time, and how much information, warning time, fleet size, and routing each change the outcome. Figures are ranges under stated assumptions.

Spec: `PRD.md`, `ARCHITECTURE.md`, `TEAM.md`.

Board: [Eaton Evacuation MVP](https://trello.com/b/L12ru6Ut/eaton-evacuation-mvp).

Demo date: November 8. The brief does not give the year.

## Layout

| Path | What goes here |
|---|---|
| `backend/` | FastAPI replay clock and OpenAPI tools |
| `agents/` | watsonx Orchestrate agent YAML |
| `engines/` | Fire nowcast, risk, and route optimizer |
| `dashboard/` | React map. The judged demo plays saved frames |
| `evaluation/` | Dispatcher heuristic, sweeps, and the arrival window |
| `data/raw/` | Downloads. Not committed |
| `data/processed/` | Small files the playback and the score use |
| `bob_sessions/` | IBM Bob session screenshots |
| `DATA_SOURCES.md` | Every public site used, with attribution |

Residents are synthetic. Probabilities, deadlines, and routes come from the engines. Agents explain those results.
