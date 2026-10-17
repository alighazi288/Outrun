/**
 * WorldContext: provides the active DataSource to all components.
 *
 * The source follows the route (src/route.ts): the precomputed Eaton replay, the Eaton API
 * in manager mode, or a live area on the live server. App remounts the provider when the
 * route changes, and the old source is closed.
 */

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ReplaySource, LiveSource, type DataSource } from "@/data/source";
import { API_URL, LIVE_URL, type Route } from "@/route";
import type { ReplayManifest } from "@/types";
import type { components } from "@/api-types";

export type WorldState = components["schemas"]["WorldState"];

interface WorldContextValue {
  source: DataSource;
  route: Route;
  /** Convenience shortcut so consumers don't reach into source */
  worldState: WorldState | null;
  manifest: ReplayManifest | null;
  loading: boolean;
  /** Live areas: the next map click places a DRILL fire report there. */
  drillArmed: boolean;
  setDrillArmed: (armed: boolean) => void;
}

const WorldContext = createContext<WorldContextValue | null>(null);

function sourceFor(route: Route): DataSource {
  if (route.mode === "manager") return new LiveSource(API_URL, "Eaton night · manager mode");
  if (route.mode === "live" && route.area) {
    return new LiveSource(`${LIVE_URL}/areas/${route.area}`, "live", true);
  }
  return new ReplaySource();
}

export function WorldProvider({ route, children }: { route: Route; children: ReactNode }) {
  // One source per mounted provider (App gives the provider a key per route)
  const sourceRef = useRef<DataSource | null>(null);
  if (!sourceRef.current) sourceRef.current = sourceFor(route);
  const source = sourceRef.current;
  const [drillArmed, setDrillArmed] = useState(false);

  // Force re-renders when source mutates
  const [, setTick] = useState(0);

  useEffect(() => {
    const src = source;
    src.onStateChange(() => setTick((n) => n + 1));
    void src.init();
    return () => src.close();
  }, [source]);

  return (
    <WorldContext.Provider
      value={{
        source,
        route,
        worldState: source.worldState,
        manifest: source instanceof ReplaySource ? source.manifest : null,
        loading: source.loading,
        drillArmed,
        setDrillArmed,
      }}
    >
      {children}
    </WorldContext.Provider>
  );
}

export function useWorld() {
  const ctx = useContext(WorldContext);
  if (!ctx) throw new Error("useWorld must be used inside <WorldProvider>");
  return ctx;
}
