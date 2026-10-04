# %% [markdown]
# # Daniel – FIRMS VIIRS detections for the Eaton Fire (Jan 7–9 2025)
#
# Fetches NASA FIRMS data for the Eaton Fire study area, checks source availability,
# and writes `data/processed/eaton/detections.jsonl`.

# %% -- imports & config -------------------------------------------------------
import io
import os
import re
import warnings
from datetime import UTC, timedelta
from datetime import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyproj
import requests
import xarray as xr
from dotenv import load_dotenv
from goes2go import GOES
from herbie import Herbie
from matplotlib.patches import Patch

load_dotenv(Path("../.env"))

FIRMS_MAP_KEY = os.environ["FIRMS_MAP_KEY"]

# Study bounding box: Altadena + 1 km buffer
W, S, E, N = -118.23, 34.12, -118.03, 34.26
LAKE_AVE_LON = -118.131

RAW = "../data/raw"

print(f"FIRMS_MAP_KEY loaded: {'*' * 8}{FIRMS_MAP_KEY[-4:]}")
print(f"Study box  W={W} S={S} E={E} N={N}")
print(f"Lake Ave lon: {LAKE_AVE_LON}")
print(f"RAW dir: {Path(RAW).resolve()}")

# %% -- check FIRMS data availability for VIIRS sources -----------------------
url = f"https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{FIRMS_MAP_KEY}/ALL"
print(f"Fetching: {url.replace(FIRMS_MAP_KEY, '****')}")

resp = requests.get(url, timeout=30)
resp.raise_for_status()

avail = pd.read_csv(io.StringIO(resp.text))
print(f"\nAll columns: {avail.columns.tolist()}")
print(f"Total sources: {len(avail)}")
print(avail.head(3))

# %% -- filter: VIIRS sources covering 2025-01-07 to 2025-01-10 ---------------
# FIRMS date columns vary by version; normalise to lowercase
avail.columns = [c.strip().lower().replace(" ", "_") for c in avail.columns]
print(f"\nNormalised columns: {avail.columns.tolist()}")

# The availability endpoint uses 'data_id' as the source name column
id_col = "data_id" if "data_id" in avail.columns else "source"

# Keep VIIRS rows
viirs = avail[avail[id_col].str.contains("VIIRS", case=False, na=False)].copy()

# Parse the min/max date columns (column names differ across FIRMS API versions)
start_col = next((c for c in ["min_date", "start_date"] if c in viirs.columns), None)
end_col   = next((c for c in ["max_date", "end_date"]   if c in viirs.columns), None)

TARGET_START = pd.Timestamp("2025-01-07")
TARGET_END   = pd.Timestamp("2025-01-10")

if start_col and end_col:
    viirs[start_col] = pd.to_datetime(viirs[start_col], errors="coerce")
    viirs[end_col]   = pd.to_datetime(viirs[end_col],   errors="coerce")
    covers = viirs[
        (viirs[start_col] <= TARGET_END) & (viirs[end_col] >= TARGET_START)
    ]
else:
    print("WARNING: could not identify date columns; showing all VIIRS rows")
    covers = viirs

print(f"\nVIIRS sources covering {TARGET_START.date()} – {TARGET_END.date()}:")
display_cols = [id_col] + ([start_col, end_col] if start_col else [])
print(covers[display_cols].to_string(index=False))

# %% -- download VIIRS detections from FIRMS area API -------------------------
# SP sources cover Jan 2025; NOAA-21 only has NRT for this period.
VIIRS_SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT"]
RAW_CSV = Path(RAW) / "firms" / "viirs_eaton_2025-01-07_to_10.csv"

if RAW_CSV.exists():
    print(f"Found existing file, loading from {RAW_CSV}")
    detections_raw = pd.read_csv(RAW_CSV)
