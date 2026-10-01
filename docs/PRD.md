# PRD: Wildfire evacuation for people who cannot leave alone

Source: `Wildfire_Evacuation_Project_Brief.pdf`, revised 2026-09-30 after review. Ali accepted the evaluation, scope, and safety changes below. Updated 2026-10-01 with the official Eaton investigations and Ali's answers to "Still unset"; the full rules are in `docs/EVAL_SPEC.md`. Track: Government & Public Services.

## Problem and target user

Evacuation alerts assume people can leave once warned. Elderly and disabled residents often cannot. On the Eaton Fire, the costly failures were warnings that came hours after the first fire reports, blocked and congested roads, and too few vehicles and crews. Routing is one lever inside that problem.

What the record shows (sources in `DATA_SOURCES.md`):

- High winds grounded all aircraft at 6:45 p.m., 27 minutes after ignition. Responders lost their real-time view of the fire.
- Fire was reported west of Lake Avenue from late evening, including at least 10 reports on the western flank between 11:18 p.m. and 12:17 a.m.
- The first VIIRS satellite detection of the fire came at 1:30 a.m. Orders for west Altadena came at 3:25 a.m. All 17 deaths were west of Lake Avenue.
- The official reviews disagree on whether the orders were late. One measures from the main fire front, which crossed Lake Avenue around 5:13 a.m. The other measures from the first fire activity. Both hold by their own definition: decisions tracked the front while embers burned homes ahead of it. We say: orders for west Altadena came at 3:25 a.m., hours after the first fire reports west of Lake Avenue. We present evidence, not blame.

**Primary user:** a county emergency manager running the response at night, with few vehicles, who must approve every dispatch.

**Secondary:** residents who need a ride (elderly, disabled, on oxygen, no car, living in care facilities), plus dispatchers, drivers, and fire command. The MVP does not serve them with their own app.

**Proof event:** one case study, the Eaton Fire, which started at 6:18 p.m. on January 7, 2025. Plans use only information that existed at each moment. Results are ranges under stated assumptions. We do not claim we would have saved specific people.

## User stories

1. As an emergency manager, I want the fire outlook treated as an uncertain signal, with pessimistic rescue deadlines, so that a coarse wind model cannot send a van somewhere the fire might already be.
2. As an emergency manager, I want residents ranked with weights I can see on screen, so that the triage rule can be reviewed by an emergency manager or disability advocate.
3. As an emergency manager, I want routes that refuse any hex a vehicle cannot clear before fire could plausibly arrive, plus a margin, so that driver risk has a hard limit. People reachable only through that danger are escalated to fire command.
4. As an emergency manager, I want most residents to appear only after a help request and a delay, so that the plan works with partial information instead of a complete registry.
5. As an emergency manager, I want each recommendation explained in plain language, and a modeled delay before it counts as approved, so that a stressed reviewer is part of the result.
6. As an emergency manager, I want warning lead time first, then how much information, warning time, fleet size, and routing each change the outcome, so that I can see what to add, including how many vans it takes to reach 90% under the stated assumptions.
7. As an emergency manager, I want fire reports from calls and radio on the map and in the forecast, so that I can see fire ahead of the main front when aircraft cannot fly and satellites have not passed.

## Core MVP

One screen, one county, Eaton Fire case study, demo by **November 8** (we submit November 6).

The demo that proves the story:

- Replay clock steps through the night and serves only data issued, observed, or reported before that time.
- **Who is known.**
  - Every strategy, including ours, starts with the same partial registry: residents of real licensed care facilities, plus 25% of everyone else. The 25% is an assumption; we also run 0, 50, and 100%.
  - Everyone else becomes known only through a help request. A request is triggered by the earlier of a real order covering their home or the first published fire report or detection within 2 km, plus a random delay of up to 60 minutes. The planner sees it 15 minutes later, at least one replay step.
  - The rule never uses the true fire arrival or our own forecast.
- **Fire nowcast** gives, per map cell, the probability fire arrives within 1, 2, and 3 hours. It is built from published fire reports, satellite detections (VIIRS, and GOES if it covers the night), and wind as issued, with downwind embers. Deadlines use the pessimistic side of that outlook (`arrival_p10_min`).
- **Residents are never real people.** Care facilities come from public licensing data (location and licensed capacity). Everyone else is sampled from Census counts into real building footprints. They are ranked with visible weights. An IBM mentor review of those weights is part of the work. CMIST is a reference to consult, not a formula already chosen.
- **OR-Tools** plans routes for wheelchair vans, ambulances, and buses, re-plans on the replay clock, and obeys the driver-safety rule:
  - For every hex a vehicle occupies, the time it leaves plus a 30-minute margin must not pass that hex's `arrival_p10_min`. The 30 minutes is an assumption; we also test 15 and 45.
  - A contract test fails the build if a route breaks the rule.
