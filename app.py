import os
import glob
from datetime import datetime, timezone, timedelta
import requests
import numpy as np
import pandas as pd
import streamlit as st
import pydeck as pdk

# ==============================================================================
# 1. FIXED PHYSICAL-STATISTICAL CONSTANTS & GLOBAL PLANETARY SCANNER
# ==============================================================================
FIXED_SIGMA_GATE = 3.0


@st.cache_data(ttl=300)
def load_territory_matrix(csv_path="Matrix.csv"):
    """Loads the 34-corridor spatial matrix regardless of filename case or subfolder."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, csv_path),
        os.path.join(base_dir, "matrix.csv"),
        os.path.join(base_dir, "Matrix.csv"),
    ] + glob.glob(os.path.join(base_dir, "**", "*[Mm]atrix*.csv"), recursive=True)

    for path in candidates:
        if os.path.exists(path):
            df = pd.read_csv(path)
            df["territory_name"] = df["territory_name"].astype(str).str.strip()
            return df

    raise FileNotFoundError(f"Could not locate Matrix.csv in {base_dir}.")


def haversine_km(lat1, lon1, lat2, lon2):
    """Computes great-circle distance in kilometers between two coordinates."""
    r = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    return float(2 * r * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))


@st.cache_data(ttl=600, show_spinner=False)
def fetch_global_usgs_quakes(now_iso_hour):
    """Fetches all M2.5+ global earthquakes over the past 72h in a single fast API call."""
    now_utc = datetime.fromisoformat(now_iso_hour).replace(tzinfo=timezone.utc)
    start_utc = now_utc - timedelta(hours=72)
    events = []
    try:
        url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
        params = {
            "format": "geojson",
            "starttime": start_utc.strftime("%Y-%m-%dT%H:%M:%S"),
            "endtime": now_utc.strftime("%Y-%m-%dT%H:%M:%S"),
            "minmagnitude": 2.5,
        }
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            for feat in resp.json().get("features", []):
                coords = feat.get("geometry", {}).get("coordinates", [])
                props = feat.get("properties", {})
                if len(coords) >= 2 and props.get("time"):
                    events.append(
                        {
                            "lon": float(coords[0]),
                            "lat": float(coords[1]),
                            "mag": float(props.get("mag") or 0.0),
                            "time_ms": int(props["time"]),
                        }
                    )
    except Exception:
        pass
    return events


@st.cache_data(ttl=600, show_spinner=False)
def fetch_batch_open_meteo(lats_tuple, lons_tuple):
    """Fetches past-72h hourly rainfall & soil moisture for all corridors in a single batch call."""
    results = {}
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": ",".join(f"{x:.4f}" for x in lats_tuple),
            "longitude": ",".join(f"{x:.4f}" for x in lons_tuple),
            "hourly": "precipitation,soil_moisture_7_to_28cm",
            "past_days": 3,
            "forecast_days": 1,
            "timezone": "UTC",
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                data = [data]
            for idx, item in enumerate(data):
                hourly = item.get("hourly", {})
                results[idx] = {
                    "time": hourly.get("time", []),
                    "precipitation": hourly.get("precipitation", []),
                    "soil_moisture": hourly.get("soil_moisture_7_to_28cm", []),
                }
    except Exception:
        pass
    return results


def evaluate_all_corridors(df_zones, live_mode=True, now_utc=None):
    """Sweeps all 34 corridors simultaneously and ranks active bottlenecks at the top."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_hour_iso = now_utc.replace(minute=0, second=0, microsecond=0).isoformat()
    start_utc = now_utc - timedelta(hours=72)
    timestamps = [now_utc - timedelta(hours=6 * (12 - i)) for i in range(13)]

    global_quakes = fetch_global_usgs_quakes(now_hour_iso) if live_mode else []
    batch_meteo = (
        fetch_batch_open_meteo(
            tuple(df_zones["latitude"].astype(float).tolist()),
            tuple(df_zones["longitude"].astype(float).tolist()),
        )
        if live_mode
        else {}
    )

    telemetry_map = {}
    triage_rows = []

    for idx, row in df_zones.iterrows():
        name = row["territory_name"]
        node_id = int(row["node_id"])
        tau_1 = float(row["tau_1_threshold"])
        tau_2 = float(row["tau_2_ceiling"])
        elev = float(row["elevation_m"])
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        is_haven = "safe haven" in name.lower()

        if live_mode:
            seismic_bins = np.zeros(13)
            quake_count = 0
            max_mag = 0.0
            for q in global_quakes:
                if abs(q["lat"] - lat) <= 3.5 and abs(q["lon"] - lon) <= 3.5:
                    if haversine_km(lat, lon, q["lat"], q["lon"]) <= 300.0:
                        quake_count += 1
                        max_mag = max(max_mag, q["mag"])
                        ev_dt = datetime.fromtimestamp(q["time_ms"] / 1000.0, tz=timezone.utc)
                        hrs_ago = (now_utc - ev_dt).total_seconds() / 3600.0
                        bin_idx = int(np.clip(12 - round(hrs_ago / 6.0), 0, 12))
                        seismic_bins[bin_idx] += (10 ** (0.75 * max(0.0, q["mag"] - 2.0))) * 0.14

            rain_bins = np.zeros(13)
            total_rain_72h = 0.0
            soil_moisture_pct = None
            m_data = batch_meteo.get(idx, {})
            if m_data:
                valid_soils = []
                for t_str, p_val, s_val in zip(
                    m_data.get("time", []),
                    m_data.get("precipitation", []),
                    m_data.get("soil_moisture", []),
                ):
                    dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
                    if start_utc <= dt <= now_utc:
                        hrs_ago = (now_utc - dt).total_seconds() / 3600.0
                        bin_idx = int(np.clip(12 - round(hrs_ago / 6.0), 0, 12))
                        p_clean = float(p_val or 0.0)
                        rain_bins[bin_idx] += p_clean
                        total_rain_72h += p_clean
                        if s_val is not None:
                            valid_soils.append(float(s_val))
                if valid_soils:
                    soil_moisture_pct = float(np.clip((valid_soils[-1] / 0.45) * 100.0, 15.0, 98.5))

            baseline_noise = 0.45 + (0.15 if elev < 50 else 0.0)
            hydro_sigma = (rain_bins / 12.0) * 1.45
            sigma_series = np.clip(baseline_noise + seismic_bins + hydro_sigma, 0.35, 4.50)

            if soil_moisture_pct is not None:
                rain_boost = min(24.0, total_rain_72h * 0.38)
                seismic_boost = min(18.0, max_mag * 2.4) if quake_count > 0 else 0.0
                saturation_pct = float(
                    np.clip(soil_moisture_pct * 0.72 + rain_boost + seismic_boost, 22.0, 99.0)
                )
            else:
                saturation_pct = float(np.clip(45.0 + np.mean(sigma_series[-4:]) * 14.0, 25.0, 98.5))

            source_summary = (
                f"LIVE FEEDS — USGS (300km): {quake_count} quakes (Max M{max_mag:.1f}) | "
                f"Open-Meteo 72h Rain: {total_rain_72h:.1f} mm"
            )
        else:
            rng = np.random.default_rng(seed=2026 + node_id * 17)
            base_level = 1.10 + (100.0 - tau_1) * 0.035 + (0.20 if elev < 50 else 0.0)
            wave = np.sin(np.linspace(0.2, np.pi * 1.15, 13)) * 1.15
            noise = rng.normal(0, 0.08, 13)
            sigma_series = np.clip(base_level + wave + noise, 0.75, 3.85)
            cumulative_load = float(np.mean(sigma_series[-4:]))
            saturation_pct = float(
                np.clip(tau_1 - 6.5 + (cumulative_load / 3.0) * (tau_2 - tau_1 + 8.0), 40.0, 99.2)
            )
            quake_count = 0
            max_mag = 0.0
            total_rain_72h = 0.0
            source_summary = "STRESS-TEST DRILL - Simulated Post-Peak Drainage Lag Scenario"
