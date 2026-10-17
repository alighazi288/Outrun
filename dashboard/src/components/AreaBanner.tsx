/**
 * AreaBanner (live areas only): what is real here right now.
 *   - the real fire the area was set up around: name, place, when it was reported, and its
 *     status from the national incident system; or "no fire chosen"
 *   - fire weather in effect (e.g. a Red Flag Warning), from the National Weather Service
 *   - the drill button: a practice fire, always labeled DRILL
 */

import { useWorld } from "@/context/WorldContext";
import { LiveSource } from "@/data/source";
import { ago, formatClock } from "@/time";
import styles from "./AreaBanner.module.css";

const STATUS = {
  active: "active (no containment reported yet)",
  contained: "contained",
  controlled: "controlled",
  out: "out",
} as const;

export default function AreaBanner() {
  const { source, worldState, drillArmed, setDrillArmed } = useWorld();
  const h = source.health;
  if (!h?.live) return null;

  const fire = h.incident;
  const drills = (worldState?.reports ?? []).filter((r) => r.id.startsWith("drill_"));
  const official = (worldState?.reports ?? []).some((r) => r.id.startsWith("nifc_"));
  const satellites = (worldState?.detections ?? []).length;

  return (
    <div className={styles.banner}>
      <div className={styles.row}>
        {fire ? (
          <span>
            <span className={styles.fireName}>🔥 {fire.name}</span>
            {" · "}{fire.place}
            {fire.discovered_at && <> · reported {formatClock(fire.discovered_at)} ({ago(fire.discovered_at)})</>}
            {" · "}{STATUS[fire.status] ?? fire.status}
            <span className={styles.note}>
              {official
                ? " · its first report drives the forecast for 2 h, then satellites"
                : satellites
                  ? " · forecast from satellite detections"
                  : " · no satellite sees fire here now; its report is over 2 h old"}
            </span>
          </span>
        ) : (
          <span className={styles.muted}>
            Watching this area: no fire chosen.
            {satellites > 0 && ` ${satellites} satellite detection(s) here today.`}
          </span>
        )}
        <span className={styles.spacer} />
        {drills.length > 0 && (
          <span className={styles.drillTag}>DRILL ×{drills.length}</span>
        )}
        {source instanceof LiveSource && (
          <button
            className={`${styles.drillBtn} ${drillArmed ? styles.armed : ""}`}
            onClick={() => setDrillArmed(!drillArmed)}
          >
            {drillArmed ? "Click the map where it starts · cancel" : "＋ Drill fire"}
          </button>
        )}
      </div>
      {h.fire_weather.map((w) => (
        <div key={w} className={styles.weather}>⚠ {w}</div>
      ))}
      {h.feed_problems.length > 0 && (
        <div className={styles.muted}>
          Couldn't refresh {h.feed_problems.map((p) => p.split(":")[0]).join(", ")} just now:
          showing the last good data, trying again in 2 min.
        </div>
      )}
    </div>
  );
}
