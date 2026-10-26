/**
 * Timeline component.
 *
 * Replay mode: range slider over 73 steps + play/pause.
 * Manager mode (the Eaton night on the API): "Next 10 min" and "Reset".
 * A live area: the clock is the real time; "Look ahead 10 min" steps forward on the
 * forecast, "Back to now" returns to the real time.
 */

import { useState } from "react";
import { useWorld } from "@/context/WorldContext";
import styles from "./Timeline.module.css";

export default function Timeline() {
  const { source, manifest, route } = useWorld();
  const isReplay = source.mode === "replay";
  const isLiveArea = route.mode === "live";
  // One request at a time: late in the night a step takes the free server several seconds,
  // and clicks made meanwhile would queue up behind it.
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const run = async (doing: string, action: () => Promise<void> | void) => {
    if (busy) return;
    setBusy(doing);
    setFailed(null);
    try {
      await action();
    } catch (e) {
      setFailed(`Couldn't do that: ${(e as Error).message}. Try again.`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={styles.bar}>
      <div className={styles.label}>{source.timeLabel}</div>

      {isReplay && manifest ? (
        <div className={styles.replayControls}>
          <button
            className={styles.btn}
            onClick={() => source.setPlaying(!source.playing)}
            aria-label={source.playing ? "Pause" : "Play"}
          >
            {source.playing ? "⏸" : "▶"}
          </button>
          <input
            type="range"
            min={0}
            max={manifest.steps.length - 1}
            value={source.stepIndex}
            onChange={(e) => {
              source.setPlaying(false);
              source.setStepIndex(Number(e.target.value));
            }}
            className={styles.slider}
          />
          <span className={styles.stepCounter}>
            Step {source.stepIndex + 1} / {manifest.steps.length}
            {manifest.steps[source.stepIndex] && (
              <>
                {" · "}
                <span className={styles.risks}>
                  {manifest.steps[source.stepIndex].at_risk} at risk
                </span>
                {(manifest.steps[source.stepIndex].to_fire_command ?? 0) > 0 && (
                  <span className={styles.fireCommand}>
                    {" · "}
                    {manifest.steps[source.stepIndex].to_fire_command!.toLocaleString()} to fire
                    command
                  </span>
                )}
                {(manifest.steps[source.stepIndex].waiting ?? 0) > 0 && (
                  <span className={styles.waiting}>
                    {" · "}
                    {manifest.steps[source.stepIndex].waiting!.toLocaleString()} waiting
                  </span>
                )}
              </>
            )}
          </span>
        </div>
      ) : (
        <div className={styles.liveControls}>
          <button
            className={styles.btn}
            disabled={busy !== null}
            onClick={() => void run("Working out the next 10 minutes…", () => source.step(1))}
          >
            {isLiveArea ? "Look ahead 10 min" : "Next 10 min"}
          </button>
          <button
            className={`${styles.btn} ${styles.btnSecondary}`}
            disabled={busy !== null}
            onClick={() =>
              void run(isLiveArea ? "Back to now…" : "Rewinding to 6:00 PM…", () => source.reset())
            }
          >
            {isLiveArea ? "Back to now" : "Reset"}
          </button>
          {busy && <span className={styles.busy}>{busy}</span>}
          {failed && <span className={styles.failed}>{failed}</span>}
        </div>
      )}
    </div>
  );
}
