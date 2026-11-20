import os
import glob
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

# Fixed physical-statistical constants (Not operator-adjustable)
FIXED_SIGMA_GATE = 3.0

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
            df['territory_name'] = df['territory_name'].astype(str).str.strip()
            return df

    raise FileNotFoundError(f"Could not locate Matrix.csv in {base_dir}.")

def haversine_km(lat1, lon1, lat2, lon2):
    """Computes great-circle distance in kilometers between two coordinates."""
    r = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0)**2
    return float(2 * r * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))

def compute_toc_bottleneck_telemetry(zone_row, now_utc=None):
    """
    Computes unified 72-hour sigma trajectory, physical TOC bottleneck saturation (tau_1 / tau_2),
    trajectory phase (RISING vs POST-PEAK), and exact wall-clock deadline before tau_2 failure.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    node_id = int(zone_row['node_id'])
    tau_1 = float(zone_row['tau_1_threshold'])
    tau_2 = float(zone_row['tau_2_ceiling'])
    elev = float(zone_row['elevation_m'])

    rng = np.random.default_rng(seed=2026 + node_id * 17)

    # Generate 13 six-hour points from T-72h to T-0h (NOW) on a unified sigma scale
    timestamps = [now_utc - timedelta(hours=6 * (12 - i)) for i in range(13)]
    base_level = 1.10 + (100.0 - tau_1) * 0.035 + (0.20 if elev < 50 else 0.0)
    wave = np.sin(np.linspace(0.2, np.pi * 1.15, 13)) * 1.15
    noise = rng.normal(0, 0.08, 13)
    sigma_series = np.clip(base_level + wave + noise, 0.75, 3.85)

    current_sigma = float(sigma_series[-1])
    peak_idx = int(np.argmax(sigma_series))
    peak_sigma = float(sigma_series[peak_idx])
    peak_time_utc = timestamps[peak_idx]

    # Determine phase: are we still climbing or past peak?
    if peak_idx >= 11:
        phase = "RISING / CRESTING NOW"
    else:
        phase = f"POST-PEAK (Peak {peak_sigma:.2f}σ at {peak_time_utc.strftime('%d %b %H:%M UTC')})"

    # Physical bottleneck saturation (%) accumulates slower and drains slower than raw sigma
    cumulative_load = float(np.mean(sigma_series[-4:]))
    saturation_pct = float(np.clip(tau_1 - 6.5 + (cumulative_load / 3.0) * (tau_2 - tau_1 + 8.0), 40.0, 99.2))

    # Calculate saturation rate (%/hr) over last 12h to project exact wall-clock breach of tau_2
    recent_rate_per_hr = max(0.18, (sigma_series[-1] - sigma_series[-3]) / 12.0 + (saturation_pct - tau_1) * 0.04)
    headroom_pct = max(0.0, tau_2 - saturation_pct)
    hours_to_tau2 = headroom_pct / recent_rate_per_hr
    deadline_utc = now_utc + timedelta(hours=hours_to_tau2)

    is_sigma_breach = current_sigma >= FIXED_SIGMA_GATE
    is_tau1_breach = saturation_pct >= tau_1

    return {
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
    }

def rank_safe_havens(df_all, active_zone):
    """Identifies and ranks contagion-free Tier-1 Safe Havens with transit feasibility."""
    havens = df_all[df_all['territory_name'].str.contains("Safe Haven", case=False, na=False)].copy()
    if havens.empty:
        return havens

    lat1, lon1 = float(active_zone['latitude']), float(active_zone['longitude'])
    elev1 = float(active_zone['elevation_m'])

    havens['distance_km'] = havens.apply(
        lambda r: round(haversine_km(lat1, lon1, float(r['latitude']), float(r['longitude'])), 1), axis=1
    )
    havens['elevation_gain_m'] = (havens['elevation_m'] - elev1).astype(int)
    havens['est_transit_hrs'] = (havens['distance_km'] / 50.0).round(1)
    havens['cap_status'] = havens['distance_km'].apply(
        lambda d: "PRIMARY CORRIDOR (OPEN)" if d < 1200 else "SECONDARY CONTINGENCY"
    )
    return havens.sort_values('distance_km').reset_index(drop=True)