else:
    frames = []
    for source in VIIRS_SOURCES:
        url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv"
            f"/{FIRMS_MAP_KEY}/{source}/{W},{S},{E},{N}/4/2025-01-07"
        )
        print(f"Fetching {source} …  {url.replace(FIRMS_MAP_KEY, '****')}")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or not text.startswith("latitude"):
            print(f"  ↳ Non-CSV response for {source}:\n    {text[:300]}")
            continue
        df = pd.read_csv(io.StringIO(text))
        df["firms_source"] = source
        print(f"  ↳ {len(df):,} rows")
        frames.append(df)

    if not frames:
        raise RuntimeError("No data returned from any FIRMS source — check your MAP KEY and bbox")

    detections_raw = pd.concat(frames, ignore_index=True)
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    detections_raw.to_csv(RAW_CSV, index=False)
    print(f"\nSaved → {RAW_CSV}")

print(f"\nTotal rows: {len(detections_raw):,}")
print("\nRows per source:")
print(detections_raw["firms_source"].value_counts().to_string())
print("\nColumns:", detections_raw.columns.tolist())
print(detections_raw.head(3))

# %% -- parse times, add west_of_lake flag ------------------------------------
PACIFIC = ZoneInfo("America/Los_Angeles")

df = detections_raw.copy()

# acq_time is an integer like 130 (= 01:30 UTC) or 2345 (= 23:45 UTC); zero-pad to 4 digits
df["acq_time_str"] = df["acq_time"].astype(int).astype(str).str.zfill(4)

# Build a UTC datetime string and parse as UTC
df["observed_utc"] = pd.to_datetime(
    df["acq_date"] + " " + df["acq_time_str"].str[:2] + ":" + df["acq_time_str"].str[2:],
    utc=True,
)

# Convert to Pacific (handles PST/PDT automatically; Jan 7–8 is PST = UTC-8)
df["observed_at"] = df["observed_utc"].dt.tz_convert(PACIFIC)

# West-of-Lake-Avenue flag
df["west_of_lake"] = df["longitude"] < LAKE_AVE_LON

# Sort by time
df = df.sort_values("observed_at").reset_index(drop=True)

show_cols = [
    "observed_at", "satellite", "latitude", "longitude",
    "frp", "confidence", "west_of_lake",
]
print("=== First 10 detections ===")
print(df[show_cols].head(10).to_string(index=False))
print("\n=== Last 10 detections ===")
print(df[show_cols].tail(10).to_string(index=False))
print(f"\nTotal: {len(df):,}  |  west_of_lake: {df['west_of_lake'].sum():,}")

# %% -- figure 1: detection map + overpass bar chart --------------------------
FIG_DIR = Path(RAW) / "firms"

# Numeric time axis: seconds since first detection (for colormap)
t0 = df["observed_at"].min()
df["_t_sec"] = (df["observed_at"] - t0).dt.total_seconds()

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# --- panel 1: spatial map coloured by time ---
ax = axes[0]
sc = ax.scatter(
    df["longitude"], df["latitude"],
    c=df["_t_sec"], cmap="plasma", s=8, alpha=0.7,
    vmin=0, vmax=df["_t_sec"].max(),
)
ax.axvline(LAKE_AVE_LON, color="cyan", linestyle="--", linewidth=1.2, label="Lake Ave")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_title("VIIRS detections – Eaton Fire bbox")
ax.legend(fontsize=8)

# Colorbar ticks in Pacific time
cbar = fig.colorbar(sc, ax=ax, pad=0.02)
cbar.set_label("Observed (Pacific time)")
tick_sec = np.linspace(0, df["_t_sec"].max(), 6)
cbar.set_ticks(tick_sec)
cbar.set_ticklabels([
    (t0 + pd.Timedelta(seconds=s)).strftime("%m/%d %H:%M")
    for s in tick_sec
])

