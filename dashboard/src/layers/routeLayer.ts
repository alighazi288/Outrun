/**
 * Route layers — PathLayer + TextLayer for stop numbers.
 *
 * schedule: solid, coloured by vehicle type.
 * plan.routes (awaiting_decision): dashed lighter version.
 *
 * Stops are looked up by id in residents + shelters maps (never parsed by prefix).
 */

import { PathLayer, TextLayer } from "@deck.gl/layers";
import type { components } from "@/api-types";

type Route = components["schemas"]["Route"];
type Resident = components["schemas"]["Resident"];
type Shelter = components["schemas"]["Shelter"];
type Vehicle = components["schemas"]["Vehicle"];

function vehicleColor(
  vehicleId: string,
  vehicles: Map<string, Vehicle>
): [number, number, number, number] {
  const v = vehicles.get(vehicleId);
  if (!v) return [255, 200, 50, 200];
  switch (v.type) {
    case "bus":
      return [50, 180, 255, 220];
    case "wheelchair_van":
      return [255, 200, 50, 220];
    case "ambulance":
      return [255, 80, 80, 220];
    default:
      return [200, 200, 200, 200];
  }
}

interface RouteWithPath {
  route: Route;
  coords: [number, number][];
  color: [number, number, number, number];
}

export function buildRouteLayer(
  routes: Route[],
  residents: Map<string, Resident>,
  shelters: Map<string, Shelter>,
  vehicles: Map<string, Vehicle>,
  /** "solid" = approved schedule, "dashed" = pending plan */
  style: "solid" | "dashed",
  /** Only show stop-number labels for this vehicle; null = show none */
  selectedVehicleId: string | null = null
) {
  const routePaths: RouteWithPath[] = [];
  const stopMarkers: { position: [number, number]; label: string }[] = [];

  for (const route of routes) {
    const coords: [number, number][] = [];
    const isSelected = selectedVehicleId === route.vehicle;

    // Start from vehicle position if known
    const v = vehicles.get(route.vehicle);
    if (v) coords.push([v.lon, v.lat]);

    for (let i = 0; i < route.stops.length; i++) {
      const stopId = route.stops[i];
      const r = residents.get(stopId);
      if (r) {
        coords.push([r.lon, r.lat]);
        if (isSelected) {
          stopMarkers.push({
            position: [r.lon, r.lat],
            label: String(i + 1),
          });
        }
      } else {
        const s = shelters.get(stopId);
        if (s) {
          coords.push([s.lon, s.lat]);
          if (isSelected) {
            stopMarkers.push({
              position: [s.lon, s.lat],
              label: "🏠",
            });
          }
        }
      }
    }

    if (coords.length >= 2) {
      routePaths.push({
        route,
        coords,
        color: vehicleColor(route.vehicle, vehicles),
      });
    }
  }

  const opacity = style === "dashed" ? 0.45 : 0.85;

  const pathLayer = new PathLayer({
    id: `routes-${style}`,
    data: routePaths,
    getPath: (d) => d.coords,
    getColor: (d) => {
      const [r, g, b] = d.color;
      return [r, g, b, Math.round(255 * opacity)] as [
        number,
        number,
        number,
        number,
      ];
    },
    getWidth: style === "dashed" ? 2 : 3,
    widthUnits: "pixels",
    pickable: true,
    getDashArray: style === "dashed" ? [6, 4] : [0, 0],
    extensions: [],
  });

  const labelLayer = new TextLayer<{ position: [number, number]; label: string }>({
    id: `routes-stops-${style}`,
    data: stopMarkers,
    getPosition: (d) => [d.position[0], d.position[1], 0] as [number, number, number],
    getText: (d) => d.label,
    getSize: 12,
    getColor: [255, 255, 255, 230],
    getTextAnchor: "middle",
    getAlignmentBaseline: "center",
    background: true,
    getBackgroundColor: [0, 0, 0, 160],
  });

  return [pathLayer, labelLayer];
}
