/**
 * Data source abstraction: two implementations behind one interface.
 *
 * - ReplaySource: static files from /replay/
 * - LiveSource: live API at VITE_API_URL
 *
 * Callers use the interface only; the concrete class is chosen once in WorldContext.
 */

import type { components } from "@/api-types";
import type { ReplayManifest } from "@/types";

export type WorldState = components["schemas"]["WorldState"];

/** Health info from /health (live mode) or manifest fields (replay mode).
 *  fake_inputs / missing_inputs are file names; empty lists mean every input is real. */
export interface HealthInfo {
  synthetic: boolean;
  fake_inputs: string[];
  missing_inputs: string[];
}

function names(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

/** What callers need from the data source */
export interface DataSource {
  mode: "replay" | "live";
  /** Current world state, or null while loading the first step */
  worldState: WorldState | null;
  /** Replay: index into manifest.steps. Live: ignored (always 0). */
  stepIndex: number;
  /** Total number of steps (73 in replay; 1 in live). */
  stepCount: number;
  /** Human-readable current time label */
  timeLabel: string;
  /** Whether auto-play / live WS is running */
  playing: boolean;
  /** Manifest (replay mode only) */
  manifest: ReplayManifest | null;
  /** Whether the initial load is in flight */
  loading: boolean;
  /** Health/data-quality info */
  health: HealthInfo | null;

  onStateChange(cb: () => void): void;
  setStepIndex(index: number): void;
  setPlaying(playing: boolean): void;
  /** Advance by n steps (replay) or POST /clock/step?n=n (live) */
  step(n?: number): void;
  /** Reset to step 0 (replay) or POST /clock/reset (live) */
  reset(): void;
  /** Initialise the source (fetch manifest / connect WS) */
  init(): Promise<void>;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Format an ISO-8601 Pacific string like "Jan 7, 10:30 p.m." */
export function formatPacificTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      timeZone: "America/Los_Angeles",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return iso;
  }
}

// ─── ReplaySource ─────────────────────────────────────────────────────────────

export class ReplaySource implements DataSource {
  readonly mode = "replay" as const;
  manifest: ReplayManifest | null = null;
  worldState: WorldState | null = null;
  stepIndex = 0;
  playing = false;
  loading = true;
  health: HealthInfo | null = null;

  private _setStateCallback: (() => void) | null = null;
  private _abortController: AbortController | null = null;
  private _playTimer: ReturnType<typeof setInterval> | null = null;

  /** Register a re-render callback (set by context) */
  onStateChange(cb: () => void) {
    this._setStateCallback = cb;
  }

  private _notify() {
    this._setStateCallback?.();
  }

  get stepCount() {
    return this.manifest?.steps.length ?? 0;
  }

  get timeLabel() {
    const step = this.manifest?.steps[this.stepIndex];
    if (!step) return "Loading…";
    return (
      formatPacificTime(step.t) + " · known at this time, no hindsight"
    );
  }

  async init() {
    try {
      const res = await fetch("/replay/manifest.json");
      if (!res.ok) throw new Error(`manifest: ${res.status}`);
      this.manifest = (await res.json()) as ReplayManifest;
      this.health = {
        synthetic: this.manifest.synthetic,
        fake_inputs: this.manifest.fake_inputs,
        missing_inputs: this.manifest.missing_inputs,
      };
      this.loading = false;
      this._notify();
      await this._fetchStep(0);
    } catch (e) {
      console.error("ReplaySource.init failed:", e);
      this.loading = false;
      this._notify();
    }
  }

  private async _fetchStep(index: number) {
    if (!this.manifest) return;
    const step = this.manifest.steps[index];
    if (!step) return;

    this._abortController?.abort();
    const ac = new AbortController();
    this._abortController = ac;

    try {
      const res = await fetch(`/replay/${step.file}`, {
        signal: ac.signal,
      });
      if (!res.ok) throw new Error(`step ${index}: ${res.status}`);
      this.worldState = (await res.json()) as WorldState;
      this._notify();

      // Prefetch next step while playing
      if (this.playing && index + 1 < this.stepCount) {
        void fetch(`/replay/${this.manifest.steps[index + 1].file}`);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        console.error("ReplaySource._fetchStep failed:", e);
      }
    }
  }