# --- panel 2: detections per overpass (group by observed_at × satellite) ---
ax2 = axes[1]
overpass = (
    df.groupby(["observed_at", "satellite"])
    .size()
    .reset_index(name="count")
    .sort_values("observed_at")
)
# Convert tz-aware timestamps to matplotlib-friendly floats
x_vals = mdates.date2num(overpass["observed_at"].dt.to_pydatetime())
colors_sat = {"N": "#1f77b4", "N20": "#ff7f0e", "N21": "#2ca02c"}
bar_colors = overpass["satellite"].map(lambda s: colors_sat.get(s, "#888888"))
ax2.bar(x_vals, overpass["count"], width=0.01, color=bar_colors, align="center")
ax2.xaxis_date()
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M", tz=PACIFIC))
ax2.xaxis.set_major_locator(mdates.HourLocator(interval=12, tz=PACIFIC))
fig.autofmt_xdate(rotation=30, ha="right")
ax2.set_xlabel("Overpass time (Pacific)")
ax2.set_ylabel("Detection count")
ax2.set_title("Detections per overpass")
# Legend for satellite colours
ax2.legend(handles=[Patch(color=v, label=k) for k, v in colors_sat.items()],
           title="Satellite", fontsize=8)

fig.tight_layout()
out1 = FIG_DIR / "fig1_map_and_bar.png"
fig.savefig(out1, dpi=150)
plt.close(fig)
print(f"Saved → {out1}")

# %% -- figure 2: small-multiples map per overpass (Jan 7–8 only) -------------
jan78 = df[df["observed_at"] < pd.Timestamp("2025-01-09", tz=PACIFIC)].copy()
passes = (
    jan78.groupby(["observed_at", "satellite"])
    .size()
    .reset_index()
    .sort_values("observed_at")
)
n = len(passes)
ncols = 4
nrows = (n + ncols - 1) // ncols

LON_LIM = (W, E)
LAT_LIM = (S, N)

fig2, axes2 = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.5 * nrows))
axes2_flat = axes2.flat if n > 1 else [axes2]

for i, (_, row) in enumerate(passes.iterrows()):
    ax = axes2_flat[i]
    mask = (jan78["observed_at"] == row["observed_at"]) & (jan78["satellite"] == row["satellite"])
    sub = jan78[mask]
    ax.scatter(sub["longitude"], sub["latitude"], c=sub["frp"],
               cmap="hot_r", s=12, vmin=0, vmax=jan78["frp"].quantile(0.95))
    ax.axvline(LAKE_AVE_LON, color="cyan", linestyle="--", linewidth=0.8)
    ax.set_xlim(LON_LIM)
    ax.set_ylim(LAT_LIM)
    ax.set_title(
        f"{row['observed_at'].strftime('%m/%d %H:%M')} {row['satellite']}  n={len(sub)}",
        fontsize=7,
    )
    ax.tick_params(labelsize=6)

# Hide unused subplots
for j in range(i + 1, nrows * ncols):
    axes2_flat[j].set_visible(False)

fig2.suptitle("VIIRS overpasses – Eaton Fire area, Jan 7–8 PST (colour = FRP MW)", fontsize=10)
fig2.tight_layout()
out2 = FIG_DIR / "fig2_small_multiples_jan78.png"
fig2.savefig(out2, dpi=150)
plt.close(fig2)
print(f"Saved → {out2}")

# %% -- GOES-18 ABI-L2-FDCC fire detection -----------------------------------
# Run with: uv run --with goes2go python daniel_firms_eaton.py
# goes2go and pyproj are not in pyproject.toml; injected at runtime via --with.
GOES_DIR = Path("../data/raw/goes")
GOES_DIR.mkdir(parents=True, exist_ok=True)

# --- list + download GOES-18 FDCC files for 2025-01-08 02:00–11:30 UTC -------
g = GOES(satellite=18, product="ABI-L2-FDCC", domain="C")
files = g.df(
    start="2025-01-08 02:00",
    end="2025-01-08 11:30",
)
print(f"Found {len(files)} GOES-18 FDCC files")
print(files[["start", "end"]].head(5))

# Download all files via timerange(); returns a DataFrame with a relative 'file' column
dl = g.timerange(
    start="2025-01-08 02:00",
    end="2025-01-08 11:30",
    save_dir=str(GOES_DIR),
    return_as="filelist",
)
local_files = [str(GOES_DIR / row) for row in dl["file"]]
print(f"\nDownloaded/cached {len(local_files)} files")
print("First file:", local_files[0])

