# Evaluation spec

How we prove Outrun works, and exactly what we will and won't claim. Every assumed number
lives in one file, `backend/assumptions.py`, with its status (sourced, from the brief, or
placeholder) and tested range; this document explains the rules around them.

**Freezes Oct 18,** before any run on real data (see §12).

---

## 1. What we claim, and what each claim rests on

| Claim | Rests on | Assumptions? |
|---|---|---|
| **A. What happened that night:** a timeline built from independent sources, showing where fire was reported, detected and confirmed west of Lake Avenue versus when orders went out, and who lived there | Published investigations, satellites, DINS, care-facility licensing, Census | None. All real records |
| **B. What was knowable:** using only data that existed at each moment, does our forecast flag the area before homes burned there? | Real fire reports, satellites and wind, scored against DINS + timelines | Only the forecast model itself, which is what's being tested |
| **C. What our dispatch would do:** ours vs. a dispatcher rule, under identical conditions | Real roads, facilities and fire; simulated residents, calls and fleet | Yes, every one labeled and tested over a range (§6) |

We lead with A and B. C is the dispatch test: it shows the product's decisions are better than
a sensible human rule, across a range of conditions.

**Problem-statement wording.** Two official reviews disagree on whether the west Altadena orders
were late. The [county-commissioned Citygate investigation](https://recovery.lacounty.gov/2026/05/18/county-of-los-angeles-fire-department-releases-independent-investigation-findings-of-west-altadena-evacuation-decisions/)
says no, because they went out before the main fire front crossed Lake Avenue (~5:13 a.m.).
[FSRI](https://www.aol.com/news/fire-marched-toward-west-altadena-172627594.html) documents fire
activity in the area 4–6 hours before the orders. Both are right by their own definition:
decisions tracked the front while embers burned homes ahead of it. We say: **"Orders for west
Altadena came at 3:25 a.m., hours after the first fire reports west of Lake Avenue."** That's
true under every report. We present evidence and assign no blame.

## 2. Real vs. simulated

| Real (cited in `DATA_SOURCES.md`) | Simulated, labeled as such |
|---|---|
| Fire reports with times and places, from the published investigations | Homebound residents' exact homes (placed from Census counts; real addresses aren't public) |
| Satellite detections (VIIRS; GOES if it covers the night) | Their help calls (real 911 records are private) |
| Wind forecasts as issued (HRRR) | Fleet size, speeds, loading and approval times |
| Roads (OpenStreetMap) | |
| Evacuation order times and zones | |
| Licensed care facilities, locations and capacity | |
| Which buildings burned (DINS) | |
| Census counts of older, disabled and no-car residents | |

## 3. Ground truth: when fire reached each place

- **Per hex, not per building.** Building-level timing isn't knowable.
- **A hex is "reached"** if DINS shows any damaged structure in it, or a satellite detection lands
  within 375 m of its centre, or a published fire report locates fire in it.
- **Arrival is a window:** after the last observation showing the hex clear, and at or before the
  first evidence of fire there. Evidence comes from satellite passes, published report times and
  the DINS-validated times in the investigations.
- **Strict scoring (headline):** a pickup counts only if the vehicle left the hex before the
  window's **earliest** time. Lenient scoring (latest time) is reported as secondary.

## 4. Who the planner knows about (`backend/knowledge.py`)

| Group | Known from | Rule |
|---|---|---|
| Care-facility residents | the start | Real licensed facilities: a real, public list |
| Estimated residents on a list | the start | `FRACTION_KNOWN` of them, drawn at random, independent of location and fire. The published result is the curve at 0, 25, 50, and 100%. 25% is the hold point for other sweeps, not the number we claim |
| Everyone else | their help call | trigger = earlier of (a) a real warning/order covering their home or (b) the first published fire report within `TRIGGER_KM` (not a satellite detection, and not our forecast); call = trigger + uniform(0, `CALL_DELAY_MAX_MIN`); planner sees it `HANDLING_DELAY_MIN` later; `NEVER_CALL` of them never call |

Why not the obvious alternatives:
- **A fixed time** ignores the fire.
- **A purely random time** has the same problem.
- **A threshold on our own risk score** would let a better forecast make people knowable sooner, which mixes the information lever with the forecast lever.
- **The true fire arrival** would decide who was knowable from where the fire actually went. That's hindsight.

The rule uses only records published by the trigger time, and `tests/test_knowledge.py` checks
this for every call. People who never become known still count in the denominator if the fire
reached them. Live help requests in the demo (`POST /requests`) are separate, labeled as examples, and also become
visible only after the handling delay.

## 5. Driver safety: one rule, one margin

For every hex a vehicle occupies (stops and the hexes between them):

**time the vehicle leaves + `SAFETY_MARGIN_MIN` ≤ that hex's `arrival_p10_min`** (forecast at plan time)

- `arrival_p10_min` is when the chance of fire reaches 10%. So this *is* a probability cutoff, written as a time: at most a 10% chance that fire arrives within the margin after the vehicle leaves. The time form matches route schedules, which are in minutes.
- The margin is in minutes, not hexes, because fire speed varies with wind.
- Burning hexes are never entered. Hexes with no forecast arrival within 3 h are open.
- The pickup deadline is this same rule at the pickup hex: deadline = `arrival_p10_min − margin` = the latest time to *leave*.
- No pickup unless a safe way out to a shelter exists afterwards.
- Anyone reachable only through danger goes to `unreachable` with "Escalate to fire command."
- Hexes between stops follow the straight line until the road router reports real paths.
- Enforced for every planner by `tests/test_engines.py::test_router_driver_safety`, which fails the build on an unsafe route.
- The 30-min margin is an assumption: we test 15, 30 and 45 min, and ask an emergency manager.
  We also run one check at the 5th percentile instead of the 10th.

## 6. The dispatch test (claim C)

**Planners.** All share the same forecast, deadlines, safety rule, capacities, information,
approval delay and 10-minute re-planning. They differ only in who goes where.
- **Ours.** Stub(closest first). OR-Tools pickup-and-delivery by the Oct 18 freeze.
- **Dispatcher rule** (`plan_routes_dispatcher` in `engines/routing.py`). Each free vehicle goes to the most urgent person (earliest deadline) it can carry and reach safely; nearest breaks ties. This is the bar to beat.
- **Closest first** (the `plan_routes` stub). The weaker baseline, run at the baseline settings only.
- A vehicle's current leg is never interrupted, for any planner. This comes in with vehicle movement.

**Fire modes, baseline only:**
- **forecast:** realistic.
- **true fire path:** the planner gets each hex's earliest real arrival as certain. It's the upper bound and isolates routing. Requests still follow §4.

**Approval delay.** A plan made at t takes effect at t + delay. Until then, vehicles follow the
last approved plan. If a stop fails the safety rule under the latest forecast when the plan takes
effect, it's skipped and escalated.

**Settings** (one at a time around the baseline; values in `assumptions.py`):

| Setting | Baseline | Tested |
|---|---|---|
| Fleet (40% wheelchair vans, 40% ambulances, 20% buses, rounded, ≥1 van and ≥1 ambulance) | 10 (4/4/2) | 2, 5, 10, 20, 40, 80 |
| Speed (× normal road speed) | 0.5 | 0.25, 0.5, 0.75 |
| Loading times (placeholders until sourced) | ×1 | ×0.5, ×1, ×2 |
| Approval delay | 5 min | 0, 5, 10, 20 min (0 = instant, best case) |
| % of estimated residents known in advance | 25% | 0, 25, 50, 100% |
| Never call | 0% (optimistic) | 0, 10, 25% |
| Call delay after trigger | up to 60 min | up to 30, up to 60 min |
| Call handling delay | 15 min | 5, 15, 30 min |
| Call trigger distance | 2 km | 1, 2, 3 km |
| Road blockages (known to all planners; needs the road network) | 0% | 0, 5, 10% |
| Safety margin | 30 min | 15, 30, 45 min |

- **Why one at a time:** every combination is about 420,000 settings. We change one setting at a time around the baseline. That is the table above, not the full grid. Untested interactions are a stated limitation.
- **Combined scenarios:** "bad night" (every setting at its pessimistic end) and "good night"
  (every setting at its optimistic end) bound the best and worst case.
- **Fleet curve:** run at 25% and 100% known. At 25% it may flatten below 90%, because vans can't
  rescue people nobody knows about. If so, that's a finding. "Vehicles needed for 90%" is read from
  the 100% curve: the smallest fleet where the median population gets ≥ 90% out. Extra points are
  added where the curve crosses 90%. A 0% curve is added if timing allows.
- **Runs.** About 2,000 in total:
  - 34 settings × 2 planners × 30 populations
  - closest-first and the true-fire-path mode at baseline
  - the 5th-percentile check

  Every run uses the same optimizer time limit. We time one replay in week 2.

**The week-1 example** (50 fake residents, 5 vehicles) is the brief's development test for the
router, not part of the evaluation. The test runs on the real Eaton replay.

## 7. Metrics

- **Headline (claim C):** of the vulnerable residents in hexes the fire reached, the share picked up
  before the earliest plausible arrival.
  - One per resident record. Carers ride along but aren't counted.
  - `none` needs are excluded.
- **Warning lead time (claim B):** earliest arrival minus warning time, compared for (a) real orders,
  (b) a zone-by-zone rule (order a zone when the first published report or detection is within
  2 km), and (c) our first at-risk flag (3-hour fire chance ≥ 10%). Each comes with its
  **precision**, the share of warned hexes the fire actually reached; otherwise "warn everyone at
  18:20" would win. West Altadena is reported separately.
- **Also reported:**
  - time to first dispatch, from fleet activation
  - vehicle utilization
  - escalations, and how many of those the fire reached
  - **driver exposure:** vehicle-minutes in hexes the real fire reached within the margin after the vehicle left (target 0)
  - false-alarm pickups (hexes the fire never reached)

## 8. Forecast scoring (claim B)

- Scored at each step, for horizons 1, 2 and 3 h, for every hex not yet burning:
  - outcome 1 if the arrival window ends before t + h
  - outcome 0 if it starts after t + h, or the hex is never reached
  - excluded if the window straddles t + h, with the excluded count reported
- Reported: Brier score per horizon, a calibration curve, and skill vs. the simple 2-km distance rule.
- **No parameters fitted on Eaton outcomes.** They come from published values or other fires, or are re-fitted at each t using only evidence visible by t.
- The Palisades Fire (same night, same data sources) is an out-of-sample check if time allows.

## 9. Population and world

- **Evaluated:** wheelchair users, people on oxygen, bedbound people, people with no car.
- **Care-facility residents:** licensed capacity per facility (state data), with a needs mix from published facility-type averages or a labeled assumption.
- **Estimated residents:** placed into real building footprints from Census tract counts. Rachel proposes the Census-to-needs mapping table with sources by Oct 11. Oxygen and bedbound aren't in Census data, so those shares need a cited source or are labeled assumptions.
- **Study area:** the Altadena community boundary + 1 km, not the burn perimeter, so it includes places the fire never reached.
- **Fleet activation:** at 6:48 p.m., the first real alert per the county review, the same for every planner (assumption).
- **Depots:** two, outside the study area, with vehicles split evenly (assumption).
- **Shelters:** real shelter locations from public reporting; capacity not binding.
- **Crews:** one per vehicle, no shift limits.

## 10. Statistics

- A seed fixes the population, who is on a list, and call behaviour. Every planner and every
  setting uses the same seeds (paired), and `knowledge.py` draws the same random numbers per
  resident, so changing one setting doesn't reshuffle anyone else.
- 30 populations per setting.
- Reported: the median and 5th–95th percentile, plus the paired difference ours − dispatcher (its median, and the share of populations where ours wins).
- The forecast's internal randomness has its own fixed seed.

## 11. Agents

- **Two agents:** Intake and Dispatch, both on IBM Granite. A supervisor is added only if Orchestrate needs one to route between them. The model name is confirmed when the instance is registered.
- **No AI runs inside the evaluation.**
  - Fire reports enter as records structured by hand from the published timelines and checks by hand.
  - Simulated calls enter as records.
- **Intake** is tested separately by comparing its output on the real published report text against the hand-checked records, field by field.
- **Dispatch** is tested by an automatic check that every number in its explanations appears in the tool outputs.

## 12. Freeze rule

- Everything in this spec and in `assumptions.py`, plus all engine parameters, freezes **Oct 18**.
- Tuning happens only on the fake fixtures or other fires, never on Eaton results.
- Any later change is logged below with a reason, and results are shown both ways.

## 13. How we word results

> "Under stated assumptions, across 30 synthetic populations, X% (5–95%: a–b%) of vulnerable
> residents in areas the fire reached were picked up before its earliest plausible arrival,
> vs Y% for the dispatcher rule."

Never "lives saved". Never "would have saved" a specific person.

## 14. Limitations we state

- Interactions between settings are untested beyond the two combined scenarios.
- Humans never modify or reject plans in the replay.
- Residents don't react to our warnings, because calls use the real orders.
- Intake is assumed correct inside the replay; it's measured separately.
- It's one fire, so it's a case study.
- Building-level arrival times aren't knowable.

## 15. Open items

| Item | Owner | Due |
|---|---|---|
| Does GOES cover the night over west Altadena (22:00–03:25)? | Daniel | week 1 |
| Turn the FSRI and county timelines into `fire_reports.jsonl`. How precise are the locations? | Bhavaani (arrival window) | week 1 |
| DINS download; real order zones and times | Bhavaani | week 1 |
| Shelter locations | Rachel | week 1 |
| Care facilities in the study area (state licensing data) | Rachel (residents) | week 1 |
| Real anchors for fleet size (county reviews, paratransit fleets) | Bhavaani | Oct 11 |
| Published boarding times (wheelchair, stretcher); smoke speed factor | Rachel | Oct 11 |
| Census-to-needs mapping table with sources | Rachel | Oct 11 |
| Mentor session with an emergency manager: margin, approval delay, triage weights | Ali + Bhavaani | Oct 11 |
| Vehicle movement + "current leg never interrupted" | Ali | Oct 11 |

## Change log

| Date | Change | Reason |
|---|---|---|
| Oct 1 | Proposed by Ali | Answers PRD "Still unset"; adds fire reports, care facilities, driver-safety rule |
| Oct 2 | Ali confirmed the five numbers | 25% is a curve point, not the published registry rate. Call trigger is an order or a published fire report, not a satellite detection. Two agents, plus a supervisor only if Orchestrate requires one |
