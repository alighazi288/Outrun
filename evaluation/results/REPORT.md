# Evaluation results

2310 of 2310 runs done, over 30 of 30 populations. Strict: picked up before the fire's earliest plausible arrival, as a share of the vulnerable residents the fire reached. Median (5th–95th percentile).

| Group | Runs done |
| --- | --- |
| sweep | 1560 of 1560 |
| extras | 150 of 150 |
| fleet_curve | 360 of 360 |
| good_night | 60 of 60 |
| bad_night | 60 of 60 |
| p5 | 60 of 60 |
| equal_weights | 60 of 60 |

## Baseline

| Planner | Mode | Picked up in time | Fire reached (people) |
| --- | --- | --- | --- |
| ours | our forecast | 5.4% (4.7–6.5) | 2221 |
| dispatcher rule | our forecast | 5.7% (4.9–6.6) | 2221 |
| closest first | our forecast | 1.6% (1.1–2.0) | 2221 |
| closest first | wait for orders | 4.5% (3.7–4.9) | 2221 |
| ours | wait for orders | 4.3% (3.7–4.8) | 2221 |
| dispatcher rule | wait for orders | 4.4% (3.7–4.9) | 2221 |
| ours | true fire path | 14.9% (14.5–15.4) | 2221 |

## What makes the difference (paired, percentage points)

| Comparison | Difference |
| --- | --- |
| Ours vs the dispatcher rule (both with our forecast) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| Our forecast vs waiting for the real orders (ours) | +1.2 pp (+0.1 to +2.3); ahead in 93% |
| Our forecast vs waiting for the real orders (the rule) | +1.3 pp (+0.3 to +2.3); ahead in 97% |
| Outrun vs roughly today (closest first, after the real orders) | +1.1 pp (+0.3 to +2.3); ahead in 97% |

## One setting at a time

| Setting | Ours | Dispatcher rule | Ours − rule |
| --- | --- | --- | --- |
| fleet = 2 | 0.2% (0.1–0.4) | 0.3% (0.1–0.4) | +0.0 pp (-0.2 to +0.1); ahead in 30% |
| fleet = 5 | 0.6% (0.4–0.8) | 0.5% (0.4–1.0) | +0.0 pp (-0.3 to +0.3); ahead in 47% |
| fleet = 10 | 1.5% (1.1–2.0) | 1.5% (1.0–1.9) | +0.0 pp (-0.5 to +0.6); ahead in 53% |
| fleet = 20 | 4.2% (3.8–5.1) | 4.4% (3.8–5.0) | -0.0 pp (-0.8 to +0.8); ahead in 47% |
| fleet = 40 | 11.6% (10.2–12.3) | 12.0% (10.6–13.0) | -0.2 pp (-2.4 to +1.2); ahead in 43% |
| fleet = 80 | 27.0% (25.6–28.0) | 26.8% (25.3–27.9) | +0.1 pp (-1.1 to +2.6); ahead in 53% |
| speed_factor = 0.25 | 1.7% (1.1–2.5) | 1.8% (1.1–2.8) | -0.1 pp (-0.9 to +1.0); ahead in 50% |
| speed_factor = 0.5 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| speed_factor = 0.75 | 7.4% (6.2–8.1) | 7.2% (6.1–8.3) | +0.2 pp (-1.3 to +1.2); ahead in 53% |
| loading = 0.5 | 11.4% (10.1–12.4) | 11.9% (10.0–13.6) | -0.4 pp (-2.4 to +1.4); ahead in 37% |
| loading = 1 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| loading = 2 | 1.5% (1.1–2.2) | 1.6% (1.1–2.4) | -0.2 pp (-0.7 to +0.4); ahead in 40% |
| approval_delay_min = 0 | 5.9% (4.9–6.7) | 6.1% (5.1–6.8) | -0.1 pp (-1.3 to +1.0); ahead in 30% |
| approval_delay_min = 5 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| approval_delay_min = 10 | 4.5% (3.8–5.7) | 4.3% (3.3–5.5) | +0.4 pp (-0.8 to +1.5); ahead in 73% |
| approval_delay_min = 20 | 2.8% (2.2–3.6) | 2.9% (2.1–3.8) | +0.0 pp (-1.3 to +0.7); ahead in 50% |
| fraction_known = 0 | 4.9% (4.3–6.0) | 5.2% (4.6–6.3) | -0.3 pp (-1.4 to +0.4); ahead in 27% |
| fraction_known = 0.25 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| fraction_known = 0.5 | 4.9% (4.1–6.2) | 5.0% (4.0–5.9) | -0.1 pp (-1.3 to +1.1); ahead in 43% |
| fraction_known = 1 | 4.6% (4.0–5.5) | 5.0% (4.3–5.6) | -0.2 pp (-1.1 to +0.3); ahead in 27% |
| never_call = 0 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| never_call = 0.1 | 5.9% (4.8–6.6) | 6.0% (5.1–6.7) | -0.3 pp (-1.1 to +0.8); ahead in 37% |
| never_call = 0.25 | 6.0% (5.0–6.9) | 6.1% (5.3–7.0) | -0.1 pp (-1.2 to +0.6); ahead in 47% |
| call_delay_max_min = 30 | 5.8% (4.7–6.9) | 5.8% (4.9–6.7) | -0.2 pp (-1.1 to +0.9); ahead in 40% |
| call_delay_max_min = 60 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| handling_delay_min = 5 | 5.8% (4.6–6.9) | 5.8% (4.6–6.6) | -0.0 pp (-1.2 to +1.3); ahead in 47% |
| handling_delay_min = 15 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| handling_delay_min = 30 | 5.3% (4.7–6.2) | 5.7% (5.0–6.7) | -0.1 pp (-1.3 to +0.7); ahead in 30% |
| trigger_km = 1 | 5.4% (4.7–6.4) | 5.5% (4.4–6.7) | -0.0 pp (-1.2 to +1.0); ahead in 50% |
| trigger_km = 2 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| trigger_km = 3 | 4.7% (4.2–5.7) | 5.0% (4.5–5.8) | -0.2 pp (-0.9 to +0.4); ahead in 20% |
| safety_margin_min = 15 | 8.5% (7.1–9.0) | 8.3% (7.0–9.0) | +0.1 pp (-1.1 to +1.3); ahead in 53% |
| safety_margin_min = 30 (baseline) | 5.4% (4.7–6.5) | 5.7% (4.9–6.6) | -0.2 pp (-1.2 to +1.0); ahead in 43% |
| safety_margin_min = 45 | 3.7% (3.0–4.3) | 3.5% (2.8–4.2) | +0.1 pp (-0.5 to +1.0); ahead in 60% |