# %% -- open ONE file, build lat/lon with pyproj, sanity-check ----------------
def goes_latlon(ds):
    """Return (lon2d, lat2d) arrays for a GOES ABI file using pyproj."""
    proj_var = ds["goes_imager_projection"]
    h     = float(proj_var.attrs["perspective_point_height"])
    lon0  = float(proj_var.attrs["longitude_of_projection_origin"])
    sweep = proj_var.attrs["sweep_angle_axis"]
    a     = float(proj_var.attrs["semi_major_axis"])
    b     = float(proj_var.attrs["semi_minor_axis"])

    p = pyproj.Proj(proj="geos", h=h, lon_0=lon0, sweep=sweep, a=a, b=b)

    # x, y are in radians; multiply by h to get metres in geostationary plane
    x_m = ds["x"].values * h   # shape (ncols,)
    y_m = ds["y"].values * h   # shape (nrows,)
    xx, yy = np.meshgrid(x_m, y_m)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lon2d, lat2d = p(xx, yy, inverse=True)

    # Off-earth pixels come back as 1e30; set to NaN
    lon2d = np.where(np.abs(lon2d) > 360, np.nan, lon2d)
    lat2d = np.where(np.abs(lat2d) > 90,  np.nan, lat2d)
    return lon2d, lat2d


# Open first file
ds0 = xr.open_dataset(local_files[0])
lon2d, lat2d = goes_latlon(ds0)

# --- sanity check 1: pixel nearest (34.19, -118.13) ---------------------------
TARGET_LAT, TARGET_LON = 34.19, -118.13
dist2 = (lat2d - TARGET_LAT)**2 + (lon2d - TARGET_LON)**2
dist2_nonan = np.where(np.isnan(dist2), np.inf, dist2)
row_i, col_i = np.unravel_index(np.argmin(dist2_nonan), dist2_nonan.shape)
near_lat = lat2d[row_i, col_i]
near_lon = lon2d[row_i, col_i]
err = np.sqrt((near_lat - TARGET_LAT)**2 + (near_lon - TARGET_LON)**2)
print(f"\nSanity 1 – nearest pixel to ({TARGET_LAT}, {TARGET_LON}):")
ok1 = "✓" if err < 0.03 else "✗ TOO LARGE"
print(f"  found ({near_lat:.4f}, {near_lon:.4f}), error = {err:.4f}°  {ok1}")

# --- sanity check 2: pixel count inside study box ----------------------------
in_box = (
    (lon2d >= W) & (lon2d <= E) &
    (lat2d >= S) & (lat2d <= N)
)
n_box = int(np.sum(in_box))
ok2 = "✓ (expect 30–80)" if 30 <= n_box <= 80 else "✗ unexpected"
print(f"\nSanity 2 – pixels inside study box: {n_box}  {ok2}")

# --- Mask value counts for a file near 06:00 UTC 2025-01-08 ------------------
# Find the file closest to 06:00 UTC
TARGET_UTC = dt(2025, 1, 8, 6, 0, tzinfo=UTC)


def file_time_utc(path):
    """Parse scan start time from GOES filename: ...s20250080600...  → datetime UTC."""
    name = Path(path).name
    # GOES filename: ...sYYYYDDDHHMMSSf... where DDD is day-of-year
    m = re.search(r"_s(\d{14})", name)
    if not m:
        return None
    s = m.group(1)  # e.g. 20250080600173
    return dt(int(s[:4]), 1, 1, tzinfo=UTC) + timedelta(
        days=int(s[4:7]) - 1,
        hours=int(s[7:9]),
        minutes=int(s[9:11]),
        seconds=int(s[11:13]),
    )

times_utc = [file_time_utc(f) for f in local_files]
diffs = [abs((t - TARGET_UTC).total_seconds()) if t else float("inf") for t in times_utc]
closest_idx = int(np.argmin(diffs))
closest_file = local_files[closest_idx]
print(f"\nFile closest to 06:00 UTC: {Path(closest_file).name}")

