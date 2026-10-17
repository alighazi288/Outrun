/**
 * Which screen is open, kept in the page address so a link opens it directly:
 *   ?mode=replay              the Eaton night from precomputed files (default)
 *   ?mode=manager             the Eaton night on the API, the manager approving
 *   ?mode=live&area=<name>    any US area on today's data (live server)
 */

import { useEffect, useState } from "react";

export type Mode = "replay" | "manager" | "live";

export interface Route {
  mode: Mode;
  area: string | null;
}

/** The Eaton API (manager mode) and the live server. Local defaults when developing. */
export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ??
  (import.meta.env.DEV ? "http://localhost:8000" : "");
export const LIVE_URL: string =
  (import.meta.env.VITE_LIVE_URL as string | undefined) ??
  (import.meta.env.DEV ? "http://localhost:8001" : "");

export function readRoute(search: string = window.location.search): Route {
  const params = new URLSearchParams(search);
  const mode = params.get("mode");
  return {
    mode: mode === "manager" || mode === "live" ? mode : "replay",
    area: mode === "live" ? params.get("area") : null,
  };
}

export function routeSearch(route: Route): string {
  const params = new URLSearchParams({ mode: route.mode });
  if (route.mode === "live" && route.area) params.set("area", route.area);
  return `?${params.toString()}`;
}

export function useRoute(): [Route, (route: Route) => void] {
  const [route, setRouteState] = useState<Route>(() => readRoute());
  useEffect(() => {
    const onPop = () => setRouteState(readRoute());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const setRoute = (next: Route) => {
    window.history.pushState(null, "", routeSearch(next));
    setRouteState(next);
  };
  return [route, setRoute];
}

/** Free hosting puts a server to sleep when idle; the first request wakes it in about a minute.
 *  Retry `load` every WAKE_RETRY_MS until it works or WAKE_LIMIT_MS passes, calling
 *  `onWaiting` while it waits. A local server is not retried: it's either running or not. */
const WAKE_RETRY_MS = 10_000;
const WAKE_LIMIT_MS = 180_000;

export const isLocal = (url: string) => /\/\/(localhost|127\.0\.0\.1)\b/.test(url);

export async function untilAwake<T>(url: string, load: () => Promise<T>,
                                    onWaiting: () => void): Promise<T> {
  const giveUp = Date.now() + (isLocal(url) ? 0 : WAKE_LIMIT_MS);
  for (;;) {
    try {
      return await load();
    } catch (e) {
      if (Date.now() >= giveUp) throw e;
      onWaiting();
      await new Promise((resolve) => setTimeout(resolve, WAKE_RETRY_MS));
    }
  }
}
