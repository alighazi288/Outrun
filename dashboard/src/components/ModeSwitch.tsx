/**
 * ModeSwitch: the three ways to look at Outrun.
 *   Eaton replay   the real night, precomputed, plans approve themselves
 *   Eaton manager  the same night on the API, the manager approves every plan
 *   Live           any US area on today's fire, wind and alerts
 * A mode whose server isn't configured in this build is shown but disabled.
 */

import { API_URL, LIVE_URL, type Mode, type Route } from "@/route";
import styles from "./ModeSwitch.module.css";

const MODES: { mode: Mode; label: string; title: string; needs: string }[] = [
  { mode: "replay", label: "Eaton replay", needs: "x",
    title: "The real Eaton Fire night, Jan 7-8 2025, using only what was known at each moment" },
  { mode: "manager", label: "Eaton · manager", needs: API_URL,
    title: "The same night on the live API: plans wait for the manager to approve them" },
  { mode: "live", label: "Live", needs: LIVE_URL,
    title: "Any US area on today's real fires, wind and alerts" },
];

export default function ModeSwitch({ route, onRoute }: {
  route: Route;
  onRoute: (route: Route) => void;
}) {
  return (
    <nav className={styles.switch} aria-label="Mode">
      {MODES.map((m) => (
        <button
          key={m.mode}
          className={`${styles.option} ${route.mode === m.mode ? styles.active : ""}`}
          title={m.needs ? m.title : `${m.title} (not configured in this build)`}
          disabled={!m.needs}
          aria-pressed={route.mode === m.mode}
          onClick={() => onRoute({ mode: m.mode, area: null })}
        >
          {m.mode === "live" && <span className={styles.dot} />}
          {m.label}
        </button>
      ))}
    </nav>
  );
}