ds_check = xr.open_dataset(closest_file)
lon_c, lat_c = goes_latlon(ds_check)
in_box_c = (lon_c >= W) & (lon_c <= E) & (lat_c >= S) & (lat_c <= N)
mask_vals = ds_check["Mask"].values[in_box_c]
vc = pd.Series(mask_vals.astype(int)).value_counts().sort_index()
print("Mask value counts inside study box (06:00 UTC file):")
print(vc.to_string())
ds_check.close()

# %% -- loop over all files, build fire-pixel time series ---------------------
FIRE_MASK_VALS = set(range(10, 16)) | set(range(30, 36))

records = []
for fpath, t_utc in zip(local_files, times_utc, strict=False):
    if t_utc is None:
        continue
    t_pac = t_utc.astimezone(PACIFIC)
    try:
        ds = xr.open_dataset(fpath)
        lon_f, lat_f = goes_latlon(ds)
        mask_arr = ds["Mask"].values
        ds.close()
    except Exception as e:
        print(f"  skip {Path(fpath).name}: {e}")
        continue

    in_box_f = (lon_f >= W) & (lon_f <= E) & (lat_f >= S) & (lat_f <= N)
    box_mask = mask_arr[in_box_f]
    fire_total = int(np.isin(box_mask, list(FIRE_MASK_VALS)).sum())

    west_mask = (lon_f >= W) & (lon_f < LAKE_AVE_LON) & (lat_f >= S) & (lat_f <= N)
    w_mask_vals = mask_arr[west_mask]
    fire_west = int(np.isin(w_mask_vals, list(FIRE_MASK_VALS)).sum())

    records.append({
        "time_pac": t_pac,
        "fire_pixels_box": fire_total,
        "fire_pixels_west": fire_west,
    })

goes_ts = pd.DataFrame(records).sort_values("time_pac").reset_index(drop=True)
print(f"\nBuilt time series: {len(goes_ts)} rows")
print(goes_ts[goes_ts["fire_pixels_box"] > 0].head(20).to_string(index=False))

# save table
goes_csv = GOES_DIR / "goes18_fdcc_fire_pixels_jan8.csv"
goes_ts.to_csv(goes_csv, index=False)
print(f"Saved → {goes_csv}")

# %% -- plot GOES fire-pixel counts over time ----------------------------------
fig3, ax3 = plt.subplots(figsize=(12, 4))
ax3.plot(
    goes_ts["time_pac"], goes_ts["fire_pixels_box"],
    label="Fire pixels – whole box", color="orangered",
)
ax3.plot(
    goes_ts["time_pac"], goes_ts["fire_pixels_west"],
    label="Fire pixels – west of Lake Ave", color="firebrick", linestyle="--",
)
ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M", tz=PACIFIC))
ax3.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=PACIFIC))
fig3.autofmt_xdate(rotation=30, ha="right")
ax3.set_xlabel("Time (Pacific)")
ax3.set_ylabel("GOES-18 FDCC fire pixels")
ax3.set_title("GOES-18 ABI-L2-FDCC fire detections – Eaton Fire area, Jan 8 2025")
ax3.legend()
fig3.tight_layout()
out3 = GOES_DIR / "fig3_goes18_fire_pixels.png"
fig3.savefig(out3, dpi=150)
plt.close(fig3)
print(f"Saved → {out3}")

# %% -- HRRR wind: single run inspection --------------------------------------
# herbie is already installed via --extra wx; h5py/netCDF4 added via --with
HRRR_DIR = Path("../data/raw/hrrr")
HRRR_DIR.mkdir(parents=True, exist_ok=True)

H = Herbie(
    "2025-01-08 06:00",
    model="hrrr",
    product="sfc",
    fxx=1,
    save_dir=str(HRRR_DIR),
)

# --- load 10 m wind components and surface gusts ----------------------------
ds_uv   = H.xarray(":(?:UGRD|VGRD):10 m above ground", remove_grib=False)
ds_gust = H.xarray(":GUST:surface", remove_grib=False)
print("Wind dataset:\n", ds_uv)
print("\nGust dataset:\n", ds_gust)

