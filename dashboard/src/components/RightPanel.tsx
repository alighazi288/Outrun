/**
 * RightPanel — plan status, decision box, routes, escalations.
 *
 * Order: header → decision box → routes (plan or schedule) → escalations.
 *
 * In replay mode: shows "Replay: plans are approved automatically." instead of buttons.
 * In live mode (awaiting_decision): Approve, Modify, Reject with POST /decisions.
 *
 * Modify UX: each route card has "Hold vehicle"; each stop has "Remove" and a
 * "Move to" select filtered by the resident's vehicle_types. No free-text ID inputs.
 *
 * Escalations: collapsed groups (click to expand), people not IDs.
 * Split "To fire command" into "Too late" and "Only reachable through danger".
 * Facility residents grouped by facility. Home residents shown by need.
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { useWorld } from "@/context/WorldContext";
import { formatClock } from "@/time";
import type { components } from "@/api-types";
import styles from "./RightPanel.module.css";

type Resident = components["schemas"]["Resident"];
type Shelter = components["schemas"]["Shelter"];
type Vehicle = components["schemas"]["Vehicle"];
type Facility = components["schemas"]["Facility"];
type PlanChange = components["schemas"]["PlanChange"];

// ─── Status pill ─────────────────────────────────────────────────────────────

const STATUS_LABELS: Record<string, string> = {
  auto: "Auto",
  awaiting_decision: "Awaiting Decision",
  approved: "Approved",
  modified: "Modified",
  rejected: "Rejected",
  expired: "Expired",
};

const STATUS_CLASS: Record<string, string> = {
  auto: styles.pillGrey,
  awaiting_decision: styles.pillAmber,
  approved: styles.pillGreen,
  modified: styles.pillBlue,
  rejected: styles.pillRed,
  expired: styles.pillGrey,
};

// ─── Escalations ─────────────────────────────────────────────────────────────

/** Max items shown before "Show N more" */
const SHOW_LIMIT = 50;

interface EscalGroup {
  title: string;
  colorClass: string;
  items: { id: string; reason: string; isFireCmd: boolean }[];
}

function EscalationsSection({
  unreachable,
  escalatedFireCommand,
  reasons,
  risks,
  residents,
  facilities,
  pickedUp,
  onFlyTo,
}: {
  unreachable: string[];
  escalatedFireCommand: string[];
  reasons: Record<string, string>;
  risks: Map<string, { priority: number; resident_id: string; at_risk: boolean }>;
  residents: Map<string, Resident>;
  facilities: Map<string, Facility>;
  pickedUp: Set<string>;
  onFlyTo: (lon: number, lat: number) => void;
}) {
  // Split escalated_fire_command into "Too late" vs "Only reachable through danger"
  const tooLate: string[] = [];
  const dangerOnly: string[] = [];
  const fireCommandSet = new Set(escalatedFireCommand);

  for (const id of escalatedFireCommand) {
    const r = reasons[id] ?? "";
    if (r.startsWith("Only reachable")) {
      dangerOnly.push(id);
    } else {
      tooLate.push(id);
    }
  }
  const waiting = unreachable.filter((id) => !fireCommandSet.has(id));

  const byPriority = (a: string, b: string) => {
    const pa = risks.get(a)?.priority ?? 0;
    const pb = risks.get(b)?.priority ?? 0;
    return pb - pa;
  };

  const groups: EscalGroup[] = [
    {
      title: `Too late (${tooLate.length})`,
      colorClass: styles.escalGroupTitleRed,
      items: [...tooLate].sort(byPriority).map((id) => ({
        id,
        reason: reasons[id] ?? "",
        isFireCmd: true,
      })),
    },
    {
      title: `Only reachable through danger (${dangerOnly.length})`,
      colorClass: styles.escalGroupTitleOrange,
      items: [...dangerOnly].sort(byPriority).map((id) => ({
        id,
        reason: reasons[id] ?? "",
        isFireCmd: true,
      })),
    },
    {
      title: `Waiting for vehicle (${waiting.length})`,
      colorClass: styles.escalGroupTitleAmber,
      items: [...waiting].sort(byPriority).map((id) => ({
        id,
        reason: reasons[id] ?? "",
        isFireCmd: false,
      })),
    },
  ].filter((g) => g.items.length > 0);

  if (unreachable.length === 0) {
    return (
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>
          Escalations and queue <span className={styles.count}>0</span>
        </h3>
        <p className={styles.mutedText}>Everyone at risk is on the plan.</p>
      </section>
    );
  }

  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>
        Escalations and queue{" "}
        <span className={styles.count}>{unreachable.length}</span>
      </h3>
      {groups.map((group) => (
        <EscalGroup
          key={group.title}
          group={group}
          residents={residents}
          facilities={facilities}
          pickedUp={pickedUp}
          onFlyTo={onFlyTo}
        />
      ))}
    </section>
  );
}

