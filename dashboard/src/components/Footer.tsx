/**
 * Footer — honest data statement + attributions, for the screen that is open.
 *   The Eaton night: what is real that night, and what is simulated.
 *   A live area: today's live feeds, and every estimate or example, labeled (from the
 *   area's own list of approximations, backend/area.py).
 * Fixed at the very bottom-left of the screen (over the timeline).
 */

import { useWorld } from "@/context/WorldContext";
import styles from "./Footer.module.css";

const SOURCES = "https://github.com/alighazi288/Outrun/blob/main/DATA_SOURCES.md";

export default function Footer() {
  const { source } = useWorld();
  const live = source.health?.live === true;

  return (
    <footer className={styles.footer}>
      {live ? (
        <>
          <span className={styles.statement}>
            Live, refreshed every 10 min: fire reports (NIFC), satellite detections (NASA
            FIRMS: VIIRS, GOES), wind (NOAA HRRR), alerts (FEMA IPAWS, NWS). People are never
            real: estimated from Census counts.{" "}
            <details className={styles.details}>
              <summary>Estimated or example here</summary>
              <ul>
                {source.health!.approximations.map((a) => <li key={a}>{a}</li>)}
              </ul>
            </details>
          </span>
          <span className={styles.divider}>·</span>
          <a className={styles.link} href={SOURCES} target="_blank" rel="noopener noreferrer">
            Data sources
          </a>
          <span className={styles.divider}>·</span>
          <span className={styles.attributions}>
            Map: OpenFreeMap (OSM) · Census · CMS nursing homes · FEMA · NCES schools
          </span>
        </>
      ) : (
        <>
          <span className={styles.statement}>
            Fire reports, satellite detections, wind forecasts, roads, care facilities,
            shelters, the bus fleet and evacuation alerts are real. People who need help,
            and their calls, are simulated from Census counts; van and ambulance numbers are
            assumptions.
          </span>
          <span className={styles.divider}>·</span>
          <a className={styles.link} href={SOURCES} target="_blank" rel="noopener noreferrer">
            Data sources
          </a>
          <span className={styles.divider}>·</span>
          <span className={styles.attributions}>
            Map: OpenFreeMap (OSM) · Alerts: LA County · Detections: NASA FIRMS, NOAA ·
            Facilities: CDSS · Census: US Census Bureau
          </span>
        </>
      )}
    </footer>
  );
}
