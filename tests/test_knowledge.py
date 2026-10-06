"""Who the planner knows about, and from when: no hindsight, stable across settings."""

from __future__ import annotations

from datetime import timedelta

from backend.knowledge import KnowledgeParams, assign_knowledge, first_trigger

KNOWN_FROM_START = {"facility", "registry"}


def _assign(store, seed=7, **params):
    return assign_knowledge(store.population, store.orders, store.reports, store.detections,
                            seed, KnowledgeParams(**params))


def test_everyone_is_accounted_for(store):
    k = _assign(store)
    known = {r.id for r in k.residents}
    assert known | set(k.never_known) == {r.id for r in store.population}
    assert not known & set(k.never_known)


def test_facility_residents_are_known_from_the_start(store):
    k = _assign(store, fraction_known=0.0)
    facility = [r for r in k.residents if r.facility_id]
    assert facility and all(r.known_at is None for r in facility)


def test_calls_only_use_records_that_existed(store):
    """The trigger must be computable from records published at or before it."""
    k = _assign(store)
    orders, reports = store.orders, store.reports
    for r in k.residents:
        if r.source != "call":
            continue
        trigger = k.triggers[r.id]
        assert trigger + timedelta(minutes=15) <= r.known_at  # handling delay is applied
        visible = [
            (e.lat, e.lon, e.visible_from())
            for e in reports if e.visible_from() <= trigger
        ]
        past_orders = [o for o in orders if o.issued_at <= trigger]
        assert first_trigger(r, past_orders, visible, 2.0) == trigger


def test_fraction_known_extremes(store):
    all_known = _assign(store, fraction_known=1.0)
    assert all(r.source in KNOWN_FROM_START for r in all_known.residents)
    none_known = _assign(store, fraction_known=0.0)
    assert not any(r.source == "registry" for r in none_known.residents)


def test_settings_stay_paired(store):
    """Changing one setting must not reshuffle who is on the list."""
    a = {r.id for r in _assign(store, never_call=0.0).residents if r.source == "registry"}
    b = {r.id for r in _assign(store, never_call=0.25).residents if r.source == "registry"}
    assert a == b


def test_never_call_removes_people(store):
    assert len(_assign(store, never_call=1.0, fraction_known=0.0).never_known) > 0


def test_a_satellite_detection_does_not_start_a_call(store):
    person = next(r for r in store.population if r.source == "estimated")
    det = store.detections[0].model_copy(update={"lat": person.lat, "lon": person.lon})
    k = assign_knowledge(
        [person], [], [], [det], seed=1, params=KnowledgeParams(fraction_known=0),
    )
    assert k.residents == []
    assert k.never_known == [person.id]