function EscalGroup({
  group,
  residents,
  facilities,
  pickedUp,
  onFlyTo,
}: {
  group: EscalGroup;
  residents: Map<string, Resident>;
  facilities: Map<string, Facility>;
  pickedUp: Set<string>;
  onFlyTo: (lon: number, lat: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);

  // Group facility residents together
  const facilityGroups = new Map<string, { fac: Facility; items: typeof group.items }>();
  const homeItems: typeof group.items = [];

  for (const item of group.items) {
    const res = residents.get(item.id);
    if (res?.facility_id) {
      const fac = facilities.get(res.facility_id);
      if (fac) {
        const existing = facilityGroups.get(fac.id);
        if (existing) {
          existing.items.push(item);
        } else {
          facilityGroups.set(fac.id, { fac, items: [item] });
        }
        continue;
      }
    }
    homeItems.push(item);
  }

  const totalItems = group.items.length;

  return (
    <div className={styles.escalGroup}>
      <button
        className={`${styles.escalGroupHeader} ${group.colorClass}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>{open ? "▾" : "▸"} {group.title}</span>
      </button>

      {open && (
        <div className={styles.escalGroupBody}>
          {/* Facility clusters */}
          {[...facilityGroups.values()].map(({ fac, items }) => (
            <div key={fac.id} className={styles.escalFacilityGroup}>
              <div className={styles.escalFacilityName}>
                {fac.name}: {items.length} resident{items.length !== 1 ? "s" : ""}
                {items[0]?.reason ? ` · ${items[0].reason}` : ""}
              </div>
            </div>
          ))}

          {/* Home residents */}
          {(showAll ? homeItems : homeItems.slice(0, SHOW_LIMIT)).map((item) => (
            <EscalHomeItem
              key={item.id}
              id={item.id}
              reason={item.reason}
              resident={residents.get(item.id) ?? null}
              pickedUp={pickedUp}
              onFlyTo={onFlyTo}
            />
          ))}

          {!showAll && homeItems.length > SHOW_LIMIT && (
            <button
              className={styles.showMore}
              onClick={() => setShowAll(true)}
            >
              Show {homeItems.length - SHOW_LIMIT} more
            </button>
          )}

          {totalItems === 0 && (
            <div className={styles.mutedText} style={{ padding: "4px 0" }}>
              (none)
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Describes a single resident at home */
function EscalHomeItem({
  id,
  reason,
  resident,
  pickedUp,
  onFlyTo,
}: {
  id: string;
  reason: string;
  resident: Resident | null;
  pickedUp: Set<string>;
  onFlyTo: (lon: number, lat: number) => void;
}) {
  const isPickedUp = pickedUp.has(id);
  // Build a human label from needs rather than showing the raw ID
  const label = resident
    ? (resident.needs || id)
    : id;

  return (
    <div className={`${styles.escalItem} ${isPickedUp ? styles.pickedUp : ""}`}>
      <div className={styles.escalItemRow}>
        <span className={styles.escalLabel}>{label}</span>
        {resident && (
          <button
            className={styles.flyBtn}
            onClick={() => onFlyTo(resident.lon, resident.lat)}
            title="Show on map"
          >
            📍
          </button>
        )}
      </div>
      {reason && <span className={styles.escalReason}>{reason}</span>}
    </div>
  );
}

// ─── Routes section ───────────────────────────────────────────────────────────

function RoutesSection({
  routes,
  label,
  reasons,
  residents,
  shelters,
  vehicles,
  style,
  modifyMode,
  onAddChange,
  selectedId,
  onSelectId,
}: {
  routes: Array<{ vehicle: string; stops: string[]; eta_min: number[] }>;
  label: string;
  reasons: Record<string, string>;
  residents: Map<string, Resident>;
  shelters: Map<string, Shelter>;
  vehicles: Map<string, Vehicle>;
  style: "solid" | "dashed";
  modifyMode: boolean;
  onAddChange: (c: PlanChange) => void;
  selectedId: string | null;
  onSelectId: (id: string | null) => void;
}) {
  if (routes.length === 0) return null;

  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>
        {label}{" "}
        <span className={styles.count}>{routes.length} vehicles</span>
      </h3>
      {routes.map((route) => (
        <RouteCard
          key={route.vehicle}
          route={route}
          reasons={reasons}
          residents={residents}
          shelters={shelters}
          vehicles={vehicles}
          dashed={style === "dashed"}
          modifyMode={modifyMode}
          onAddChange={onAddChange}
          selectedId={selectedId}
          onSelectId={onSelectId}
        />
      ))}
    </section>
  );
}

function RouteCard({
  route,
  reasons,
  residents,
  shelters,
  vehicles,
  dashed,
  modifyMode,
  onAddChange,
  selectedId,
  onSelectId,
}: {
  route: { vehicle: string; stops: string[]; eta_min: number[] };
  reasons: Record<string, string>;
  residents: Map<string, Resident>;
  shelters: Map<string, Shelter>;
  vehicles: Map<string, Vehicle>;
  dashed: boolean;
  modifyMode: boolean;
  onAddChange: (c: PlanChange) => void;
  selectedId: string | null;
  onSelectId: (id: string | null) => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const isSelected = selectedId === route.vehicle;

  // Scroll into view when this vehicle is selected (e.g. via map click)
  useEffect(() => {
    if (isSelected && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [isSelected]);

  return (
    <div
      ref={cardRef}
      className={`${styles.routeCard} ${dashed ? styles.dashed : ""} ${isSelected ? styles.routeCardSelected : ""}`}
      onClick={() => onSelectId(isSelected ? null : route.vehicle)}
    >
      <div className={styles.routeHeader}>
        <span>🚐 <strong>{route.vehicle}</strong></span>
        {modifyMode && (
          <button
            className={styles.holdBtn}
            onClick={(e) => {
              e.stopPropagation();
              onAddChange({ kind: "hold_vehicle", vehicle: route.vehicle });
            }}
          >
            Hold vehicle
          </button>
        )}
      </div>
      {route.stops.map((stopId, i) => {
        const resident = residents.get(stopId);
        const shelter = shelters.get(stopId);
        const eta = route.eta_min[i];
        const etaStr = eta != null ? `+${Math.round(eta)} min` : "";
        const reason = reasons[stopId];
        const label = shelter
          ? `🏠 ${shelter.name}`
          : resident
            ? `${resident.needs || stopId}`
            : stopId;

        // For "Move to": vehicles whose type is in resident.vehicle_types
        const compatibleVehicles = resident?.vehicle_types
          ? [...vehicles.values()].filter(
              (v) => resident.vehicle_types!.includes(v.type)
            )
          : [];

        return (
          <div key={stopId} className={styles.stop}>
            <span className={styles.stopNum}>{i + 1}</span>
            <div className={styles.stopInfo}>
              <span className={styles.stopLabel}>{label}</span>
              {etaStr && <span className={styles.stopEta}>{etaStr}</span>}
              {reason && (
                <span className={styles.stopReason}>{reason}</span>
              )}
              {modifyMode && resident && (
                <div className={styles.stopActions}>
                  <button
                    className={styles.stopActionBtn}
                    onClick={(e) => {
                      e.stopPropagation();
                      onAddChange({ kind: "remove_stop", resident: stopId });
                    }}
                  >
                    Remove
                  </button>
                  {compatibleVehicles.length > 0 && (
                    <select
                      className={styles.stopMoveSelect}
                      defaultValue=""
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        const vid = e.target.value;
                        if (vid) {
                          onAddChange({
                            kind: "reassign",
                            resident: stopId,
                            vehicle: vid,
                          });
                          e.target.value = "";
                        }
                      }}
                    >
                      <option value="">Move to…</option>
                      {compatibleVehicles.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.id}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Main export ─────────────────────────────────────────────────────────────

export default function RightPanel({
  selectedId,
  onSelectId,
}: {
  selectedId: string | null;
  onSelectId: (id: string | null) => void;
}) {
  const { worldState, source } = useWorld();
  const [_decisionError, setDecisionError] = useState<string | null>(null);
  const [modifyMode, setModifyMode] = useState(false);
  const [pendingChanges, setPendingChanges] = useState<PlanChange[]>([]);
  const panelRef = useRef<HTMLElement>(null);

  const addChange = useCallback((c: PlanChange) => {
    setPendingChanges((cs) => [...cs, c]);
  }, []);

  // Fly the MapLibre map to a coordinate by dispatching a custom event
  const handleFlyTo = useCallback((lon: number, lat: number) => {
    window.dispatchEvent(new CustomEvent("outrun:flyto", { detail: { lon, lat } }));
  }, []);

  if (!worldState) {
    return (
      <aside className={styles.panel}>
        <div className={styles.empty}>Loading…</div>
      </aside>
    );
  }

  const plan = worldState.plan;
  const isLive = source.mode === "live";
  const isAwaiting = worldState.plan_status === "awaiting_decision";
  const apiUrl = source.apiUrl;

  const residentsMap = new Map<string, Resident>(
    worldState.residents.map((r) => [r.id, r as Resident])
  );
  const sheltersMap = new Map<string, Shelter>(
    worldState.shelters.map((s) => [s.id, s as Shelter])
  );
  const vehiclesMap = new Map<string, Vehicle>(
    worldState.vehicles.map((v) => [v.id, v as Vehicle])
  );
  const facilitiesMap = new Map<string, Facility>(
    (worldState.facilities as Facility[]).map((f) => [f.id, f])
  );
  const risksMap = new Map(
    worldState.risks.map((r) => [r.resident_id, r])
  );
  const pickedUpSet = new Set(Object.keys(worldState.picked_up ?? {}));

  // Routes to show: plan.routes while awaiting; schedule otherwise
  const routesToShow = isAwaiting ? plan.routes : (worldState.schedule ?? []);
  const routesLabel = isAwaiting ? "Proposed plan" : "Schedule";
  const routesStyle: "solid" | "dashed" = isAwaiting ? "dashed" : "solid";

  return (
    <aside ref={panelRef} className={styles.panel}>
      {/* 1. Plan header */}
      <div className={styles.planHeader}>
        <span className={styles.planId}>{plan.plan_id}</span>
        <span
          className={`${styles.pill} ${STATUS_CLASS[worldState.plan_status] ?? styles.pillGrey}`}
        >
          {STATUS_LABELS[worldState.plan_status] ?? worldState.plan_status}
        </span>
        {worldState.plan_takes_effect_at && (
          <span className={styles.effectTime}>
            Takes effect:{" "}
            {formatClock(worldState.plan_takes_effect_at)}
          </span>
        )}
      </div>

      {/* 2. Decision box (live + awaiting) or replay note */}
      {isLive && isAwaiting ? (
        <DecisionBoxWithModify
          planId={plan.plan_id}
          apiUrl={apiUrl}
          worldStateT={worldState.t}
          modifyMode={modifyMode}
          setModifyMode={setModifyMode}
          pendingChanges={pendingChanges}
          setPendingChanges={setPendingChanges}
          onAddChange={addChange}
          onDecisionSent={(err) => {
            setModifyMode(false);
            setPendingChanges([]);
            if (err === "reload") {
              setDecisionError("Plan changed — reloading…");
              void source.init();
            } else if (err) {
              setDecisionError(err);
            } else {
              setDecisionError(null);
              void source.init();
            }
          }}
        />
      ) : (
        !isLive && (
          <div className={styles.replayNote}>
            Replay: plans are approved automatically.
          </div>
        )
      )}

      {/* 3. Routes */}
      <RoutesSection
        routes={routesToShow}
        label={routesLabel}
        reasons={plan.reasons as Record<string, string>}
        residents={residentsMap}
        shelters={sheltersMap}
        vehicles={vehiclesMap}
        style={routesStyle}
        modifyMode={modifyMode}
        onAddChange={addChange}
        selectedId={selectedId}
        onSelectId={onSelectId}
      />

      {/* 4. Escalations (collapsed by default) */}
      <EscalationsSection
        unreachable={plan.unreachable}
        escalatedFireCommand={plan.escalated_fire_command ?? []}
        reasons={plan.reasons as Record<string, string>}
        risks={risksMap}
        residents={residentsMap}
        facilities={facilitiesMap}
        pickedUp={pickedUpSet}
        onFlyTo={handleFlyTo}
      />
    </aside>
  );
}

// ─── DecisionBox with modify state threaded in ───────────────────────────────

function DecisionBoxWithModify({
  planId,
  apiUrl,
  worldStateT,
  modifyMode,
  setModifyMode,
  pendingChanges,
  setPendingChanges,
  onAddChange: _onAddChange,
  onDecisionSent,
}: {
  planId: string;
  apiUrl: string;
  worldStateT: string;
  modifyMode: boolean;
  setModifyMode: (v: boolean) => void;
  pendingChanges: PlanChange[];
  setPendingChanges: (cs: PlanChange[]) => void;
  onAddChange: (c: PlanChange) => void;
  onDecisionSent: (error?: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const post = useCallback(
    async (action: "approve" | "modify" | "reject") => {
      setSending(true);
      setError(null);
      try {
        const body = {
          plan_id: planId,
          action,
          by: "emergency_manager",
          t: worldStateT,
          reason: reason || undefined,
          changes: action === "modify" ? pendingChanges : [],
        };
        const res = await fetch(`${apiUrl}/decisions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (res.status === 409) {
          setError(
            "The plan has changed since you loaded it. Reloading the latest plan…"
          );
          onDecisionSent("reload");
        } else if (res.status === 422) {
          const data = (await res.json()) as {
            detail?: string | Array<{ msg: string }>;
          };
          const msg =
            typeof data.detail === "string"
              ? data.detail
              : Array.isArray(data.detail)
                ? data.detail.map((d) => d.msg).join("; ")
                : "Validation error";
          setError(msg);
        } else if (!res.ok) {
          setError(`Error ${res.status}: ${res.statusText}`);
        } else {
          onDecisionSent();
        }
      } catch (e) {
        setError(String(e));
      } finally {
        setSending(false);
      }
    },
    [planId, apiUrl, worldStateT, reason, pendingChanges, onDecisionSent]
  );

  const removeChange = (i: number) =>
    setPendingChanges(pendingChanges.filter((_, idx) => idx !== i));

  return (
    <div className={styles.decisionBox}>
      {error && <div className={styles.decisionError}>{error}</div>}

      <textarea
        className={styles.reasonField}
        placeholder="Reason (optional)…"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
      />

      {modifyMode && (
        <div className={styles.changeList}>
          <div className={styles.changeListTitle}>Pending changes</div>
          {pendingChanges.length === 0 && (
            <div className={styles.mutedText}>
              Use route cards below to add changes.
            </div>
          )}
          {pendingChanges.map((c, i) => (
            <div key={i} className={styles.changeItem}>
              <span className={styles.changeDesc}>
                {c.kind === "hold_vehicle"
                  ? `Hold ${c.vehicle ?? ""}`
                  : c.kind === "remove_stop"
                    ? `Remove ${c.resident ?? ""}`
                    : c.kind === "reassign"
                      ? `Move ${c.resident ?? ""} → ${c.vehicle ?? ""}`
                      : `${c.kind}`}
              </span>
              <button
                className={styles.removeBtn}
                onClick={() => removeChange(i)}
                aria-label="Undo"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      <div className={styles.decisionBtns}>
        <button
          className={`${styles.decisionBtn} ${styles.approve}`}
          disabled={sending}
          onClick={() => void post("approve")}
        >
          Approve
        </button>
        <button
          className={`${styles.decisionBtn} ${styles.modify}`}
          disabled={sending}
          onClick={() => {
            if (!modifyMode) {
              setModifyMode(true);
            } else {
              void post("modify");
            }
          }}
        >
          {modifyMode ? "Submit changes" : "Modify"}
        </button>
        <button
          className={`${styles.decisionBtn} ${styles.reject}`}
          disabled={sending}
          onClick={() => void post("reject")}
        >
          Reject
        </button>
      </div>
    </div>
  );
}
