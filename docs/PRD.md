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
- **Who is known.** Same rule for every strategy.
  - Residents of real licensed care facilities are known from the start. The list is state licensing data.
  - Estimated residents come from Census counts. We do not publish one registry rate for them. The result is the curve at 0, 25, 50, and 100% pre-registered, and each point is labeled as an assumption. 25% is a point on that curve.
  - Estimated residents who are not in that share become known only through a help request. The request is created at the earlier of a real order covering their home, or the first published fire report within 2 km, plus a random wait of 0 to 60 minutes. The planner sees it after a 15-minute handling delay, at least one replay step. Satellite detections stay in the nowcast. They do not create the request.
  - The rule never uses the true fire arrival or our own forecast. In the live demo, typed help requests are examples and are labeled that way, because 911 records are not public at that detail.
- **Fire nowcast** gives, per map cell, the probability fire arrives within 1, 2, and 3 hours. It is built from published fire reports, satellite detections (VIIRS, and GOES if it covers the night), and wind as issued, with downwind embers. Deadlines use the pessimistic side of that outlook (`arrival_p10_min`).
- **Residents are never real people.** Care facilities come from public licensing data (location and licensed capacity). Everyone else is sampled from Census counts into real building footprints. They are ranked with visible weights. An IBM mentor review of those weights is part of the work. CMIST is a reference to consult, not a formula already chosen.
- **OR-Tools** plans routes for wheelchair vans, ambulances, and buses, re-plans on the replay clock, and obeys the driver-safety rule:
  - For every hex a vehicle occupies, the time it leaves plus a 30-minute margin must not pass that hex's `arrival_p10_min`. The 30 minutes is an assumption; we also test 15 and 45.
  - A contract test fails the build if a route breaks the rule.
- **Two Orchestrate agents,** both on IBM Granite, kept as YAML in the repo:
  - Intake turns help requests and fire reports into records.
  - Dispatch explains the plan and waits for approval.

  They do not produce probabilities, deadlines, or routes. A third supervisor exists only if Orchestrate needs one to route between these two. Ali will confirm the Granite model name when he registers the instance.
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
  - 30 synthetic populations per setting. One setting at a time, plus a bad night and a good night, about 2,000 runs. The full cross product is about 420,000 settings, and we do not run it.
- **Fleet-size curve:** the six fleet sizes, at 25% and at 100% known, with extra points where the curve crosses 90%. At 25% it may never reach 90%, because vans cannot rescue people nobody knows about. That is a finding. The week-1 example of 50 fake residents and 5 vehicles is a router test. It is not this sweep.
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
- A third agent, unless Orchestrate requires a supervisor only to route between Intake and Dispatch
- LLM-produced probabilities, deadlines, or routes
- A single headline number of people saved

## Settled on October 2

Ali confirmed these. None of the rates below has a published source. Each is an assumption, and each is swept. The full rules are in `docs/EVAL_SPEC.md`.

- **Registry.** Care-facility residents are known from the start. For estimated residents, publish the curve at 0, 25, 50, and 100%. Do not publish 25% as the result.
- **Help requests.** Trigger: the earlier of an official order covering the home, or the first published fire report within 2 km. Then a random wait of up to 60 minutes (also test up to 30). Then a handling delay of 15 minutes (also 5 and 30) before the planner sees it. Never-call rate: 0% at the hold point, also 10 and 25%. Trigger distance: also 1 and 3 km. The trigger is not the true arrival and not our forecast.
- **Safety.** For every hex on a route: time the vehicle leaves + 30 minutes ≤ `arrival_p10_min` from the forecast at plan time. Also test 15 and 45. The margin is in minutes. A hex with no forecast arrival within 3 hours stays open. The mentor can still change the 30 minutes. Until then, 30 is the hold point.
- **Sweeps.** Hold the other settings still: 10 vehicles (4 vans, 4 ambulances, 2 buses), 0.5× road speed, loading ×1, 5-minute approval. Try fleet {2, 5, 10, 20, 40, 80}, speed {0.25, 0.5, 0.75}, loading ×{0.5, 1, 2}, approval {0, 5, 10, 20} minutes, plus the registry, call, margin, and road-blockage ranges (blockages 0, 5, 10%). One setting at a time, plus one all-pessimistic night and one all-optimistic night. About 2,000 runs. The Eaton replay uses the Census-based population.
- **Agents.** Two: Intake and Dispatch, on IBM Granite. Alerts stay code. A supervisor is added only if Orchestrate cannot route between the two without one.

## Still unset

- The exact Granite model name. Ali checks it when he registers the Orchestrate instance.
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
