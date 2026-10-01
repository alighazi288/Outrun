# evaluation/

The rules and the proposed values are in [`docs/EVAL_SPEC.md`](../docs/EVAL_SPEC.md). This folder
holds the code that carries them out.

## Pieces

- **Arrival window:** per hex, the earliest and latest plausible fire arrival. It's built from DINS
  (which buildings burned), satellite detections and the published report timelines. A pickup counts
  only if it beats the earliest plausible arrival.
- **Dispatcher heuristic:** most urgent first, nearest suitable vehicle, with the same information
  and the same safety rule as ours.
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
