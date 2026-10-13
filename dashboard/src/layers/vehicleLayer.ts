/**
 * Vehicle layer — ScatterplotLayer.
 * Coloured by vehicle type, outlined by status.
 */

import { ScatterplotLayer } from "@deck.gl/layers";
import type { components } from "@/api-types";

type Vehicle = components["schemas"]["Vehicle"];

function typeColor(type: Vehicle["type"]): [number, number, number, number] {
  switch (type) {
    case "bus":
      return [50, 180, 255, 230];
    case "wheelchair_van":
      return [255, 200, 50, 230];
    case "ambulance":
      return [255, 80, 80, 230];
    default:
      return [200, 200, 200, 200];
  }
}

function statusLineColor(
  status: Vehicle["status"]
): [number, number, number, number] {
  switch (status) {
    case "en_route":
      return [255, 255, 255, 255];
    case "loading":
      return [0, 255, 100, 255];
    default:
      return [100, 100, 120, 150];
  }
}

export function buildVehiclesLayer(vehicles: Vehicle[]) {
  return new ScatterplotLayer({
    id: "vehicles",
    data: vehicles,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 20,
    getFillColor: (d) => typeColor(d.type),
    getLineColor: (d) => statusLineColor(d.status),
    stroked: true,
    lineWidthMinPixels: 2,
    pickable: true,
    radiusUnits: "meters",
  });
}
