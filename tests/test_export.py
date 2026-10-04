"""The map hexagons file: one closed hexagon per cell, in the [lon, lat] order maps expect."""

from __future__ import annotations

from backend.export import cells_geojson


def test_one_hexagon_per_cell(store):
    geo = cells_geojson(store.cells)
    assert geo["type"] == "FeatureCollection"
    assert [f["properties"]["h3"] for f in geo["features"]] == store.cells


def test_rings_are_closed_hexagons(store):
    for f in cells_geojson(store.cells)["features"]:
        ring = f["geometry"]["coordinates"][0]
        assert len(ring) == 7, "6 corners plus the first corner repeated"
        assert ring[0] == ring[-1]


def test_corners_are_lon_lat_inside_the_study_area(store):
    """Swapping lat and lon would put Altadena in Antarctica; this catches it."""
    box = store.meta["bbox"]
    pad = 0.01  # edge hexagons stick out of the box a little
    for f in cells_geojson(store.cells)["features"]:
        for lon, lat in f["geometry"]["coordinates"][0]:
            assert box["west"] - pad <= lon <= box["east"] + pad
            assert box["south"] - pad <= lat <= box["north"] + pad
