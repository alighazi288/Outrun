/**
 * OutrunMap — MapLibre map with deck.gl MapboxOverlay.
 *
 * Layers built with useMemo on worldState changes.
 * Horizon toggle (1h/2h/3h) as a small control inside the map.
 */

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer } from "@deck.gl/core";
import { useWorld } from "@/context/WorldContext";
import { buildEvacLayer } from "@/layers/evacLayer";
import { buildOutlookLayer, type OutlookHorizon } from "@/layers/outlookLayer";
import {
  buildReportsLayer,
  buildDetectionsLayer,
  buildFacilitiesLayer,
  buildResidentsLayer,
  buildSheltersLayer,
} from "@/layers/pointLayers";
import { buildRouteLayer } from "@/layers/routeLayer";
import { buildVehiclesLayer } from "@/layers/vehicleLayer";
import type { components } from "@/api-types";
import { LiveSource } from "@/data/source";
import { formatDateTime as formatTime } from "@/time";
import styles from "./OutrunMap.module.css";

type Resident = components["schemas"]["Resident"];
type Shelter = components["schemas"]["Shelter"];
type Vehicle = components["schemas"]["Vehicle"];
type Facility = components["schemas"]["Facility"];

const DARK_STYLE = "https://tiles.openfreemap.org/styles/dark";

// Until the data says where it is: west Altadena to the Convention Center shelter.
const BOUNDS: [[number, number], [number, number]] = [
  [-118.19, 34.135], // SW
  [-118.08, 34.23],  // NE
];
const FIT_PADDING = { top: 70, bottom: 130, left: 40, right: 420 };

