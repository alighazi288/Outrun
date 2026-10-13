/**
 * Footer — honest data statement + attributions.
 * Fixed at the very bottom-left of the screen (over the timeline).
 */

import styles from "./Footer.module.css";

export default function Footer() {
  return (
    <footer className={styles.footer}>
      <span className={styles.statement}>
        Fire reports, satellite detections, wind forecasts, roads, care
        facilities, shelters, the bus fleet and evacuation alerts are real.
        People who need help, and their calls, are simulated from Census counts;
        van and ambulance numbers are assumptions.
      </span>
      <span className={styles.divider}>·</span>
      <a
        className={styles.link}
        href="https://github.com/your-org/outrun/blob/main/DATA_SOURCES.md"
        target="_blank"
        rel="noopener noreferrer"
      >
        Data sources
      </a>
      <span className={styles.divider}>·</span>
      <span className={styles.attributions}>
        Map: OpenFreeMap (OSM) · Fire reports: LA County · Detections: NASA
        FIRMS, NOAA · Facilities: CDSS · Census: US Census Bureau
      </span>
    </footer>
  );
}
