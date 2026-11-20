import os
import glob
from datetime import datetime, timezone, timedelta
import requests
import numpy as np
import pandas as pd
import streamlit as st
import pydeck as pdk

# ==============================================================================
# 1. STREAMLIT CONFIG & PAGE INITIALIZATION (MUST BE FIRST)
# ==============================================================================
st.set_page_config(
    page_title="Geohazard Watchtower Command Room",
    page_icon="🛰️",
    layout="wide",
)

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
    """Fetches global earthquakes over the past 72h."""
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
    """Sweeps all 34 corridors with robust fallback."""
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
        elif is_sigma_breach or is_tau1_breach:
            alert_tier = "RED / BREACH"
            severity_score = 100.0 + (saturation_pct - tau_1) + peak_sigma * 5.0
        elif peak_sigma >= 1.8 or (tau_1 - saturation_pct) <= 10.0:
            alert_tier = "AMBER / WATCH"
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
    """Identifies and ranks contagion-free Tier-1 Safe Havens with transit feasibility."""
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


# ==============================================================================
# 2. STREAMLIT UI & COMMAND ROOM LAYOUT
# ==============================================================================
df_zones = load_territory_matrix("Matrix.csv")

st.sidebar.header("📡 Telemetry Feed Mode")
feed_mode = st.sidebar.radio(
    "Select Operational Stream",
    ["Live Real-Time Telemetry (USGS Seismic)", "3:00 AM Post-Peak Stress-Test Drill"],
    index=0,
)
is_live = feed_mode.startswith("Live")

with st.spinner("Scanning 34 planetary nodes..."):
    telemetry_map, triage_df = evaluate_all_corridors(df_zones, live_mode=is_live)

ranked_corridors = triage_df["Corridor"].tolist()

st.sidebar.markdown("---")
st.sidebar.header("🌐 Active Surveillance Sector")
st.sidebar.caption("Sorted automatically by highest live risk:")
selected_zone_name = st.sidebar.selectbox(
    "Select Monitored Corridor (Ranked by Severity)",
    ranked_corridors,
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.subheader("📐 Fixed Physical-Statistical Gates")
st.sidebar.markdown(
    f"- **Anomaly Gate (σ):** `{FIXED_SIGMA_GATE:.1f}σ` *(Fixed 99.73% non-random statistical threshold)*\n"
    "- **τ₁ Bottleneck Limit:** *Physical drainage / absorption capacity saturation threshold*\n"
    "- **τ₂ Structural Ceiling:** *Irreversible cascade failure limit (liquefaction / overtopping / rupture)*"
)

zone_data = df_zones[df_zones["territory_name"] == selected_zone_name].iloc[0]
tel = telemetry_map[selected_zone_name]
havens_df = rank_safe_havens(df_zones, zone_data)

now_utc = tel["now_utc"]
now_ist = now_utc + timedelta(hours=5, minutes=30)
deadline_utc = tel["deadline_utc"]
deadline_ist = deadline_utc + timedelta(hours=5, minutes=30)

st.title("🛰️ Geohazard Watchtower — 24/7 Tactical Command Room")

red_count = int((triage_df["Status"] == "RED / BREACH").sum())
amber_count = int((triage_df["Status"] == "AMBER / WATCH").sum())
green_count = int((triage_df["Status"] == "GREEN / NORMAL").sum())

st.markdown(
    f"**LIVE WATCH CLOCK:** `{now_utc.strftime('%d %b %Y, %H:%M UTC')}` | `{now_ist.strftime('%H:%M IST')}`  "
    f"•  **GLOBAL PLANETARY SWEEP:** `🔴 {red_count} RED` | `🟠 {amber_count} AMBER` | `🟢 {green_count} GREEN`"
)

with st.expander(
    f"🌍 Planetary 34-Node Live Triage Board (Auto-Sorted — Top Active Hot-Spot: {ranked_corridors[0]})",
    expanded=True,
):
    st.dataframe(
        triage_df.drop(columns=["_score"]),
        use_container_width=True,
        hide_index=True,
        height=210,
    )

st.markdown("---")
st.subheader(f"🎯 Sector Deep-Dive: {selected_zone_name} [{tel['alert_tier']}]")
st.caption(f"**ACTIVE DATA STREAM:** {tel['source_summary']}")

k1, k2, k3, k4 = st.columns(4)
k1.metric(
    f"Current Anomaly (Gate: {FIXED_SIGMA_GATE:.1f}σ)",
    f"{tel['current_sigma']:.2f}σ",
    delta=tel["phase"],
    delta_color="inverse" if tel["is_sigma_breach"] else "off",
)
k2.metric(
    "TOC Bottleneck Saturation",
    f"{tel['saturation_pct']:.1f}%",
    delta=f"τ₁ Limit: {tel['tau_1']:.1f}% ({'BREACHED' if tel['is_tau1_breach'] else 'Below'})",
    delta_color="inverse" if tel["is_tau1_breach"] else "normal",
)
k3.metric(
    "Headroom to τ₂ Failure Ceiling",
    f"{tel['headroom_pct']:.1f}%",
    delta=f"τ₂ Ceiling: {tel['tau_2']:.1f}% | Elev: {int(zone_data['elevation_m'])}m",
    delta_color="inverse" if tel["headroom_pct"] < 8.0 else "off",
)
primary_haven = havens_df.iloc[0] if not havens_df.empty else None
k4.metric(
    "Assigned Tier-1 Safe Haven",
    primary_haven["territory_name"].replace("Tier-1 Safe Haven: ", "")
    if primary_haven is not None
    else "N/A",
    delta=f"{primary_haven['distance_km']} km ({primary_haven['est_transit_hrs']}h transit)"
    if primary_haven is not None
    else "",
    delta_color="off",
)

col_map, col_cmd = st.columns([1.3, 1.1])

with col_map:
    st.subheader(f"Spatial Contagion & Evacuation Vector: {selected_zone_name}")
    active_point = pd.DataFrame(
        [
            {
                "name": f"{selected_zone_name} ({tel['current_sigma']:.2f}σ | Load {tel['saturation_pct']:.1f}%)",
                "lat": float(zone_data["latitude"]),
                "lon": float(zone_data["longitude"]),
                "color": [255, 50, 50, 230]
                if (tel["is_sigma_breach"] or tel["is_tau1_breach"])
                else ([255, 165, 0, 220] if tel["alert_tier"] == "AMBER / WATCH" else [46, 204, 113, 220]),
                "radius": 48000,
            }
        ]
    )
    safe_points = pd.DataFrame(
        [
            {
                "name": f"{r['territory_name']} ({r['distance_km']} km | +{r['elevation_gain_m']}m)",
                "lat": float(r["latitude"]),
                "lon": float(r["longitude"]),
                "color": [0, 212, 255, 220],
                "radius": 38000,
            }
            for _, r in havens_df.iterrows()
        ]
    )
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=pd.concat([active_point, safe_points], ignore_index=True),
            get_position=["lon", "lat"],
            get_fill_color="color",
            get_radius="radius",
            pickable=True,
        )
    ]
    if primary_haven is not None:
        arc_data = pd.DataFrame(
            [
                {
                    "source_lon": float(zone_data["longitude"]),
                    "source_lat": float(zone_data["latitude"]),
                    "target_lon": float(primary_haven["longitude"]),
                    "target_lat": float(primary_haven["latitude"]),
                }
            ]
        )
        layers.append(
            pdk.Layer(
                "ArcLayer",
                data=arc_data,
                get_source_position=["source_lon", "source_lat"],
                get_target_position=["target_lon", "target_lat"],
                get_source_color=[255, 75, 75, 220],
                get_target_color=[0, 212, 255, 220],
                get_width=5,
            )
        )
    st.pydeck_chart(
        pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
            initial_view_state=pdk.ViewState(
                latitude=float(zone_data["latitude"]),
                longitude=float(zone_data["longitude"]),
                zoom=4.2,
                pitch=25,
            ),
            layers=layers,
            tooltip={"text": "{name}"},
        )
    )

