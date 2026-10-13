/**
 * TopBar — four big numbers + data quality badge.
 *
 * Numbers: people known, at risk now, picked up, to fire command, waiting for a vehicle.
 * plan.unreachable is everyone left off this plan: the fire-command subset plus the queue.
 * Badge: green "Real inputs" or red "Fake data: …" based on manifest/worldState.
 */

import { useWorld } from "@/context/WorldContext";
import styles from "./TopBar.module.css";

export default function TopBar() {
  const { worldState, source } = useWorld();

  const peopleKnown = worldState?.residents.length ?? 0;
  const atRisk = worldState?.risks.filter((r) => r.at_risk).length ?? 0;
  const pickedUp = Object.keys(worldState?.picked_up ?? {}).length;
  const toFireCommand = worldState?.plan.escalated_fire_command?.length ?? 0;
  const waiting = (worldState?.plan.unreachable.length ?? 0) - toFireCommand;

  // Data quality badge — uses source.health in both replay and live modes
  let badgeClass = styles.badgeUnknown;
  let badgeText = "Loading…";
  const h = source.health;
  if (h) {
    const isReal = !h.synthetic && h.fake_inputs.length === 0 && h.missing_inputs.length === 0;
    if (isReal) {
      badgeClass = styles.badgeReal;
      badgeText = source.mode === "live" ? "Real inputs · manager mode" : "Real inputs";
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
