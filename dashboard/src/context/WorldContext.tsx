/**
 * WorldContext: provides the active DataSource to all components.
 *
 * Chooses ReplaySource or LiveSource based on VITE_API_URL at build time.
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
import type { ReplayManifest } from "@/types";
import type { components } from "@/api-types";

export type WorldState = components["schemas"]["WorldState"];

interface WorldContextValue {
  source: DataSource;
  /** Convenience shortcut so consumers don't reach into source */
  worldState: WorldState | null;
  manifest: ReplayManifest | null;
  loading: boolean;
}

const WorldContext = createContext<WorldContextValue | null>(null);

export function WorldProvider({ children }: { children: ReactNode }) {
  // Stable source instance — created once
  const sourceRef = useRef<DataSource | null>(null);
  if (!sourceRef.current) {
    const apiUrl = import.meta.env.VITE_API_URL as string | undefined;
    if (apiUrl) {
      const live = new LiveSource(apiUrl);
      sourceRef.current = live;
    } else {
      const replay = new ReplaySource();
      sourceRef.current = replay;
    }
  }
  const source = sourceRef.current;

  // Force re-renders when source mutates
  const [, setTick] = useState(0);

  useEffect(() => {
    const src = source;
    src.onStateChange(() => setTick((n) => n + 1));
    void src.init();
    // cleanup: nothing to cancel on unmount for now
  }, [source]);

  return (
    <WorldContext.Provider
      value={{
        source,
        worldState: source.worldState,
        manifest: source instanceof ReplaySource ? source.manifest : null,
        loading: source.loading,
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
