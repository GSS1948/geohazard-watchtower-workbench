import os
import glob
from datetime import datetime, timezone, timedelta
import requests
import numpy as np
import pandas as pd

FIXED_SIGMA_GATE = 3.0


def load_territory_matrix(csv_path="Matrix.csv"):
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
    r = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    return float(2 * r * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))


def fetch_global_usgs_quakes(now_iso_hour):
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
        resp = requests.get(url, params=params, timeout=4)
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


def fetch_sector_meteo(lat, lon):
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "hourly": "precipitation,wind_gusts_10m,pressure_msl",
            "past_days": 3,
            "forecast_days": 1,
            "timezone": "UTC",
        }
        resp = requests.get(url, params=params, timeout=3)
        if resp.status_code == 200:
            return resp.json().get("hourly", {})
    except Exception:
        pass
    return {}


def evaluate_all_corridors(df_zones, live_mode=True, now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_hour_iso = now_utc.replace(minute=0, second=0, microsecond=0).isoformat()
    start_utc = now_utc - timedelta(hours=72)
    timestamps = [now_utc - timedelta(hours=6 * (12 - i)) for i in range(13)]
    global_quakes = fetch_global_usgs_quakes(now_hour_iso) if live_mode else []

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
        is_cyclone_zone = any(k in name.lower() for k in ["cyclone", "chennai", "bengal", "delta", "typhoon", "coast"])

        if live_mode:
            quake_count = 0
            max_mag = 0.0
            seismic_bins = np.zeros(13)
            for q in global_quakes:
                if haversine_km(lat, lon, q["lat"], q["lon"]) <= 300.0:
                    quake_count += 1
                    max_mag = max(max_mag, q["mag"])
                    ev_dt = datetime.fromtimestamp(q["time_ms"] / 1000.0, tz=timezone.utc)
                    hrs_ago = (now_utc - ev_dt).total_seconds() / 3600.0
                    bin_idx = int(np.clip(12 - round(hrs_ago / 6.0), 0, 12))
                    seismic_bins[bin_idx] += (10 ** (0.75 * max(0.0, q["mag"] - 2.0))) * 0.14

            rain_bins = np.zeros(13)
            total_rain_72h = 0.0
            max_gust_kmh = 0.0
            min_pressure_hpa = 1013.0
            meteo_active = False

            if is_cyclone_zone and not is_haven:
                hourly = fetch_sector_meteo(lat, lon)
                times = hourly.get("time", [])
                precips = hourly.get("precipitation", [])
                gusts = hourly.get("wind_gusts_10m", [])
                pressures = hourly.get("pressure_msl", [])
                if times:
                    meteo_active = True
                    for t_str, p_val, g_val, pr_val in zip(times, precips, gusts, pressures):
                        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
                        if start_utc <= dt <= now_utc:
                            hrs_ago = (now_utc - dt).total_seconds() / 3600.0
                            bin_idx = int(np.clip(12 - round(hrs_ago / 6.0), 0, 12))
                            p_clean = float(p_val or 0.0)
                            g_clean = float(g_val or 0.0)
                            pr_clean = float(pr_val or 1013.0)
                            rain_bins[bin_idx] += p_clean
                            total_rain_72h += p_clean
                            max_gust_kmh = max(max_gust_kmh, g_clean)
                            min_pressure_hpa = min(min_pressure_hpa, pr_clean)

            baseline_noise = 0.45 + (0.15 if elev < 50 else 0.0)
            hydro_sigma = (rain_bins / 15.0) * 1.6 + (max(0.0, max_gust_kmh - 55.0) / 35.0)
            sigma_series = np.clip(baseline_noise + seismic_bins + hydro_sigma, 0.35, 4.50)

            rain_load = min(32.0, total_rain_72h * 0.35)
            gust_load = min(18.0, max(0.0, max_gust_kmh - 45.0) * 0.35)
            seismic_load = (max_mag * 2.0) if quake_count > 0 else 0.0
            saturation_pct = float(
                np.clip(45.0 + np.mean(sigma_series[-4:]) * 12.0 + rain_load + gust_load + seismic_load, 25.0, 99.0)
            )

            if meteo_active:
                source_summary = (
                    f"MULTI-HAZARD LIVE FEED — Rain 72h: {total_rain_72h:.1f}mm | Max Gust: {max_gust_kmh:.0f} km/h | "
                    f"Min Pressure: {min_pressure_hpa:.0f} hPa | USGS Quakes: {quake_count}"
                )
            else:
                source_summary = f"LIVE USGS SEISMIC FEED (300km): {quake_count} quakes (Max M{max_mag:.1f})"
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
            max_gust_kmh = 0.0
            total_rain_72h = 0.0
            min_pressure_hpa = 1013.0
            source_summary = "STRESS-TEST DRILL — Simulated Fast-Moving Cyclone & Drainage Lag Scenario"

        current_sigma = float(sigma_series[-1])
        peak_idx = int(np.argmax(sigma_series))
        peak_sigma = float(sigma_series[peak_idx])
        peak_time_utc = timestamps[peak_idx]

        delta_sigma_12h = float(sigma_series[-1] - sigma_series[-3])
        rapid_intensification = (delta_sigma_12h >= 1.2) or (max_gust_kmh >= 85.0) or (total_rain_72h >= 110.0)

        phase = (
            "RAPID INTENSIFICATION / SURGING"
            if rapid_intensification
            else (
                "RISING / CRESTING NOW"
                if peak_idx >= 11
                else f"POST-PEAK (Peak {peak_sigma:.2f}σ at {peak_time_utc.strftime('%d %b %H:%M UTC')})"
            )
        )

        recent_rate_per_hr = max(
            0.15,
            delta_sigma_12h / 12.0 + max(0.0, saturation_pct - tau_1) * 0.04,
        )
        headroom_pct = max(0.0, tau_2 - saturation_pct)
        hours_to_tau2 = headroom_pct / recent_rate_per_hr
        deadline_utc = now_utc + timedelta(hours=hours_to_tau2)

        is_sigma_breach = current_sigma >= FIXED_SIGMA_GATE
        is_tau1_breach = saturation_pct >= tau_1

        if is_haven:
            alert_tier = "SAFE HAVEN"
            severity_score = -100.0
        elif (is_sigma_breach and is_tau1_breach) or (rapid_intensification and (is_sigma_breach or is_tau1_breach)):
            alert_tier = "RED / CRITICAL ESCALATION"
            severity_score = 150.0 + (saturation_pct - tau_1) + peak_sigma * 5.0
        elif is_sigma_breach or is_tau1_breach or peak_sigma >= 3.5 or rapid_intensification:
            alert_tier = "ORANGE / HIGH ALERT"
            severity_score = 100.0 + (saturation_pct - tau_1) + peak_sigma * 5.0
        elif peak_sigma >= 2.2 or (tau_1 - saturation_pct) <= 12.0:
            alert_tier = "YELLOW / WATCH"
            severity_score = 50.0 + (saturation_pct - tau_1) + peak_sigma * 5.0
        else:
            alert_tier = "GREEN / NORMAL"
            severity_score = (saturation_pct - tau_1) + peak_sigma * 5.0

        telemetry_map[name] = {
            "now_utc": now_utc,
            "timestamps": timestamps,
            "sigma_series": sigma_series,
            "current_sigma": current_sigma,
            "peak_sigma": peak_sigma,
            "peak_time_utc": peak_time_utc,
            "phase": phase,
            "saturation_pct": saturation_pct,
            "tau_1": tau_1,
            "tau_2": tau_2,
            "headroom_pct": headroom_pct,
            "hours_to_tau2": hours_to_tau2,
            "deadline_utc": deadline_utc,
            "is_sigma_breach": is_sigma_breach,
            "is_tau1_breach": is_tau1_breach,
            "source_summary": source_summary,
            "alert_tier": alert_tier,
            "total_rain_72h": total_rain_72h,
            "max_gust_kmh": max_gust_kmh,
            "min_pressure_hpa": min_pressure_hpa,
        }

        if not is_haven:
            triage_rows.append(
                {
                    "Status": alert_tier,
                    "Node": node_id,
                    "Corridor": name,
                    "Now σ": round(current_sigma, 1),
                    "72h Peak σ": round(peak_sigma, 1),
                    "Saturation %": round(saturation_pct, 1),
                    "τ₁ Limit %": round(tau_1, 1),
                    "Headroom %": round(headroom_pct, 1),
                    "Rain 72h (mm)": round(total_rain_72h, 1),
                    "Max Gust (km/h)": round(max_gust_kmh, 1),
                    "_score": severity_score,
                }
            )

    triage_df = pd.DataFrame(triage_rows).sort_values("_score", ascending=False).reset_index(drop=True)
    return telemetry_map, triage_df


def rank_safe_havens(df_all, active_zone):
    havens = df_all[
        df_all["territory_name"].str.contains("Safe Haven", case=False, na=False)
    ].copy()
    if havens.empty:
        return havens

    lat1, lon1 = float(active_zone["latitude"]), float(active_zone["longitude"])
    elev1 = float(active_zone["elevation_m"])

    havens["distance_km"] = havens.apply(
        lambda r: round(
            haversine_km(lat1, lon1, float(r["latitude"]), float(r["longitude"])), 1
        ),
        axis=1,
    )
    havens["elevation_gain_m"] = (havens["elevation_m"] - elev1).astype(int)
    havens["est_transit_hrs"] = (havens["distance_km"] / 50.0).round(1)
    havens["cap_status"] = havens["distance_km"].apply(
        lambda d: "PRIMARY CORRIDOR (OPEN)" if d < 1200 else "SECONDARY CONTINGENCY"
    )
    return havens.sort_values("distance_km").reset_index(drop=True)