- **Two Orchestrate agents,** kept as YAML in the repo:
  - Intake turns help requests and fire reports into records.
  - Dispatch explains the plan and waits for approval.

  They do not produce probabilities, deadlines, or routes.
- Alerts, if shown, are fixed human-written English and Spanish sentences. Blanks are filled with engine numbers.
- The manager approves or changes the plan. Evaluation includes approval delay in the sweep.
- Every assumed number lives in one file (`backend/assumptions.py`), labeled with its source or "placeholder" and the range we test. All settings freeze **October 18**, before any run on real data.
- The public demo is static playback of precomputed files, plus a backup video. A small live API covers tool calls, new help requests and fire reports, a small re-plan, and approvals.

## What the result must show

Check these at the demo:

- **Lead result:** warning lead time, and how much of the outcome moves when you change information, warning time, fleet size, or routing.
- **Rescue bar:** a dispatcher heuristic, most urgent first, nearest suitable vehicle, given the same partial information and the same safety rule. Report a range, under the swept assumptions.
- **Historical orders:** used for the warning-time comparison. They are not a rescue count. The rescues that actually happened are not something this model can recreate.
- **Warning precision:** each warning-time comparison also shows how many warned places the fire actually reached, so warning everyone early does not win.
- **Two labeled plans,** both scored against the real fire's arrival window:
  - Upper bound: the planner can see the true fire path.
  - Realistic: the planner sees only our forecast.
- **Arrival window:** per hex, from Cal Fire DINS (which buildings burned), satellite detections, the published report timelines, and the official order timeline. A pickup counts only when it beats the earliest plausible arrival.
- **Sweeps:** one lever at a time around a baseline, plus a "bad night" and a "good night" with every lever at its pessimistic or optimistic end.
  - Baseline: 10 vehicles (4 wheelchair vans, 4 ambulances, 2 buses), half normal road speed, placeholder loading times, 5-minute approval.
  - Values:
    - fleet 2, 5, 10, 20, 40, 80
    - speed 0.25, 0.5, 0.75
    - loading half and double
    - approval 0, 5, 10, 20 minutes
    - registry and help-request settings
    - random closures 0, 5, 10%
    - margin 15, 30, 45
  - 30 synthetic populations per setting, about 2,200 runs.
- **Fleet-size curve:** at 25% and 100% registry, with extra points where it crosses 90%. At 25% it may never reach 90%, because vans cannot rescue people nobody knows about. That is a finding.
- **Forecast label:** one-fire case study. Calibration and Brier score may be shown beside it. They are not a validated forecast.
- **Safety:** no accepted route enters a hex the vehicle cannot leave before plausible fire arrival, plus the margin. Danger-only stops are escalated to fire command.
- Many synthetic populations. Report the median and the range.

## Out of scope

- Live connection to real 911 or alert systems
- Real resident data, real addresses, or 911 records
- A complete registry that only our system can see
- Counting historical rescues, or using zone-by-zone orders as the rescue bar
- A traffic simulation
- Multi-county data pipeline
- Full physics fire model (Cell2Fire or ELMFIRE). Bonus only if the nowcast owner is ahead in week 4
- Backtests on other fires, including Lahaina, unless Eaton is already solid
- Mobile app for residents
- Free LLM translation of alerts, and any alert copy a human has not written
- A third agent, unless a job is named that is not intake or dispatch
- LLM-produced probabilities, deadlines, or routes
- A single headline number of people saved

## Settled on October 1

Proposed by Ali in `docs/EVAL_SPEC.md`. Each value is labeled as an assumption and swept.

- **Registry fraction:** 25% as the main case, plus 0, 50, and 100%. Care-facility residents are always known.
- **Help-request delay:** a trigger (real order or published report or detection within 2 km), plus up to 60 minutes, plus 15 minutes before the planner sees it.
- **Safety margin:** 30 minutes against `arrival_p10_min`.
- **Sweep grids:** one lever at a time, plus two combined scenarios and the fleet-size curve.
- **Agents:** two, Intake and Dispatch.

## Still unset

- The mentor session is agreed and not yet booked. It should cover the margin, the approval delay, and the triage weights.
- Whether GOES detections cover the night over west Altadena
- How precisely the published fire reports can be located
- Real sources for the placeholders: fleet size, loading times, speed in smoke

## Milestone

**November 8**, as written in the brief. We submit **November 6**.

| Date | Gate |
|---|---|
| Week 1 | Each risky piece works on a small real example, and the data formats are agreed, including when a resident becomes known and how a route fails the safety rule |
| October 11 | The whole night replays on real data. Nothing judges see uses fake data after this |
| October 18 | The full loop runs with a human approving. All settings freeze |
| November 1 | Feature freeze |
| November 6 | Submit |
