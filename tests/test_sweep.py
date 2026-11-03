"""The full evaluation runner: every planned run once, settings that really reach the replay,
and tables that read the results right. On the fake fixtures, so the numbers mean nothing."""

from __future__ import annotations

import dataclasses
import importlib
import json

from backend.assumptions import SAFETY_MARGIN_MIN, VULNERABILITY
from backend.store import DATASETS, DataStore
from evaluation import report as rep
from evaluation import sweep
from evaluation.sweep import BASELINE, Settings

FIXTURES = DATASETS["fixtures"]


def test_every_run_is_planned_once_and_paired():
    plan = sweep.runs(populations=2)
    keys = [r.key for r in plan]
    assert len(keys) == len(set(keys))
    baseline = [r for r in plan if r.group == "sweep" and r.label == "baseline"]
    assert {(r.planner, r.population) for r in baseline} == {
        (p, k) for p in ("ours", "dispatcher rule") for k in (0, 1)}
    # A tested value equal to the baseline is the baseline run, not a second copy of it.
    labels = {r.label for r in plan if r.group == "sweep"}
    assert "safety_margin_min=30" not in labels and "safety_margin_min=15" in labels
    assert len(sweep.runs()) == 2280


def test_the_fleet_curve_keeps_the_mix_and_the_depot():
    like = DataStore(FIXTURES).vehicles
    for n, (vans, ambulances, buses) in {2: (1, 1, 0), 5: (2, 2, 1), 80: (32, 32, 16)}.items():
        made = sweep.fleet(n, like)
        kinds = [v.type for v in made]
        assert (kinds.count("wheelchair_van"), kinds.count("ambulance"),
                kinds.count("bus")) == (vans, ambulances, buses)
        assert {(v.lat, v.lon) for v in made} == {(like[0].lat, like[0].lon)}


def test_engine_values_are_set_for_each_run_and_put_back():
    risk = importlib.import_module("engines.risk")
    routing = importlib.import_module("engines.routing")
    nowcast = importlib.import_module("engines.nowcast")
    sweep.apply_engine_values(Settings(safety_margin_min=45, percentile=5, equal_weights=True))
    assert risk.SAFETY_MARGIN_MIN == routing.SAFETY_MARGIN_MIN == 45
    assert nowcast.Z_P10 == sweep.Z[5] and set(risk.VULNERABILITY.values()) == {1.0}
    sweep.apply_engine_values(BASELINE)
    assert risk.SAFETY_MARGIN_MIN == routing.SAFETY_MARGIN_MIN == SAFETY_MARGIN_MIN
    assert nowcast.Z_P10 == sweep.Z[10] and risk.VULNERABILITY == VULNERABILITY


def test_settings_reach_the_people_the_fleet_and_who_is_known():
    base = sweep.store_for(FIXTURES, BASELINE, 0)
    changed = sweep.store_for(FIXTURES, Settings(loading=2.0, fleet=5, fraction_known=1.0), 0)
    assert [r.load_minutes * 2 for r in base.population] == [
        r.load_minutes for r in changed.population]
    assert len(changed.vehicles) == 5
    estimated = sum(r.source == "estimated" for r in changed.population)
    on_the_list = [r for r in changed.residents if r.source == "registry"]
    assert estimated and len(on_the_list) == estimated  # 100% known: everyone is on the list
    assert all(r.known_at is None for r in on_the_list)


def test_one_run_is_scored_with_every_measure():
    run = next(r for r in sweep.runs(populations=1) if r.label == "baseline")
    row = sweep.run_one(run, FIXTURES)
    assert row["key"] == run.key and 0 <= row["strict"] <= row["lenient"] <= row["reached"]
    for name in ("first_dispatch_min", "vehicle_use", "escalated", "escalated_fire_reached",
                 "driver_exposure_min"):
        assert name in row
    json.dumps(row)  # one line of the results file


def _row(group, label, planner, mode, k, strict, reached=100):
    return {"key": f"{group}|{label}|{planner}|{mode}|{k}", "group": group, "label": label,
            "planner": planner, "mode": mode, "population": k, "strict": strict,
            "reached": reached, "first_dispatch_min": 130, "vehicle_use": 0.5,
            "escalated": 3, "escalated_fire_reached": 2, "driver_exposure_min": 0}


def test_results_from_several_laptops_merge_once_each(tmp_path):
    a, b = _row("sweep", "baseline", "ours", "our forecast", 0, 10), \
        _row("sweep", "baseline", "ours", "our forecast", 1, 12)
    (tmp_path / "runs-a-part1of2.jsonl").write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n")
    (tmp_path / "runs-b-part2of2.jsonl").write_text(json.dumps(b) + "\n")
    assert sorted(r["population"] for r in sweep.load(tmp_path)) == [0, 1]
    plan = sweep.runs(populations=2)
    halves = sweep.part(plan, 1, 2), sweep.part(plan, 2, 2)
    assert sorted(r.key for h in halves for r in h) == sorted(r.key for r in plan)


def test_the_report_pairs_populations_and_reads_the_fleet_curve():
    rows = []
    for k in range(4):
        rows.append(_row("sweep", "baseline", "ours", "our forecast", k, 20 + k))
        rows.append(_row("sweep", "baseline", "dispatcher rule", "our forecast", k, 18 + k))
        rows.append(_row("extras", "baseline", "ours", "wait for orders", k, 10))
    res = rep.Results(rows)
    gap = res.paired(("sweep", "baseline", "ours", "our forecast"),
                     ("sweep", "baseline", "dispatcher rule", "our forecast"))
    assert gap == [2.0, 2.0, 2.0, 2.0]
    assert rep.needed_for({5: [50.0], 10: [91.0, 89.0, 95.0], 20: [99.0]}) == "10 vehicles"
    assert rep.needed_for({5: [50.0]}).startswith("not reached")
    text = rep.report(rows)
    assert "Our forecast vs waiting for the real orders (ours) | +11.5 pp" in text
    assert "across 4 synthetic populations, 21.5%" in text


def test_settings_cover_every_tested_value():
    names = {f.name for f in dataclasses.fields(Settings)}
    assert set(sweep.TESTED) <= names
