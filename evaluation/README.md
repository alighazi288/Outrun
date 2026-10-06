# evaluation/

The rules and the proposed values are in [`docs/EVAL_SPEC.md`](../docs/EVAL_SPEC.md). This folder
holds the code that carries them out.

**Now:** `standin.py` (`make eval`) is a STAND-IN: ours vs. the dispatcher rule over 5 seeds,
scored strict (before the earliest plausible arrival) and lenient (before the first evidence of
fire). Its docstring lists what the real version adds. Replace it piece by piece;
`tests/test_eval.py` and `tests/test_arrival_window.py` pin the scoring rule.

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
- **Harness:** for each setting and each of 30 synthetic populations:
  1. Load the dataset with `DataStore(folder, knowledge=KnowledgeParams(...), seed=seed)`.
  2. Step through the night: nowcast → risk → plan → approval delay → move vehicles → mark pickups.
  3. Score against the arrival window.
  4. Write one row per (setting, planner, seed).
- **Report:** lead with warning lead time, then each lever's effect, the fleet-size curve, and the
  paired difference ours − dispatcher. Medians and ranges.

## Harness shape

```python
class Planner(Protocol):  # same signature as engines.routing.plan_routes
    def __call__(self, risks, residents, vehicles, shelters, outlook, travel, t,
                 previous_plan=None) -> Plan: ...

def run_replay(planner, store, settings) -> Metrics: ...
```
