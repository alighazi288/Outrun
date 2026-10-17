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