# Merge into one dataset for convenience
ds_wind = xr.merge([ds_uv, ds_gust])

# --- fix longitudes: HRRR uses 0–360, convert to –180..180 ------------------
# Use the UV dataset directly for coordinates (avoids merge coordinate issues)
lon_raw = ds_uv["longitude"].values.copy()
lon_180 = np.where(lon_raw > 180, lon_raw - 360, lon_raw)
lat_arr = ds_uv["latitude"].values

# --- resolve actual variable names from cfgrib (u/v component discovery) ----
# UGRD → shortName "u10" (heightAboveGround:10); VGRD → "v10"
uv_vars  = list(ds_uv.data_vars)
u_name   = next((v for v in uv_vars if v.startswith("u")), uv_vars[0])
v_name   = next((v for v in uv_vars if v.startswith("v")), uv_vars[1])
print(f"U variable: {u_name},  V variable: {v_name}")

# --- crop to study box -------------------------------------------------------
mask2d = (lon_180 >= W) & (lon_180 <= E) & (lat_arr >= S) & (lat_arr <= N)

u_full = ds_uv[u_name].values
v_full = ds_uv[v_name].values

# Find row/col index range that covers the box (assume regular 2D grid)
rows, cols = np.where(mask2d)
r0, r1 = rows.min(), rows.max() + 1
c0, c1 = cols.min(), cols.max() + 1

lon_box  = lon_180[r0:r1, c0:c1]
lat_box  = lat_arr[r0:r1, c0:c1]
u_box    = u_full[r0:r1, c0:c1]
v_box    = v_full[r0:r1, c0:c1]

# Gust may have a different variable name; find it
gust_var = [v for v in ds_wind.data_vars if "gust" in str(v).lower() or v == "si10"]
if gust_var:
    gust_box = ds_wind[gust_var[0]].values[r0:r1, c0:c1]
    print(f"\nGust variable: {gust_var[0]}, shape: {gust_box.shape}")
else:
    gust_box = None
    print("\nNo gust variable found")

# --- derived wind fields -----------------------------------------------------
speed_ms  = np.hypot(u_box, v_box)
# Meteorological FROM direction: wind blowing FROM the direction it came
dir_from_deg = (np.degrees(np.arctan2(-u_box, -v_box)) + 360) % 360

print(f"\nGrid shape (cropped): {u_box.shape}")
print(f"Speed  – mean: {speed_ms.mean():.2f} m/s,  max: {speed_ms.max():.2f} m/s")
print(f"Dir from (mean): {dir_from_deg.mean():.1f}°")
if gust_box is not None:
    print(f"Gust   – mean: {gust_box.mean():.2f} m/s,  max: {gust_box.max():.2f} m/s")

# --- quiver plot -------------------------------------------------------------
fig4, ax4 = plt.subplots(figsize=(7, 6))

# Thin the quiver so arrows don't overlap (every other point)
step = max(1, min(u_box.shape) // 12)
sc4 = ax4.contourf(lon_box, lat_box, speed_ms, levels=15, cmap="YlOrRd", alpha=0.6)
fig4.colorbar(sc4, ax=ax4, label="Wind speed (m/s)")
ax4.quiver(
    lon_box[::step, ::step], lat_box[::step, ::step],
    u_box[::step, ::step],   v_box[::step, ::step],
    scale=250, width=0.004, color="navy", alpha=0.85,
)
ax4.axvline(LAKE_AVE_LON, color="cyan", linestyle="--", linewidth=1.2, label="Lake Ave")
ax4.set_xlim(W, E)
ax4.set_ylim(S, N)
ax4.set_xlabel("Longitude")
ax4.set_ylabel("Latitude")
ax4.set_title("HRRR 10 m wind – 2025-01-08 07:00 UTC valid (06Z run fxx=1)")
ax4.legend(fontsize=8)
fig4.tight_layout()
out4 = HRRR_DIR / "fig4_hrrr_wind_quiver.png"
fig4.savefig(out4, dpi=150)
plt.close(fig4)
print(f"\nSaved → {out4}")
