/**
 * LivePicker: choose what live mode watches.
 *   - areas already set up on the live server (open one)
 *   - real US wildfires, newest first, from the national incident system: set one up
 *     (the server builds the area from national data in about 15-60 seconds)
 *   - any place, by coordinates
 */

import { useEffect, useState } from "react";
import { LIVE_URL } from "@/route";
import { ago } from "@/time";
import styles from "./LivePicker.module.css";

interface Fire {
  id: string;
  name: string;
  place: string;
  acres: number | null;
  status: string;
  discovered_at: string | null;
}

interface Area {
  name: string;
  description: string;
  incident: Fire | null;
  feeds_pulled_at: string | null;
  fire_weather: string[];
}

export default function LivePicker({ onOpen }: { onOpen: (area: string) => void }) {
  const [areas, setAreas] = useState<Area[] | null>(null);
  const [fires, setFires] = useState<Fire[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [place, setPlace] = useState({ name: "", lat: "", lon: "" });

  useEffect(() => {
    const load = async () => {
      try {
        const [a, f] = await Promise.all([
          fetch(`${LIVE_URL}/areas`).then((r) => r.json() as Promise<Area[]>),
          fetch(`${LIVE_URL}/fires?days=3`).then((r) => r.json() as Promise<Fire[]>),
        ]);
        setAreas(a);
        setFires(f);
      } catch {
        setError(`Can't reach the live server at ${LIVE_URL}. Start it with: make live`);
      }
    };
    void load();
  }, []);

  const setUp = async (label: string, body: object) => {
    setBusy(label);
    setError(null);
    try {
      const res = await fetch(`${LIVE_URL}/areas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = ((await res.json()) as { detail?: unknown }).detail;
        throw new Error(typeof detail === "string" ? detail : "check the name and coordinates");
      }
      onOpen(((await res.json()) as Area).name);
    } catch (e) {
      setError(`Couldn't set up ${label}: ${(e as Error).message || "server error"}`);
      setBusy(null);
    }
  };

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <h1 className={styles.h1}>Live: any US area, on today's data</h1>
        <p className={styles.lead}>
          Pick a real fire and Outrun sets up the area around it from national data: who may
          need a ride (Census), nursing homes (Medicare), open shelters (FEMA), today's
          satellites, wind and alerts. Then it plans, and a manager approves.
        </p>
        {error && <p className={styles.error}>{error}</p>}
        {busy && <p className={styles.busy}>Setting up {busy}… usually 15-60 seconds.</p>}

        {areas && areas.length > 0 && (
          <section>
            <h2 className={styles.h2}>Areas set up</h2>
            {areas.map((a) => (
              <button key={a.name} className={styles.row} onClick={() => onOpen(a.name)}
                      disabled={busy !== null}>
                <span className={styles.name}>{a.incident ? `🔥 ${a.incident.name}` : a.name}</span>
                <span className={styles.place}>{a.description}</span>
                <span className={styles.meta}>
                  {a.fire_weather.length > 0 && <span className={styles.flag}>Red Flag</span>}
                  feeds {ago(a.feeds_pulled_at)}
                </span>
              </button>
            ))}
          </section>
        )}

        <section>
          <h2 className={styles.h2}>Real US wildfires, newest first</h2>
          <p className={styles.small}>
            From the national wildfire incident system (NIFC). Most are small and put out
            quickly: that is what a normal day looks like.
          </p>
          {fires === null && !error && <p className={styles.small}>Loading…</p>}
          {fires?.slice(0, 25).map((f) => (
            <button key={f.id} className={styles.row} disabled={busy !== null}
                    onClick={() => void setUp(f.name, { fire_id: f.id })}>
              <span className={styles.name}>{f.name}</span>
              <span className={styles.place}>{f.place}</span>
              <span className={styles.meta}>
                {f.acres != null && `${f.acres.toLocaleString()} ac · `}
                {f.status} · {ago(f.discovered_at)}
              </span>
            </button>
          ))}
        </section>

        <section>
          <h2 className={styles.h2}>Any place</h2>
          <form
            className={styles.form}
            onSubmit={(e) => {
              e.preventDefault();
              void setUp(place.name, {
                name: place.name, lat: Number(place.lat), lon: Number(place.lon),
              });
            }}
          >
            <input placeholder="name, e.g. paradise-ca" value={place.name} required
                   onChange={(e) => setPlace({ ...place, name: e.target.value })} />
            <input placeholder="latitude" value={place.lat} required inputMode="decimal"
                   onChange={(e) => setPlace({ ...place, lat: e.target.value })} />
            <input placeholder="longitude" value={place.lon} required inputMode="decimal"
                   onChange={(e) => setPlace({ ...place, lon: e.target.value })} />
            <button type="submit" disabled={busy !== null}>Set up</button>
          </form>
        </section>
      </div>
    </main>
  );
}
