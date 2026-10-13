/**
 * Evacuation alert zones — PolygonLayer.
 * advisory: yellow, warning: orange, order: red.
 * Polygons in WorldState.orders are [lon, lat] pairs (GeoJSON order).
 */

import { PolygonLayer } from "@deck.gl/layers";
import type { components } from "@/api-types";

type EvacOrder = components["schemas"]["EvacOrder"];

function kindColor(kind: EvacOrder["kind"]): [number, number, number, number] {
  switch (kind) {
    case "advisory":
      return [255, 220, 0, 60];
    case "warning":
      return [255, 140, 0, 70];
    case "order":
      return [220, 50, 50, 80];
  }
}

function kindLineColor(
  kind: EvacOrder["kind"]
): [number, number, number, number] {
  switch (kind) {
    case "advisory":
      return [255, 220, 0, 200];
    case "warning":
      return [255, 140, 0, 220];
    case "order":
      return [220, 50, 50, 240];
  }
}

export function buildEvacLayer(orders: EvacOrder[]) {
  const withPolygon = orders.filter((o) => o.polygon && o.polygon.length > 2);
  return new PolygonLayer({
    id: "evac-orders",
    data: withPolygon,
    getPolygon: (d) => d.polygon as number[][],
    getFillColor: (d) => kindColor(d.kind),
    getLineColor: (d) => kindLineColor(d.kind),
    getLineWidth: 2,
    lineWidthUnits: "pixels",
    pickable: true,
    stroked: true,
    filled: true,
  });
}
