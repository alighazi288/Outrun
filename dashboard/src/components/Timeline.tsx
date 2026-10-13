/**
 * Timeline component.
 *
 * Replay mode: range slider over 73 steps + play/pause.
 * Live mode: "Next 10 min" and "Reset" buttons.
 */

import { useWorld } from "@/context/WorldContext";
import { ReplaySource } from "@/data/source";
import styles from "./Timeline.module.css";

export default function Timeline() {
  const { source, manifest } = useWorld();
  const isReplay = source.mode === "replay";

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
            onClick={() => void (source as ReplaySource).step(1)}
          >
            Next 10 min
          </button>
          <button
            className={`${styles.btn} ${styles.btnSecondary}`}
            onClick={() => void source.reset()}
          >
            Reset
          </button>
        </div>
      )}
    </div>
  );
}