  setStepIndex(index: number) {
    const clamped = Math.max(0, Math.min(index, this.stepCount - 1));
    this.stepIndex = clamped;
    this._notify();
    void this._fetchStep(clamped);
  }

  setPlaying(playing: boolean) {
    this.playing = playing;
    if (playing) {
      this._playTimer = setInterval(() => {
        const next = this.stepIndex + 1;
        if (next >= this.stepCount) {
          this.setPlaying(false);
        } else {
          this.setStepIndex(next);
        }
      }, 2000);
    } else {
      if (this._playTimer !== null) {
        clearInterval(this._playTimer);
        this._playTimer = null;
      }
    }
    this._notify();
  }

  step(n = 1) {
    this.setStepIndex(this.stepIndex + n);
  }

  reset() {
    this.setPlaying(false);
    this.setStepIndex(0);
  }
}

// ─── LiveSource ───────────────────────────────────────────────────────────────

interface ClockInfo {
  now: string;
  step: number;
}

export class LiveSource implements DataSource {
  readonly mode = "live" as const;
  readonly manifest = null;
  worldState: WorldState | null = null;
  stepIndex = 0;
  stepCount = 1;
  playing = false;
  loading = true;
  health: HealthInfo | null = null;

  private _apiUrl: string;
  private _ws: WebSocket | null = null;
  private _clock: ClockInfo | null = null;
  private _setStateCallback: (() => void) | null = null;

  constructor(apiUrl: string) {
    this._apiUrl = apiUrl.replace(/\/$/, "");
  }

  onStateChange(cb: () => void) {
    this._setStateCallback = cb;
  }

  private _notify() {
    this._setStateCallback?.();
  }

  get timeLabel() {
    // Use worldState.t for current time — it updates with every WS message
    if (this.worldState?.t) return formatPacificTime(this.worldState.t) + " · live";
    if (this._clock) return formatPacificTime(this._clock.now) + " · live";
    return "Connecting…";
  }

  async init() {
    try {
      const [clockRes, healthRes] = await Promise.all([
        fetch(`${this._apiUrl}/clock`),
        fetch(`${this._apiUrl}/health`),
      ]);
      if (!clockRes.ok) throw new Error(`/clock: ${clockRes.status}`);
      this._clock = (await clockRes.json()) as ClockInfo;
      if (healthRes.ok) {
        const h = (await healthRes.json()) as Record<string, unknown>;
        this.health = {
          synthetic: h["synthetic"] === true,
          fake_inputs: names(h["fake_inputs"]),
          missing_inputs: names(h["missing_inputs"]),
        };
      }
      await this._fetchState(this._clock.now);
      this._openWs();
    } catch (e) {
      console.error("LiveSource.init failed:", e);
    } finally {
      this.loading = false;
      this._notify();
    }
  }

  private async _fetchState(t: string) {
    const url = `${this._apiUrl}/state?t=${encodeURIComponent(t)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`/state: ${res.status}`);
    this.worldState = (await res.json()) as WorldState;
    this._notify();
  }

  private _openWs() {
    const wsUrl = this._apiUrl.replace(/^http/, "ws") + "/ws";
    this._ws = new WebSocket(wsUrl);
    this._ws.onmessage = (ev) => {
      try {
        this.worldState = JSON.parse(ev.data as string) as WorldState;
        this._notify();
      } catch (e) {
        console.error("WS parse error:", e);
      }
    };
    this._ws.onerror = (e) => console.error("WS error:", e);
    this._ws.onclose = () => {
      // Reconnect after 3 s
      setTimeout(() => this._openWs(), 3000);
    };
  }

  setStepIndex(_index: number) {
    // No-op in live mode
  }

  setPlaying(_playing: boolean) {
    // No-op in live mode
  }

  async step(n = 1) {
    const res = await fetch(`${this._apiUrl}/clock/step?n=${n}`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`/clock/step: ${res.status}`);
    this._clock = (await res.json()) as ClockInfo;
    await this._fetchState(this._clock.now);
  }

  async reset() {
    const res = await fetch(`${this._apiUrl}/clock/reset`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`/clock/reset: ${res.status}`);
    this._clock = (await res.json()) as ClockInfo;
    await this._fetchState(this._clock.now);
  }
}
