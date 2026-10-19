/**
 * Point layers: fire reports, satellite detections, care facilities,
 * residents (coloured by priority), shelters.
 *
 * All built as ScatterplotLayer with explicit generics to satisfy strict TS.
 */

import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { components } from "@/api-types";

type FireReport = components["schemas"]["FireReport"];
type FireDetection = components["schemas"]["FireDetection"];
type Facility = components["schemas"]["Facility"];
type Resident = components["schemas"]["Resident"];
type ResidentRisk = components["schemas"]["ResidentRisk"];
type Shelter = components["schemas"]["Shelter"];

// ─── Fire reports (amber dots, fixed screen size) ────────────────────────────

export function buildReportsLayer(reports: FireReport[]) {
  return new ScatterplotLayer<FireReport>({
    id: "fire-reports",
    data: reports,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 6,
    getFillColor: [255, 160, 0, 210],
    getLineColor: [30, 20, 0, 220],
    stroked: true,
    lineWidthMinPixels: 1.5,
    pickable: true,
    radiusUnits: "pixels",
  });
}

// ─── Satellite detections (tiny yellow dots, fixed screen size) ───────────────

export function buildDetectionsLayer(detections: FireDetection[]) {
  return new ScatterplotLayer<FireDetection>({
    id: "detections",
    data: detections,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 3,
    getFillColor: [255, 230, 0, 230],
    stroked: false,
    pickable: true,
    radiusUnits: "pixels",
  });
}

// ─── Care facilities (circles sized by capacity) ──────────────────────────────

export function buildFacilitiesLayer(
  facilities: Facility[],
  residentsByFacility: Map<string, number>
) {
  // Sized in screen pixels by licensed places, so even a 6-bed home is big enough to hover.
  return new ScatterplotLayer<Facility>({
    id: "facilities",
    data: facilities,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => 5 + Math.sqrt(d.licensed_capacity) * 0.55,
    getFillColor: (d) =>
      (residentsByFacility.get(d.id) ?? 1) > 0
        ? [26, 188, 156, 180]
        : [26, 188, 156, 60], // everyone picked up: faded
    getLineColor: [26, 188, 156, 255],
    stroked: true,
    lineWidthMinPixels: 2,
    pickable: true,
    radiusUnits: "pixels",
    updateTriggers: { getFillColor: [residentsByFacility] },
  });
}

// ─── Residents (coloured by priority; red ring = fire command, amber = waiting) ─

function priorityToColor(
  priority: number,
  maxPriority: number,
  atRisk: boolean
): [number, number, number, number] {
  if (!atRisk) return [100, 100, 120, 180];
  const t = maxPriority > 0 ? Math.min(priority / maxPriority, 1) : 0;
  const r = Math.round(50 + t * 200);
  const g = Math.round(200 - t * 180);
  const b = 50;
  return [r, g, b, 220];
}

export function buildResidentsLayer(
  residents: Resident[],
  risks: ResidentRisk[],
  pickedUp: Record<string, string>,
  unreachable: string[],
  escalatedFireCommand: string[]
) {
  const riskMap = new Map<string, ResidentRisk>(
    risks.map((r) => [r.resident_id, r])
  );
  const offPlan = new Set(unreachable);
  const fireCommand = new Set(escalatedFireCommand);
  const maxPriority = Math.max(
    0,
    ...risks.filter((r) => r.at_risk).map((r) => r.priority)
  );

  const picked = residents.filter((r) => r.id in pickedUp);
  // Care-home residents sit on the home's own point: the home answers the hover for them
  const open = residents.filter((r) => !(r.id in pickedUp) && !r.facility_id);
  const atHomes = residents.filter((r) => !(r.id in pickedUp) && r.facility_id);

  const pickedLayer = new ScatterplotLayer<Resident>({
    id: "residents-picked-up",
    data: picked,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 12,
    getFillColor: [80, 80, 90, 150],
    radiusUnits: "meters",
    pickable: false,
  });

  const openLayer = new ScatterplotLayer<Resident>({
    id: "residents-open",
    data: open,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => {
      const risk = riskMap.get(d.id);
      return risk?.at_risk ? 22 : 14;
    },
    getFillColor: (d) => {
      const risk = riskMap.get(d.id);
      if (!risk) return [100, 100, 120, 160] as [number, number, number, number];
      return priorityToColor(risk.priority, maxPriority, risk.at_risk);
    },
    getLineColor: (d) =>
      fireCommand.has(d.id)
        ? ([220, 50, 50, 255] as [number, number, number, number])
        : offPlan.has(d.id)
          ? ([240, 166, 60, 230] as [number, number, number, number])
          : ([0, 0, 0, 0] as [number, number, number, number]),
    stroked: true,
    lineWidthMinPixels: 2,
    pickable: true,
    radiusUnits: "meters",
    updateTriggers: {
      getFillColor: [risks, pickedUp],
      getLineColor: [unreachable, escalatedFireCommand],
      getRadius: [risks],
    },
  });

  const atHomesLayer = openLayer.clone({ id: "residents-at-care-homes", data: atHomes, pickable: false });

  return [pickedLayer, atHomesLayer, openLayer];
}

// ─── Shelters (white dots) ────────────────────────────────────────────────────

export function buildSheltersLayer(shelters: Shelter[]) {
  const dots = new ScatterplotLayer<Shelter>({
    id: "shelters",
    data: shelters,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 35,
    getFillColor: [230, 230, 230, 200],
    getLineColor: [255, 255, 255, 255],
    stroked: true,
    lineWidthMinPixels: 2,
    pickable: true,
    radiusUnits: "meters",
  });

  const labels = new TextLayer<Shelter>({
    id: "shelters-labels",
    data: shelters,
    getPosition: (d) => [d.lon, d.lat, 0] as [number, number, number],
    getText: () => "S",
    getSize: 11,
    getColor: [230, 230, 230, 255],
    getTextAnchor: "middle",
    getAlignmentBaseline: "center",
  });

  return [dots, labels];
}