with col_cmd:
    st.subheader("72-Hour Unified Anomaly Trajectory (Chronological UTC)")
    chart_df = pd.DataFrame(
        {
            "UTC_Time": [ts.strftime("%m-%d %H:%M") for ts in tel["timestamps"]],
            "Observed Anomaly (σ)": tel["sigma_series"],
            "Fixed 3.0σ Gate": [FIXED_SIGMA_GATE] * len(tel["timestamps"]),
        }
    ).set_index("UTC_Time")
    st.line_chart(chart_df)

    st.subheader("📋 Duty Officer Command Directives")
    if tel["is_sigma_breach"] or tel["is_tau1_breach"]:
        cutoff_utc = deadline_utc - timedelta(hours=float(primary_haven["est_transit_hrs"]))
        st.error(
            f"**CONDITION RED / AMBER — ACTION REQUIRED BEFORE {deadline_utc.strftime('%H:%M UTC')} ({deadline_ist.strftime('%H:%M IST')}):**\n"
            f"1. **Bottleneck Load:** Saturation is at **`{tel['saturation_pct']:.1f}%`** (above τ₁ = `{tel['tau_1']:.1f}%`).\n"
            f"2. **Evacuation Cut-Off:** Convoy to **{primary_haven['territory_name']}** (`{primary_haven['est_transit_hrs']}h`) must clear elevation no later than **`{cutoff_utc.strftime('%d %b %H:%M UTC')}`**."
        )
    else:
        st.success(
            f"**CONDITION GREEN — BASELINE SURVEILLANCE:**\n"
            f"1. **Status:** Anomaly (`{tel['current_sigma']:.2f}σ`) and saturation (`{tel['saturation_pct']:.1f}%`) are below τ₁ (`{tel['tau_1']:.1f}%`).\n"
            f"2. **Readiness:** Safe Haven corridor to **{primary_haven['territory_name']}** (`{primary_haven['distance_km']} km`) pre-mapped."
        )