## Fleet size

| Vehicles | Ours, 25% known | Rule, 25% known | Ours, 100% known | Rule, 100% known |
| --- | --- | --- | --- | --- |
| 2 | 0.2% (0.1–0.4) | 0.3% (0.1–0.4) | 0.2% (0.1–0.3) | 0.2% (0.1–0.4) |
| 5 | 0.6% (0.4–0.8) | 0.5% (0.4–1.0) | 0.5% (0.4–0.8) | 0.6% (0.3–0.9) |
| 10 | 1.5% (1.1–2.0) | 1.5% (1.0–1.9) | 1.4% (0.9–1.8) | 1.4% (1.1–1.9) |
| 20 | 4.2% (3.8–5.1) | 4.4% (3.8–5.0) | 4.4% (3.8–5.0) | 3.9% (3.2–4.5) |
| 40 | 11.6% (10.2–12.3) | 12.0% (10.6–13.0) | 12.5% (11.6–13.4) | 12.2% (10.6–13.0) |
| 80 | 27.0% (25.6–28.0) | 26.8% (25.3–27.9) | 30.5% (29.1–31.9) | 29.5% (28.5–30.6) |

Vehicles needed for 90% (100% known, median population): ours not reached with 80 vehicles; dispatcher rule not reached with 80 vehicles.

## Good night, bad night, and checks

| Run | Ours | Dispatcher rule |
| --- | --- | --- |
| Good night: every condition at its optimistic end | 15.9% (14.9–17.0) | 16.7% (14.6–17.9) |
| Bad night: every condition at its pessimistic end | 0.9% (0.6–1.4) | 0.9% (0.5–1.3) |
| Safety rule at the 5th percentile instead of the 10th | 3.5% (2.9–4.2) | 3.7% (3.2–4.4) |
| Equal priority weights for every need | 5.4% (4.9–6.5) | 5.7% (4.9–6.6) |

## Other measures at the baseline (median)

| Measure | Ours | Dispatcher rule |
| --- | --- | --- |
| First vehicle moving (minutes after 6 p.m.) | 130 | 130 |
| Vehicle use (share of vehicle-steps busy) | 66% | 66% |
| People escalated to fire command (ever) | 3846 | 3847 |
| … of them, the fire reached | 2090 | 2082 |
| Driver exposure (vehicle-minutes; target 0) | 0 | 0 |

## The sentence (EVAL_SPEC §13)

> Under stated assumptions, across 30 synthetic populations, 5.4% (5–95%: 4.7–6.5%) of vulnerable residents in areas the fire reached were picked up before its earliest plausible arrival, vs 5.7% for the dispatcher rule and 4.3% when vehicles waited for the real evacuation orders.
