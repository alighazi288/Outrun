# Outrun screenshots

These screenshots document an IBM Bob-assisted development session in the Outrun project. They show the project workspace, repository files, prompts and responses, and progress through planning and implementation. The images are preserved as captured; descriptions below are based on their filenames and visible session context, because the repository itself could not be opened to verify its structure.

## Screenshots

### Screenshot 1
IBM Bob verifies the `agents/intake.yaml` and `agents/dispatch.yaml` requirements and identifies `agents/import.sh` as the missing deliverable.

![Initial Outrun workspace session](Untitled.png)

### Screenshot 2
Continuation of the agent configuration review, showing the safety and tool-use requirements checked for both agent files.

![Early project exploration](Untitled%202.png)

### Screenshot 3
IBM Bob creates `agents/import.sh` with Orchestrate CLI commands and traces the Week 1 fire-outlook test path.

![Reviewing project files](Untitled%203.png)

### Screenshot 4
Compliance summary for the intake and dispatch agents, including permitted tools, number-handling rules, and human approval requirements.

![Planning and analysis](Untitled%204.png)

### Screenshot 5
Week 1 test trace: dispatch calls the fire-outlook tool and reports values directly from its output.

![Planning before implementation](Untitled%205.png)

### Screenshot 6
Dashboard planning begins after reviewing the README, OpenAPI spec, and source files; the session lists the replay, map, and dashboard files explored.

![Plan mode and project review](6.png)

### Screenshot 7
Dashboard audit showing existing React/Vite components, map layers, replay handling, and the features already implemented.

![Follow-up project work](7.png)

### Screenshot 8
Dashboard plan identifies operational gaps such as missing dependencies, replay data, potentially stale generated types, and layer checks.

![Implementation context](8.png)

### Screenshot 9
Five-step dashboard plan covering scaffold verification, type regeneration, replay export, layer audit, and end-to-end smoke testing; two scope questions remain.

![Outrun workspace progress](9.png)

### Screenshot 10
Satellite notebook planning begins, with source reuse and constants for the Eaton fire data identified alongside the dashboard package file.

![Implementation and review](10.png)

### Screenshot 11
Flowchart for the satellite notebook: configure, download VIIRS and GOES-18 data, validate, then create map, timeline, and summary outputs.

![Implementation and review](11.png)

### Screenshot 12
OR-Tools routing research summarizes reusable planner and safety-map code, plus routing invariants the tests must enforce.

![Implementation and review](12.png)

### Screenshot 13
Routing test contract and dependency-ordered plan for implementing `plan_routes_ortools`.

![Implementation and review](13.png)

### Screenshot 14
Six-step OR-Tools implementation flow, followed by design questions about optional dependency handling and solver time limits.

![Implementation and review](14.png)

### Screenshot 15
The routing plan's open design questions: behavior when OR-Tools is unavailable and whether the solver limit should be configurable.

![Implementation and review](15.png)

### Screenshot 16
Evaluation harness task prompt: build replay metrics and a CLI that runs seeded simulations and writes a CSV.

![Implementation and review](16.png)

### Screenshot 17
Evaluation research finds `evaluation/sweep.py` already contains the replay building blocks; a three-part plan covers metrics, CLI, and validation.

![Implementation and review](17.png)

### Screenshot 18
Evaluation harness plan details how replay timing, approval delay, vehicle movement, and resident pickup feed the metrics.

![Implementation and review](18.png)

### Screenshot 19
Fire-report migration plan: replace hardcoded report rows with CSV input and runtime geocoding, with explicit handling for failures and caching.

![Implementation and review](19.png)

### Screenshot 20
Three-step fire-report plan to create the CSV, rewrite the report builder, and validate that generated output matches existing results.

![Implementation and review](20.png)

### Screenshot 21
Editor view of `evaluation/forecast_check.py` alongside the fire-report plan, showing forecast scoring and geocoding decisions.

![Later Outrun project session](21.png)

## Suggested repository location

Add this folder as `docs/screenshots/` (or use the repository's existing documentation or screenshot directory if one exists). Keep the original filenames so the sequence remains intact.
