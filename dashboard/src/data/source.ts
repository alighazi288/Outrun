/**
 * Data source abstraction: two implementations behind one interface.
 *
 * - ReplaySource: static files from /replay/ (the Eaton night, precomputed)
 * - LiveSource: an Outrun API: the Eaton night in manager mode, or a live area on the live
 *   server (/areas/<name>), which runs on the real clock
 *
 * Callers use the interface only; the concrete class is chosen in WorldContext per route.
 */

import type { components } from "@/api-types";
import { untilAwake } from "@/route";
import { formatDateTimeZone, setTimeZone } from "@/time";
import type { Bbox, ReplayManifest } from "@/types";

export type WorldState = components["schemas"]["WorldState"];

/** A fire from the national incident system, as the live server describes it. */
export interface Incident {
  id: string;
  name: string;
  place: string;
  lat: number;
  lon: number;
  acres: number | null;
  status: "active" | "contained" | "controlled" | "out";
  discovered_at: string | null;
}

/** Health info from /health (API) or manifest fields (replay).
 *  fake_inputs / missing_inputs are file names; empty lists mean every input is real. */
export interface HealthInfo {
  dataset: string;
  synthetic: boolean;
  fake_inputs: string[];
  missing_inputs: string[];
  /** The dataset's area, to fit the map (null: an old export without it). */
  bbox: Bbox | null;
  /** An area set up on demand, with live feeds. */
  live: boolean;
  /** What is approximate in an area set up on demand (shown to the manager). */
  approximations: string[];
  /** Fire weather alerts in effect, e.g. a Red Flag Warning. */
  fire_weather: string[];
  /** When the live feeds were last pulled. */
  feeds_pulled_at: string | null;
  /** Feeds that failed on the last pull ("wind: ..."): their last good data is kept. */
  feed_problems: string[];
  /** The real fire the area was set up around, if any. */
  incident: Incident | null;
  /** IANA time zone of the area. */
  time_zone: string;
}