export default function OutrunMap({
  onSelectResident,
  selectedId: _selectedId,
}: {
  onSelectResident?: (id: string | null) => void;
  selectedId?: string | null;
}) {
  const { worldState, source, drillArmed, setDrillArmed } = useWorld();
  const drillRef = useRef(drillArmed);
  drillRef.current = drillArmed;
  const area = source.health?.bbox ?? null;
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [horizon, setHorizon] = useState<OutlookHorizon>("p_1h");
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    text: string;
  } | null>(null);
  // selectedVehicleId: the vehicle whose stop numbers are shown
  const [selectedVehicleId, setSelectedVehicleId] = useState<string | null>(null);
  // What tooltips need to say about each person and care home, kept current for the
  // overlay's hover callback (created once, so it reads this ref, not stale props)
  const tipRef = useRef<TipContext>(emptyTipContext());

  // Initialise map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: DARK_STYLE,
      center: [-118.135, 34.183],
      zoom: 12,
      attributionControl: false,
    });

    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-left"
    );
    map.addControl(new maplibregl.NavigationControl(), "top-left");

    const overlay = new MapboxOverlay({
      layers: [],
      pickingRadius: 6, // small markers are easy to hover
      getTooltip: ({ object, x, y }) => {
        if (!object) {
          setTooltip(null);
          return null;
        }
        const text = getTooltipText(object, tipRef.current);
        if (text) setTooltip({ x, y, text });
        else setTooltip(null);
        return null; // we render our own tooltip
      },
      onClick: (info) => {
        const obj = info.object as { id?: string; type?: string } | undefined;
        if (obj?.id) {
          // Vehicle click → select it for stop labels; also surface to parent
          if (obj.type !== undefined) {
            // it has a .type field → it's a Vehicle
            setSelectedVehicleId((prev) => (prev === obj.id ? null : obj.id!));
          }
          onSelectResident?.(obj.id);
        } else {
          setSelectedVehicleId(null);
          onSelectResident?.(null);
        }
      },
    });

    map.on("load", () => {
      map.addControl(overlay);
      map.fitBounds(BOUNDS, { padding: FIT_PADDING, animate: false });
      map.resize();
    });

    map.on("click", (e) => {
      if (!drillRef.current || !(source instanceof LiveSource)) return;
      setDrillArmed(false);
      void source.addDrill(e.lngLat.lat, e.lngLat.lng);
    });

    mapRef.current = map;
    overlayRef.current = overlay;

    // ResizeObserver keeps the map canvas sized correctly
    const ro = new ResizeObserver(() => map.resize());
    if (containerRef.current) ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A crosshair while the next click places a drill fire
  useEffect(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = drillArmed ? "crosshair" : "";
  }, [drillArmed]);

  // Fit the map to the dataset's own area (any place Outrun is set up, not just Altadena)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !area) return;
    const fit = () =>
      map.fitBounds(
        [[area.west, area.south], [area.east, area.north]],
        { padding: FIT_PADDING, animate: false },
      );
    if (map.loaded()) fit();
    else map.once("load", fit);
  }, [area?.south, area?.west, area?.north, area?.east]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build lookup maps from worldState
  const { residentsMap, sheltersMap, vehiclesMap, facilitiesResidentMap } =
    useMemo(() => {
      if (!worldState)
        return {
          residentsMap: new Map<string, Resident>(),
          sheltersMap: new Map<string, Shelter>(),
          vehiclesMap: new Map<string, Vehicle>(),
          facilitiesResidentMap: new Map<string, number>(),
        };

      const residentsMap = new Map<string, Resident>(
        worldState.residents.map((r) => [r.id, r])
      );
      const sheltersMap = new Map<string, Shelter>(
        worldState.shelters.map((s) => [s.id, s])
      );
      const vehiclesMap = new Map<string, Vehicle>(
        worldState.vehicles.map((v) => [v.id, v])
      );

      // How many residents each care home has here, and how many are at risk / picked up
      const pickedSet = new Set(Object.keys(worldState.picked_up ?? {}));
      const atRisk = new Set(worldState.risks.filter((r) => r.at_risk).map((r) => r.resident_id));
      const facilitiesResidentMap = new Map<string, number>();
      const homes = new Map<string, HomeSummary>();
      const facilityNames = new Map<string, string>();
      for (const f of worldState.facilities as Facility[]) {
        homes.set(f.id, { residents: 0, atRisk: 0, pickedUp: 0 });
        facilityNames.set(f.id, f.name);
      }
      for (const r of worldState.residents) {
        const home = r.facility_id ? homes.get(r.facility_id) : undefined;
        if (!home) continue;
        home.residents += 1;
        if (atRisk.has(r.id)) home.atRisk += 1;
        if (pickedSet.has(r.id)) home.pickedUp += 1;
      }
      for (const [id, h] of homes) facilitiesResidentMap.set(id, h.residents - h.pickedUp);

      // Where each person stands in the plan
      const status = new Map<string, string>();
      for (const id of worldState.plan.unreachable) status.set(id, "Waiting for a vehicle");
      for (const id of worldState.plan.escalated_fire_command ?? []) {
        status.set(id, "Sent to fire command (too late or only reachable through danger)");
      }
      for (const route of [...worldState.plan.routes, ...(worldState.schedule ?? [])]) {
        for (const stop of route.stops) {
          if (residentsMap.has(stop)) status.set(stop, `On the plan: ${route.vehicle}`);
        }
      }
      for (const [id, t] of Object.entries(worldState.picked_up ?? {})) {
        status.set(id, `Picked up ${formatTime(String(t))}`);
      }
      tipRef.current = {
        homes, facilityNames, status,
        risks: new Map(worldState.risks.map((r) => [r.resident_id, r])),
      };

      return { residentsMap, sheltersMap, vehiclesMap, facilitiesResidentMap };
    }, [worldState]);

  // Build deck.gl layers
  const layers = useMemo((): Layer[] => {
    if (!worldState) return [];

    const ls: Layer[] = [];

    // 1. Evac zones (bottom)
    ls.push(buildEvacLayer(worldState.orders));

    // 2. Fire outlook hexes
    ls.push(buildOutlookLayer(worldState.outlook, horizon));

    // 3. Fire reports and detections
    ls.push(buildReportsLayer(worldState.reports));
    ls.push(buildDetectionsLayer(worldState.detections));

    // 4. Residents (picked-up + open)
    ls.push(
      ...buildResidentsLayer(
        worldState.residents as Resident[],
        worldState.risks,
        worldState.picked_up as Record<string, string>,
        worldState.plan.unreachable,
        worldState.plan.escalated_fire_command ?? []
      )
    );

    // 5. Care facilities, above residents so a home answers the hover
    ls.push(
      buildFacilitiesLayer(
        worldState.facilities as Facility[],
        facilitiesResidentMap
      )
    );

    // 6. Shelters
    ls.push(...buildSheltersLayer(worldState.shelters as Shelter[]));

    // 7. Routes: schedule (solid) always; plan.routes (dashed) only awaiting
    ls.push(
      ...buildRouteLayer(
        worldState.schedule ?? [],
        residentsMap,
        sheltersMap,
        vehiclesMap,
        "solid",
        selectedVehicleId
      )
    );
    if (worldState.plan_status === "awaiting_decision") {
      ls.push(
        ...buildRouteLayer(
          worldState.plan.routes,
          residentsMap,
          sheltersMap,
          vehiclesMap,
          "dashed",
          selectedVehicleId
        )
      );
    }

    // 8. Vehicles (top)
    ls.push(buildVehiclesLayer(worldState.vehicles as Vehicle[]));

    return ls;
  }, [
    worldState,
    horizon,
    residentsMap,
    sheltersMap,
    vehiclesMap,
    facilitiesResidentMap,
    selectedVehicleId,
  ]);

  // Push layers to overlay on every change
  useEffect(() => {
    overlayRef.current?.setProps({ layers });
  }, [layers]);

  // Listen for flyto events dispatched by the right panel
  useEffect(() => {
    const handler = (e: Event) => {
      const { lon, lat } = (e as CustomEvent<{ lon: number; lat: number }>).detail;
      mapRef.current?.flyTo({ center: [lon, lat], zoom: 15, duration: 800 });
    };
    window.addEventListener("outrun:flyto", handler);
    return () => window.removeEventListener("outrun:flyto", handler);
  }, []);

  const horizonLabels: { key: OutlookHorizon; label: string }[] = [
    { key: "p_1h", label: "1 h" },
    { key: "p_2h", label: "2 h" },
    { key: "p_3h", label: "3 h" },
  ];

  const handleHorizonClick = useCallback(
    (h: OutlookHorizon) => setHorizon(h),
    []
  );

  return (
    <div className={`${styles.wrapper} ${source.health?.live ? styles.withBanner : ""}`}>
      <div ref={containerRef} className={styles.map} />

      {/* Horizon toggle */}
      <div className={styles.horizonControl}>
        <span className={styles.horizonLabel}>Fire risk</span>
        {horizonLabels.map(({ key, label }) => (
          <button
            key={key}
            className={`${styles.horizonBtn} ${horizon === key ? styles.active : ""}`}
            onClick={() => handleHorizonClick(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className={styles.tooltip}
          style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}
        >
          {tooltip.text}
        </div>
      )}
    </div>
  );
}

// ─── Tooltip text helpers ─────────────────────────────────────────────────────

interface HomeSummary {
  residents: number;
  atRisk: number;
  pickedUp: number;
}

interface TipContext {
  homes: Map<string, HomeSummary>;
  facilityNames: Map<string, string>;
  status: Map<string, string>;
  risks: Map<string, components["schemas"]["ResidentRisk"]>;
}

function emptyTipContext(): TipContext {
  return { homes: new Map(), facilityNames: new Map(), status: new Map(), risks: new Map() };
}

const NEEDS_TEXT: Record<string, string> = {
  wheelchair: "Wheelchair user",
  oxygen: "On home oxygen",
  bedbound: "Bedbound",
  no_car: "No car",
  none: "No special needs",
};

const SOURCE_TEXT: Record<string, string> = {
  estimated: "Estimated from Census counts (not a real person)",
  registry: "On the pre-fire list (estimated from Census counts)",
  call: "Called for help (a simulated call; estimated from Census counts)",
  request: "Help request",
  facility: "Care-home resident",
};

function pct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

function residentText(obj: Record<string, unknown>, ctx: TipContext): string {
  const id = String(obj.id);
  const people = Number(obj.people ?? 1);
  const lines = [
    `${NEEDS_TEXT[String(obj.needs)] ?? String(obj.needs)}${people > 1 ? ` (${people} people)` : ""}`,
  ];
  const home = obj.facility_id ? ctx.facilityNames.get(String(obj.facility_id)) : undefined;
  lines.push(home ? `Lives at ${home}` : SOURCE_TEXT[String(obj.source)] ?? String(obj.source));
  if (obj.address) lines.push(String(obj.address));
  const risk = ctx.risks.get(id);
  if (risk?.at_risk) {
    const leave = risk.deadline_min == null ? ""
      : risk.deadline_min > 0 ? ` · must be picked up within ${Math.round(risk.deadline_min)} min`
        : " · past the safe pickup time";
    lines.push(`${pct(risk.p_3h)} chance of fire within 3 h${leave}`);
  } else {
    lines.push("Not at risk now");
  }
  const status = ctx.status.get(id);
  if (status) lines.push(status);
  return lines.join("\n");
}

function getTooltipText(obj: Record<string, unknown>, ctx: TipContext): string | null {
  // Fire report
  if ("description" in obj && "reported_at" in obj) {
    const id = String(obj.id ?? "");
    const icon = id.startsWith("drill_") ? "🧪" : id.startsWith("nifc_") ? "🔥" : "📞";
    const kind = id.startsWith("nifc_") ? "\nOfficial report (national incident system)" : "";
    return `${icon} ${String(obj.description)}${kind}\n${formatTime(String(obj.reported_at))}`;
  }
  // Detection
  if ("source" in obj && "frp_mw" in obj) {
    const frp = obj.frp_mw != null ? ` · ${String(obj.frp_mw)} MW` : "";
    const footprint = obj.pixel_m != null ? ` · footprint ~${String(obj.pixel_m)} m` : "";
    return `🛰 ${String(obj.source)}${frp}${footprint}\n${formatTime(String(obj.observed_at ?? ""))}`;
  }
  // Care home: what it is, and how its residents stand
  if ("licensed_capacity" in obj && "name" in obj) {
    const home = ctx.homes.get(String(obj.id));
    const people = home
      ? `\n${home.residents} residents here (estimated)` +
        (home.atRisk ? ` · ${home.atRisk} at risk now` : "") +
        (home.pickedUp ? ` · ${home.pickedUp} picked up` : "")
      : "";
    return `${String(obj.name)}\n${String(obj.kind)} · ${String(obj.licensed_capacity)} licensed places${people}`;
  }
  // Vehicle
  if ("seats" in obj && "type" in obj) {
    const kind = String(obj.type).replace("_", " ");
    return `${String(obj.id)} · ${kind}\n${String(obj.seats)} seats, ${String(obj.wheelchair_spaces ?? 0)} wheelchair spaces · ${String(obj.status ?? "")}`;
  }
  // Fire outlook hexagon
  if ("p_3h" in obj && "h3" in obj && !("resident_id" in obj)) {
    if (obj.burning) return "🔥 Fire seen here";
    const arrival = obj.arrival_p10_min != null
      ? `\nCould arrive in ${Math.round(Number(obj.arrival_p10_min))} min (pessimistic)` : "";
    return `Chance of fire: ${pct(Number(obj.p_1h))} in 1 h · ${pct(Number(obj.p_3h))} in 3 h${arrival}`;
  }
  // Shelter
  if ("opened_at" in obj && "name" in obj && !("kind" in obj)) {
    const opened = obj.opened_at
      ? `Opened ${formatTime(String(obj.opened_at))}`
      : "Open before fire";
    return `🏠 ${String(obj.name)}\n${opened}`;
  }
  // Person who may need a ride
  if ("needs" in obj && "id" in obj) {
    return residentText(obj, ctx);
  }
  // Evac order
  if ("kind" in obj && "area" in obj && "issued_at" in obj) {
    const k = String(obj.kind).toUpperCase();
    return `${k}: ${String(obj.area)}\n${formatTime(String(obj.issued_at))}`;
  }
  return null;
}
