/**
 * Times as people in the area read their clocks: the area's own time zone (from the
 * backend's /health or the replay manifest; Pacific for the Eaton night).
 */

let zone = "America/Los_Angeles";

export function setTimeZone(tz: string | null | undefined): void {
  if (tz) zone = tz;
}

function fmt(iso: string, options: Intl.DateTimeFormatOptions): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("en-US", { timeZone: zone, ...options });
  } catch {
    return iso;
  }
}

/** "Oct 15, 8:25 AM" */
export function formatDateTime(iso: string): string {
  return fmt(iso, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** "Oct 15, 8:25 AM PDT": for the clock line, so a viewer elsewhere knows whose time it is */
export function formatDateTimeZone(iso: string): string {
  return fmt(iso, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
  });
}

/** "8:25 AM" */
export function formatClock(iso: string): string {
  return fmt(iso, { hour: "numeric", minute: "2-digit" });
}

/** "4 min ago", "3 h ago", "2 days ago" */
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