function names(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function bbox(value: unknown): Bbox | null {
  const b = value as Partial<Bbox> | null | undefined;
  return b && [b.south, b.west, b.north, b.east].every((v) => typeof v === "number")
    ? (b as Bbox)
    : null;
}

function healthFrom(h: Record<string, unknown>): HealthInfo {
  const tz = typeof h["time_zone"] === "string" ? h["time_zone"] : "America/Los_Angeles";
  setTimeZone(tz);
  return {
    dataset: String(h["dataset"] ?? ""),
    synthetic: h["synthetic"] === true,
    fake_inputs: names(h["fake_inputs"]),
    missing_inputs: names(h["missing_inputs"]),
    bbox: bbox(h["bbox"]),
    live: h["live"] === true,
    approximations: names(h["approximations"]),
    fire_weather: names(h["fire_weather"]),
    feed_problems: names(h["feed_problems"]),
    feeds_pulled_at: typeof h["feeds_pulled_at"] === "string" ? h["feeds_pulled_at"] : null,
    incident: (h["incident"] as Incident | null | undefined) ?? null,
    time_zone: tz,
  };
}

/** What callers need from the data source */
export interface DataSource {
  mode: "replay" | "live";
  /** The Outrun API this source talks to ("" for the precomputed replay). */
  apiUrl: string;
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
  /** Why the source can't load (shown instead of an empty screen) */
  error: string | null;
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
  /** Stop timers and sockets (the screen switched to another source). */
  close(): void;
}

// ─── ReplaySource ─────────────────────────────────────────────────────────────

export class ReplaySource implements DataSource {
  readonly mode = "replay" as const;
  readonly apiUrl = "";
  manifest: ReplayManifest | null = null;
  worldState: WorldState | null = null;
  stepIndex = 0;
  playing = false;
  loading = true;
  error: string | null = null;
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
    if (!step) return this.error ?? "Loading…";
    return formatDateTimeZone(step.t) + " · known at this time, no hindsight";
  }

  async init() {
    try {
      const res = await fetch("/replay/manifest.json");
      if (!res.ok) throw new Error(`manifest: ${res.status}`);
      this.manifest = (await res.json()) as ReplayManifest;
      this.health = healthFrom(this.manifest as unknown as Record<string, unknown>);
      this.loading = false;
      this._notify();
      await this._fetchStep(0);
    } catch (e) {
      console.error("ReplaySource.init failed:", e);
      this.error = "No replay files yet. Run: OUTRUN_DATASET=eaton make export";
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

  close() {
    if (this._playTimer !== null) clearInterval(this._playTimer);
    this._playTimer = null;
    this._abortController?.abort();
    this._setStateCallback = null;
  }
}

// ─── LiveSource ───────────────────────────────────────────────────────────────

interface ClockInfo {
  now: string;
  step: number;
}

/** How often a live area is asked for the latest state (it pulls fresh feeds itself). */
const FOLLOW_MS = 60_000;

export class LiveSource implements DataSource {
  readonly mode = "live" as const;
  readonly manifest = null;
  readonly apiUrl: string;
  worldState: WorldState | null = null;
  stepIndex = 0;
  stepCount = 1;
  playing = false;
  loading = true;
  error: string | null = null;
  health: HealthInfo | null = null;

  private _ws: WebSocket | null = null;
  private _clock: ClockInfo | null = null;
  private _setStateCallback: (() => void) | null = null;
  private _closed = false;
  private _follow: ReturnType<typeof setInterval> | null = null;

  /**
   * @param apiUrl the Outrun API (the Eaton API, or a live area on the live server)
   * @param label  shown after the time: "manager mode" or "live"
   * @param follow keep up with the real clock (live areas)
   */
  constructor(apiUrl: string, private readonly label: string, private readonly follow = false) {
    this.apiUrl = apiUrl.replace(/\/$/, "");
  }

  onStateChange(cb: () => void) {
    this._setStateCallback = cb;
  }

  private _notify() {
    this._setStateCallback?.();
  }

  get timeLabel() {
    if (this.error) return this.error;
    // Use worldState.t for current time — it updates with every WS message
    if (this.worldState?.t) return `${formatDateTimeZone(this.worldState.t)} · ${this.label}`;
    if (this._clock) return `${formatDateTimeZone(this._clock.now)} · ${this.label}`;
    return "Connecting…";
  }

  async init() {
    try {
      await untilAwake(this.apiUrl, () => this._refresh(), () => {
        this.error = "Waking up the server (free hosting sleeps when idle; about a minute)…";
        this._notify();
      });
      this.error = null;
      this._openWs();
      if (this.follow) this._follow = setInterval(() => void this._refresh(), FOLLOW_MS);
    } catch (e) {
      console.error("LiveSource.init failed:", e);
      this.error = `Can't reach the Outrun API at ${this.apiUrl}`;
    } finally {
      this.loading = false;
      this._notify();
    }
  }

  /** Clock, health and state at the clock's time (a live area follows the real clock and
   *  pulls its feeds again when they are 10 minutes old, on this request). */
  private async _refresh() {
    const [clockRes, healthRes] = await Promise.all([
      fetch(`${this.apiUrl}/clock`),
      fetch(`${this.apiUrl}/health`),
    ]);
    if (!clockRes.ok) throw new Error(`/clock: ${clockRes.status}`);
    this._clock = (await clockRes.json()) as ClockInfo;
    if (healthRes.ok) {
      this.health = healthFrom((await healthRes.json()) as Record<string, unknown>);
    }
    await this._fetchState(this._clock.now);
  }

  private async _fetchState(t: string) {
    const url = `${this.apiUrl}/state?t=${encodeURIComponent(t)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`/state: ${res.status}`);
    this.worldState = (await res.json()) as WorldState;
    this._notify();
  }

  private _openWs() {
    if (this._closed) return;
    const wsUrl = this.apiUrl.replace(/^http/, "ws") + "/ws";
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
      // Reconnect after 3 s, unless the screen moved on to another source
      if (!this._closed) setTimeout(() => this._openWs(), 3000);
    };
  }

  setStepIndex(_index: number) {
    // No-op in live mode
  }

  setPlaying(_playing: boolean) {
    // No-op in live mode
  }

  async step(n = 1) {
    const res = await fetch(`${this.apiUrl}/clock/step?n=${n}`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`/clock/step: ${res.status}`);
    this._clock = (await res.json()) as ClockInfo;
    await this._fetchState(this._clock.now);
  }

  async reset() {
    const res = await fetch(`${this.apiUrl}/clock/reset`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`/clock/reset: ${res.status}`);
    // A live area's clock goes back to the real time on the next request.
    await this._refresh();
  }

  /** Add a DRILL fire report at a point (live areas only; always labeled a drill). */
  async addDrill(lat: number, lon: number) {
    const res = await fetch(`${this.apiUrl}/drill`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lon }),
    });
    if (!res.ok) throw new Error(`/drill: ${res.status}`);
    await this._refresh();
  }

  close() {
    this._closed = true;
    if (this._follow !== null) clearInterval(this._follow);
    this._ws?.close();
    this._setStateCallback = null;
  }
}
