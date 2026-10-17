/**
 * Hand-written types for replay manifest (not in the API contract).
 * Shape verified against the real export output.
 */
export interface ManifestStep {
  i: number;
  t: string;
  file: string;
  /** Everyone left off the plan (to_fire_command + waiting). Not shown as such. */
  unreachable: number;
  /** Too late, or only reachable through danger: escalated to fire command. */
  to_fire_command?: number;
  /** Reachable, but every suitable vehicle is busy. */
  waiting?: number;
  at_risk: number;
}

export interface ReplayManifest {
  dataset: string;
  synthetic: boolean;
  fake_inputs: string[];
  missing_inputs: string[];
  start: string;
  end: string;
  step_minutes: number;
  cells: string;
  bbox?: Bbox;
  live?: boolean;
  approximations?: string[];
  fire_weather?: string[];
  time_zone?: string;
  steps: ManifestStep[];
}

/** The dataset's area: south/west/north/east in degrees. */
export interface Bbox {
  south: number;
  west: number;
  north: number;
  east: number;
}
