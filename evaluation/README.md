# evaluation/

The rules and the proposed values are in [`docs/EVAL_SPEC.md`](../docs/EVAL_SPEC.md). This folder
holds the code that carries them out.

**Now:** `standin.py` (`make eval`) is the small version: ours vs. the dispatcher rule over 5 seeds,
scored strict (before the earliest plausible arrival) and lenient (before the first evidence of
fire). Each planner (ours, the dispatcher rule, closest first) runs three ways: with our
forecast; waiting for the real orders (a vehicle only goes once an order covers the home);
and with a perfect forecast (`perfect_forecast`, the true fire path, the upper bound). It
also prints the ceiling (people the strict rule can never count) and where each planner's
pickups went (in time, too late, fire never came). Replays run 4 at a time. On real data:
`OUTRUN_DATASET=eaton make eval SEEDS=2`.
`tests/test_eval.py` and `tests/test_arrival_window.py` pin the scoring rule.

**The full version:** `sweep.py` (`make sweep`, about 6 hours on one 8-core laptop at
`WORKERS=5`) runs 2,310 full nights: every tested setting one at a time, on 30 synthetic
populations, the fleet curve at 25% and 100% known, a good and a bad night, the safety rule at
the 5th percentile, equal priority weights, and the baseline extras (wait for orders, closest
first, closest first after the orders as roughly today, perfect forecast). Each finished night is one line in `results/`; a run that stops
carries on where it left off (`make sweep` again), and `PART=2/3` splits the work across
laptops. `report.py` (`make report`) turns the lines into `results/REPORT.md`: medians with
5th-95th percentiles, paired differences, the fleet curve, and the sentence worded as
EVAL_SPEC §13 asks. `tests/test_sweep.py` checks that every setting reaches the replay.

## Pieces

- **Arrival window** (`arrival_window.py`, `make arrival-window`): per hex, the earliest and latest
  plausible fire arrival. Reached = DINS damage in the hex, a VIIRS detection within 375 m of its
  centre, or a report precise enough to name one hex. Latest = first evidence; earliest = the last
  VIIRS pass that saw the hex clear, else the fire's start. DINS says where, never when: a hex only
  DINS reached is flagged `dins_only`. A pickup counts only if it beats the earliest time. It also
  gives warning lead time and warning precision against the official order timeline.
  On the real night VIIRS passed about twice, so most earliest times will be the fire's start or
  the 1:30 a.m. pass: strict is strict. That is the stated rule, not a bug.
- **Dispatcher heuristic:** `heuristic.py` ranks most urgent first (earliest deadline), then the
  nearest suitable vehicle. `plan_routes_dispatcher` runs that ranking under the same information
  and the same safety rule as ours. `tests/test_dispatcher.py` locks the ranking.
- **Harness** (`sweep.py`): for each setting and each of 30 synthetic populations:
  1. Draw population k (`scripts/build_residents.py` with seed 20250107 + k; k = 0 is
     `residents.jsonl`) and who's known when (`backend/knowledge.py`, seed k).
  2. Step through the night: nowcast → risk → plan → approval delay → move vehicles → mark pickups.
  3. Score against the arrival window, plus first dispatch, vehicle use, escalations and driver
     exposure (read off the vehicles at each step).
  4. Write one row per (setting, planner, mode, population).
- **Report** (`report.py`): the baseline and what changes it, the paired difference ours −
  dispatcher, our forecast vs waiting for orders, the fleet curve. Medians and ranges.
