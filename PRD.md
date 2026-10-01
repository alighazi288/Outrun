# PRD: Wildfire evacuation for people who cannot leave alone

Source: `Wildfire_Evacuation_Project_Brief.pdf`, revised 2026-09-30 after review. Ali accepted the evaluation, scope, and safety changes below. Track: Government & Public Services.

## Problem and target user

Evacuation alerts assume people can leave once warned. Elderly and disabled residents often cannot. On the Eaton Fire, the costly failures were late warnings, blocked and congested roads, and too few vehicles and crews. Routing is one lever inside that problem.

**Primary user:** a county emergency manager running the response at night, with few vehicles, who must approve every dispatch.

**Secondary:** residents who need a ride (elderly, disabled, on oxygen, no car), plus dispatchers, drivers, and fire command. The MVP does not serve them with their own app.

**Proof event:** one case study, the Eaton Fire, which started at 6:18 p.m. on January 7, 2025. Plans use only information that existed at each moment. Results are ranges under stated assumptions. We do not claim we would have saved specific people.

## User stories

1. As an emergency manager, I want the fire outlook treated as an uncertain signal, with pessimistic rescue deadlines, so that a coarse wind model cannot send a van somewhere the fire might already be.
2. As an emergency manager, I want residents ranked with weights I can see on screen, so that the triage rule can be reviewed by an emergency manager or disability advocate.
3. As an emergency manager, I want routes that refuse any hex a vehicle cannot clear before fire could plausibly arrive, plus a margin, so that driver risk has a hard limit. People reachable only through that danger are escalated to fire command.
4. As an emergency manager, I want most residents to appear only after a help request and a delay, so that the plan works with partial information instead of a complete registry.
5. As an emergency manager, I want each recommendation explained in plain language, and a modeled delay before it counts as approved, so that a stressed reviewer is part of the result.
6. As an emergency manager, I want warning lead time first, then how much information, warning time, fleet size, and routing each change the outcome, so that I can see what to add, including how many vans it takes to reach 90% under the stated assumptions.



## Core MVP

One screen, one county, Eaton Fire case study, demo by **November 8** (the brief does not give the year).

The demo that proves the story:

- Replay clock steps through the night and serves only data issued or observed before that time.
- Every strategy, including ours, starts with the same partial registry. Ali's starting example is 25%. Everyone else becomes known only through a help request, after a delay.
- Fire nowcast gives, per map cell, the probability fire arrives within 1, 2, and 3 hours. Deadlines use the pessimistic side of that outlook.
- Synthetic residents (never real people) are ranked with visible weights. An IBM mentor review of those weights is part of the work. CMIST is a reference to consult, not a formula already chosen.
- OR-Tools plans routes for wheelchair vans, ambulances, and buses, re-plans on the replay clock, and obeys the driver-safety rule. A contract test fails the build if a route breaks it.
- Two or three Orchestrate agents, kept as YAML in the repo. They read messy help text, call the engines, and explain. They do not produce probabilities, deadlines, or routes.
- Alerts, if shown, are fixed human-written English and Spanish sentences. Blanks are filled with engine numbers.
- The manager approves or changes the plan. Evaluation includes approval delay in the sweep.
- The public demo is static playback of precomputed files, plus a backup video. A small live API covers tool calls, new help requests, a small re-plan, and approvals.



## What the result must show

Check these at the demo:

- **Lead result:** warning lead time, and how much of the outcome moves when you change information, warning time, fleet size, or routing.
- **Rescue bar:** a dispatcher heuristic, most urgent first, nearest suitable vehicle, given the same partial information. Report a range, under the swept assumptions.
- **Historical orders:** used for the warning-time comparison. They are not a rescue count. The rescues that actually happened are not something this model can recreate.
- **Two labeled plans,** both scored against the real fire's arrival window:
  - Upper bound: the planner can see the true fire path.
  - Realistic: the planner sees only our forecast.
- **Arrival window:** Cal Fire DINS (which buildings burned), NASA FIRMS detections, and the official timeline. A pickup counts only when it beats the earliest plausible arrival.
- **Sweeps:** fleet size, speed, loading time, and approval delay. Blocked roads and congestion enter as random closures and slower speeds. Publish the fleet-size curve, including how many vans reach 90% out under those assumptions.
- **Forecast label:** one-fire case study. Calibration and Brier score may be shown beside it. They are not a validated forecast.
- **Safety:** no accepted route enters a hex the vehicle cannot leave before plausible fire arrival, plus a margin. Danger-only stops are escalated to fire command.
- Many synthetic populations. Report the median and the range.



## Out of scope

- Live connection to real 911 or alert systems
- Real resident data
- A complete registry that only our system can see
- Counting historical rescues, or using zone-by-zone orders as the rescue bar
- A traffic simulation
- Multi-county data pipeline
- Full physics fire model (Cell2Fire or ELMFIRE). Bonus only if the nowcast owner is ahead in week 4
- Backtests on other fires, including Lahaina, unless Eaton is already solid
- Mobile app for residents
- Free LLM translation of alerts, and any alert copy a human has not written
- More than three agents
- LLM-produced probabilities, deadlines, or routes
- A single headline number of people saved



## Still unset

- The registry fraction, if 25% is only an example
- The help-request delay, the safety margin, and the numeric sweep grids
- Which two or three agents remain
- The mentor session is agreed and not yet booked



## Milestone

**November 8**, as written in the brief. Week 1 is done when each risky piece works on a small real example and the five data formats are agreed, including when a resident becomes known and how a route fails the safety rule.