/**
 * TopBar — mode switch, five big numbers, data badge.
 *
 * Numbers: people known, at risk now, picked up, to fire command, waiting for a vehicle.
 * plan.unreachable is everyone left off this plan: the fire-command subset plus the queue.
 * Badge: the Eaton night: green "Real inputs" or red "Fake data: …"; a live area: "LIVE"
 * with how long ago the feeds were pulled, and a button to pick another area.
 */

import { useWorld } from "@/context/WorldContext";
import ModeSwitch from "@/components/ModeSwitch";
import type { Route } from "@/route";
import { ago } from "@/time";
import styles from "./TopBar.module.css";

const STALE_MIN = 15;  // feeds refresh every 10 min; older than this, the badge turns amber

export default function TopBar({ onRoute }: { onRoute: (route: Route) => void }) {
  const { worldState, source, route } = useWorld();

  const peopleKnown = worldState?.residents.length ?? 0;
  const atRisk = worldState?.risks.filter((r) => r.at_risk).length ?? 0;
  const pickedUp = Object.keys(worldState?.picked_up ?? {}).length;
  const toFireCommand = worldState?.plan.escalated_fire_command?.length ?? 0;
  const waiting = (worldState?.plan.unreachable.length ?? 0) - toFireCommand;

  // Data quality badge — uses source.health in both replay and live modes
  let badgeClass = styles.badgeUnknown;
  let badgeText = "Loading…";
  const h = source.health;
  if (route.mode === "live" && h) {
    const pulled = h.feeds_pulled_at ? new Date(h.feeds_pulled_at).getTime() : 0;
    const fresh = Date.now() - pulled < STALE_MIN * 60_000;
    badgeClass = fresh ? styles.badgeReal : styles.badgeStale;
    badgeText = `LIVE · feeds ${ago(h.feeds_pulled_at)}`;
  } else if (source.error) {
    badgeClass = styles.badgeFake;
    badgeText = "Not connected";
  } else if (h) {
    const isReal = !h.synthetic && h.fake_inputs.length === 0 && h.missing_inputs.length === 0;
    if (isReal) {
      badgeClass = styles.badgeReal;
      badgeText = route.mode === "manager" ? "Real inputs · manager mode" : "Real inputs";
    } else {
      const issues = [
        h.synthetic ? "synthetic dataset" : null,
        h.fake_inputs.length ? `fake ${h.fake_inputs.join(", ")}` : null,
        h.missing_inputs.length ? `missing ${h.missing_inputs.join(", ")}` : null,
      ]
        .filter(Boolean)
        .join("; ");
      badgeClass = styles.badgeFake;
      badgeText = `Fake data: ${issues}`;
    }
  }

  return (
    <header className={styles.bar}>
      <div className={styles.title}>Outrun</div>
      <ModeSwitch route={route} onRoute={onRoute} />

      <div className={styles.numbers}>
        <Stat label="Known" value={peopleKnown} />
        <Stat label="At risk" value={atRisk} accent="risk" />
        <Stat label="Picked up" value={pickedUp} accent="safe" />
        <Stat
          label="To fire command"
          value={toFireCommand}
          accent={toFireCommand > 0 ? "fire" : undefined}
        />
        <Stat
          label="Waiting for a vehicle"
          value={waiting}
          accent={waiting > 0 ? "wait" : undefined}
        />
      </div>

      <div className={`${styles.badge} ${badgeClass}`}>{badgeText}</div>
      {route.mode === "live" && (
        <button className={styles.change} onClick={() => onRoute({ mode: "live", area: null })}>
          Change area
        </button>
      )}
    </header>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: "risk" | "fire" | "safe" | "wait";
}) {
  const accentClass =
    accent === "risk"
      ? styles.accentRisk
      : accent === "fire"
        ? styles.accentFire
        : accent === "safe"
          ? styles.accentSafe
          : accent === "wait"
            ? styles.accentWait
            : "";

  return (
    <div className={styles.stat}>
      <span className={`${styles.statValue} ${accentClass}`}>
        {value.toLocaleString()}
      </span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}
