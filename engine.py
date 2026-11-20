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
        resp = requests.get(url, params=params, timeout=5)
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


def evaluate_all_corridors(df_zones, live_mode=True, now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_hour_iso = now_utc.replace(minute=0, second=0, microsecond=0).isoformat()
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

            baseline_noise = 0.45 + (0.15 if elev < 50 else 0.0)
            sigma_series = np.clip(baseline_noise + seismic_bins, 0.35, 4.20)
            saturation_pct = float(np.clip(45.0 + np.mean(sigma_series[-4:]) * 14.0 + (max_mag * 2.0), 25.0, 98.5))
            source_summary = f"LIVE USGS FEED (300km): {quake_count} quakes (Max M{max_mag:.1f})"
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
            source_summary = "STRESS-TEST DRILL — Simulated Post-Peak Drainage Lag Scenario"

        current_sigma = float(sigma_series[-1])
        peak_idx = int(np.argmax(sigma_series))
        peak_sigma = float(sigma_series[peak_idx])
        peak_time_utc = timestamps[peak_idx]

        phase = (
            "RISING / CRESTING NOW"
            if peak_idx >= 11
            else f"POST-PEAK (Peak {peak_sigma:.2f}σ at {peak_time_utc.strftime('%d %b %H:%M UTC')})"
        )

        recent_rate_per_hr = max(
            0.15,
            (sigma_series[-1] - sigma_series[-3]) / 12.0 + max(0.0, saturation_pct - tau_1) * 0.04,
        )
        headroom_pct = max(0.0, tau_2 - saturation_pct)
        hours_to_tau2 = headroom_pct / recent_rate_per_hr
        deadline_utc = now_utc + timedelta(hours=hours_to_tau2)

        is_sigma_breach = current_sigma >= FIXED_SIGMA_GATE
        is_tau1_breach = saturation_pct >= tau_1

        if is_haven:
            alert_tier = "SAFE HAVEN"
            severity_score = -100.0
        elif is_sigma_breach and is_tau1_breach:
            alert_tier = "RED / CRITICAL BREACH"
            severity_score = 150.0 + (saturation_pct - tau_1) + peak_sigma * 5.0
        elif is_sigma_breach or is_tau1_breach or peak_sigma >= 3.5:
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
        }

        if not is_haven:
            triage_rows.append(
                {
                    "Status": alert_tier,
                    "Node": node_id,
                    "Corridor": name,
                    "Now σ": round(current_sigma, 2),
                    "72h Peak σ": round(peak_sigma, 2),
                    "Saturation %": round(saturation_pct, 1),
                    "τ₁ Limit %": round(tau_1, 1),
                    "Headroom %": round(headroom_pct, 1),
                    "Quakes (72h)": quake_count if live_mode else "-",
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
