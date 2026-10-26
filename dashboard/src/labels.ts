/**
 * Plain names for what the data calls by id: people ("Wheelchair user · Bedell Family
 * Circle", "Person with no car · home #214"), vehicles ("Wheelchair van 1") and plans.
 * People are simulated from Census counts, so they have no real names; the number tells two
 * people with the same need apart.
 */

export const NEEDS_TEXT: Record<string, string> = {
  wheelchair: "Wheelchair user",
  oxygen: "Person on home oxygen",
  bedbound: "Bedbound person",
  no_car: "Person with no car",
  none: "Person",
};

export const SOURCE_TEXT: Record<string, string> = {
  estimated: "Estimated from Census counts (not a real person)",
  registry: "On the pre-fire list (estimated from Census counts)",
  call: "Called for help (a simulated call; estimated from Census counts)",
  request: "Help request",
  facility: "Care-home resident",
};

interface PersonLike {
  id: string;
  needs?: string | null;
  people?: number | null;
  address?: string | null;
}

export function personLabel(r: PersonLike, careHome?: string): string {
  const need = NEEDS_TEXT[r.needs ?? ""] ?? "Person";
  const count = r.people && r.people > 1 ? ` (${r.people} people)` : "";
  if (careHome) return `${need}${count} · ${careHome}`;
  if (r.address) return `${need}${count} · ${r.address}`;
  const number = /(\d+)$/.exec(r.id)?.[1];
  return `${need}${count} · home${number ? ` #${Number(number)}` : ""}`;
}

const VEHICLE_KIND: Record<string, string> = {
  van: "Wheelchair van",
  amb: "Ambulance",
  bus: "Bus",
};

/** "van_01" -> "Wheelchair van 1"; anything else is shown as it is. */
export function vehicleLabel(id: string): string {
  const m = /^([a-z]+)_0*(\d+)$/.exec(id);
  const kind = m ? VEHICLE_KIND[m[1]] : undefined;
  return kind && m ? `${kind} ${m[2]}` : id;
}
