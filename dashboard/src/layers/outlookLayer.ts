/**
 * Fire outlook hexes — H3HexagonLayer.
 * Colour by selected horizon (p_1h / p_2h / p_3h).
 * Transparent below 5 %; yellow → orange → red.
 * Burning cells: dark red regardless of probability.
 */

import { H3HexagonLayer } from "@deck.gl/geo-layers";
import type { components } from "@/api-types";

type FireOutlook = components["schemas"]["FireOutlook"];
export type OutlookHorizon = "p_1h" | "p_2h" | "p_3h";

function lerpColor(
  a: [number, number, number],
  b: [number, number, number],
  t: number
): [number, number, number] {
  return [
    Math.round(a[0] + (b[0] - a[0]) * t),
    Math.round(a[1] + (b[1] - a[1]) * t),
    Math.round(a[2] + (b[2] - a[2]) * t),
  ];
}

/** Map 0..1 probability to RGBA */
function probToColor(p: number): [number, number, number, number] {
  if (p < 0.05) return [0, 0, 0, 0]; // transparent
  const yellow: [number, number, number] = [255, 220, 0];
  const orange: [number, number, number] = [255, 100, 0];
  const red: [number, number, number] = [200, 0, 0];
  let rgb: [number, number, number];
  if (p < 0.5) {
    rgb = lerpColor(yellow, orange, (p - 0.05) / 0.45);
  } else {
    rgb = lerpColor(orange, red, (p - 0.5) / 0.5);
  }
  const alpha = Math.round(80 + p * 140); // 80–220
  return [...rgb, alpha];
}

export function buildOutlookLayer(
  outlook: FireOutlook[],
  horizon: OutlookHorizon
) {
  return new H3HexagonLayer({
    id: `outlook-${horizon}`,
    data: outlook,
    getHexagon: (d) => d.h3,
    getFillColor: (d) => {
      if (d.burning) return [180, 20, 0, 220];
      return probToColor(d[horizon]);
    },
    extruded: false,
    pickable: true,
    opacity: 0.45,
    updateTriggers: {
      getFillColor: [horizon],
    },
  });
}
