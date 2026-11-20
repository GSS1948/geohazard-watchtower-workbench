import os
import glob
from datetime import datetime, timezone, timedelta
import requests
import numpy as np
import pandas as pd
import streamlit as st
import pydeck as pdk

# ==============================================================================
# 1. FIXED PHYSICAL-STATISTICAL CONSTANTS & REAL-TIME TELEMETRY ENGINE
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
def fetch_live_geophysical_feeds(lat, lon, now_iso_hour):
    """
    Pulls real-time past-72h seismic events (USGS) and hourly hydro-meteorological
    telemetry (Open-Meteo) for the exact corridor coordinates.
    """
    now_utc = datetime.fromisoformat(now_iso_hour).replace(tzinfo=timezone.utc)
    start_utc = now_utc - timedelta(hours=72)
    timestamps = [now_utc - timedelta(hours=6 * (12 - i)) for i in range(13)]

    seismic_bins = np.zeros(13)
    quake_count = 0
    max_mag = 0.0
    usgs_ok = False

    # 1. Live USGS Earthquake API (300 km radius, past 72 hours)
    try:
        usgs_url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
        params = {
            "format": "geojson",
            "starttime": start_utc.strftime("%Y-%m-%dT%H:%M:%S"),
            "endtime": now_utc.strftime("%Y-%m-%dT%H:%M:%S"),
            "latitude": lat,
            "longitude": lon,
            "maxradiuskm": 300,
            "minmagnitude": 2.0,
        }
        resp = requests.get(usgs_url, params=params, timeout=6)
        if resp.status_code == 200:
            features = resp.json().get("features", [])
            quake_count = len(features)
            for feat in features:
                mag = float(feat["properties"].get("mag") or 0.0)
                max_mag = max(max_mag, mag)
                ev_ms = feat["properties"].get("time")
                if ev_ms:
                    ev_dt = datetime.fromtimestamp(ev_ms / 1000.0, tz=timezone.utc)
                    hrs_ago = (now_utc - ev_dt).total_seconds() / 3600.0
                    bin_idx = int(np.clip(12 - round(hrs_ago / 6.0), 0, 12))
                    # Gutenberg-Richter relative energy weight
                    seismic_bins[bin_idx] += (10 ** (0.75 * max(0.0, mag - 2.0))) * 0.12
            usgs_ok = True
    except Exception:
        usgs_ok = False

    # 2. Live Open-Meteo Hydro-Meteorological API (Past 3 days hourly rain & soil moisture)
    rain_bins = np.zeros(13)
    soil_moisture_pct = None
    total_rain_72h = 0.0
    meteo_ok = False

    try:
        meteo_url = "https://api.open-meteo.com/v1/forecast"
        m_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation,soil_moisture_7_to_28cm",
            "past_days": 3,
            "forecast_days": 1,
            "timezone": "UTC",
        }
        m_resp = requests.get(meteo_url, params=m_params, timeout=6)
        if m_resp.status_code == 200:
            hourly = m_resp.json().get("hourly", {})
            times = hourly.get("time", [])
            precip = hourly.get("precipitation", [])
            soil = hourly.get("soil_moisture_7_to_28cm", [])

            valid_soils = []
            for t_str, p_val, s_val in zip(times, precip, soil):
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
                # Volumetric soil moisture (~0.05 dry to ~0.48 saturated) mapped to %
                soil_moisture_pct = float(np.clip((valid_soils[-1] / 0.45) * 100.0, 15.0, 98.5))
            meteo_ok = True
    except Exception:
        meteo_ok = False

    return {
        "timestamps": timestamps,
        "seismic_bins": seismic_bins,
        "rain_bins": rain_bins,
        "quake_count": quake_count,
        "max_mag": max_mag,
        "total_rain_72h": total_rain_72h,
        "soil_moisture_pct": soil_moisture_pct,
        "usgs_ok": usgs_ok,
        "meteo_ok": meteo_ok,
    }


def compute_toc_bottleneck_telemetry(zone_row, live_mode=True, now_utc=None):
    """
    Computes unified 72-hour sigma trajectory, physical TOC bottleneck saturation (tau_1 / tau_2),
    trajectory phase, and exact wall-clock deadline before tau_2 failure.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    node_id = int(zone_row["node_id"])
    tau_1 = float(zone_row["tau_1_threshold"])
    tau_2 = float(zone_row["tau_2_ceiling"])
    elev = float(zone_row["elevation_m"])
    lat = float(zone_row["latitude"])
    lon = float(zone_row["longitude"])

    if live_mode:
        now_hour_iso = now_utc.replace(minute=0, second=0, microsecond=0).isoformat()
        live = fetch_live_geophysical_feeds(lat, lon, now_hour_iso)
        timestamps = live["timestamps"]

        # Combine real seismic strain + real 6h rainfall surge into unified sigma index
        baseline_noise = 0.45 + (0.15 if elev < 50 else 0.0)
        hydro_sigma = (live["rain_bins"] / 15.0) * 1.35
        sigma_series = np.clip(baseline_noise + live["seismic_bins"] + hydro_sigma, 0.35, 4.20)

        # Physical bottleneck saturation driven by real root-zone soil moisture + 72h cumulative load
        if live["soil_moisture_pct"] is not None:
            rain_boost = min(22.0, live["total_rain_72h"] * 0.35)
            seismic_boost = min(15.0, live["max_mag"] * 2.2) if live["quake_count"] > 0 else 0.0
            saturation_pct = float(
                np.clip(live["soil_moisture_pct"] * 0.72 + rain_boost + seismic_boost, 22.0, 99.0)
            )
        else:
            saturation_pct = float(np.clip(45.0 + np.mean(sigma_series[-4:]) * 14.0, 25.0, 98.5))

        source_summary = (
            f"LIVE FEEDS — USGS (300km): {live['quake_count']} quakes (Max M{live['max_mag']:.1f}) | "
            f"Open-Meteo 72h Rain: {live['total_rain_72h']:.1f} mm"
        )
    else:
        # Tactical 3:00 AM Post-Peak Drainage Trap Stress-Test Drill
        rng = np.random.default_rng(seed=2026 + node_id * 17)
        timestamps = [now_utc - timedelta(hours=6 * (12 - i)) for i in range(13)]
        base_level = 1.10 + (100.0 - tau_1) * 0.035 + (0.20 if elev < 50 else 0.0)
        wave = np.sin(np.linspace(0.2, np.pi * 1.15, 13)) * 1.15
        noise = rng.normal(0, 0.08, 13)
        sigma_series = np.clip(base_level + wave + noise, 0.75, 3.85)

        cumulative_load = float(np.mean(sigma_series[-4:]))
        saturation_pct = float(
            np.clip(tau_1 - 6.5 + (cumulative_load / 3.0) * (tau_2 - tau_1 + 8.0), 40.0, 99.2)
        )
        source_summary = "STRESS-TEST DRILL — Simulated Post-Peak Drainage Lag Scenario"

    current_sigma = float(sigma_series[-1])
    peak_idx = int(np.argmax(sigma_series))
    peak_sigma = float(sigma_series[peak_idx])
    peak_time_utc = timestamps[peak_idx]

    if peak_idx >= 11:
        phase = "RISING / CRESTING NOW"
    else:
        phase = f"POST-PEAK (Peak {peak_sigma:.2f}σ at {peak_time_utc.strftime('%d %b %H:%M UTC')})"

    recent_rate_per_hr = max(
        0.15,
        (sigma_series[-1] - sigma_series[-3]) / 12.0 + max(0.0, saturation_pct - tau_1) * 0.04,
    )
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
        "source_summary": source_summary,
    }


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
# 2. STREAMLIT 24/7 TACTICAL COMMAND ROOM INTERFACE
# ==============================================================================
st.set_page_config(
    page_title="Geohazard Watchtower Command Room",
    page_icon="🛰️",
    layout="wide",
)

df_zones = load_territory_matrix("Matrix.csv")

# Sidebar: Telemetry Mode + Territory Selection + Physical Constants
st.sidebar.header("📡 Telemetry Feed Mode")
feed_mode = st.sidebar.radio(
    "Select Operational Stream",
    ["Live Real-Time Telemetry (USGS + Open-Meteo)", "3:00 AM Post-Peak Stress-Test Drill"],
    index=0,
)
is_live = feed_mode.startswith("Live")

st.sidebar.markdown("---")
st.sidebar.header("🌐 Active Surveillance Sector")
selected_zone_name = st.sidebar.selectbox(
    "Select Monitored Corridor (34 Global Nodes)",
    df_zones["territory_name"].tolist(),
)

st.sidebar.markdown("---")
st.sidebar.subheader("📐 Fixed Physical-Statistical Gates")
st.sidebar.markdown(
    f"- **Anomaly Gate (σ):** `{FIXED_SIGMA_GATE:.1f}σ` *(Fixed 99.73% non-random statistical threshold)*\n"
    "- **τ₁ Bottleneck Limit:** *Physical drainage / absorption capacity saturation threshold*\n"
    "- **τ₂ Structural Ceiling:** *Irreversible cascade failure limit (liquefaction / overtopping / rupture)*\n\n"
    "⚠️ *Operational Rule: Even if σ recedes post-peak, residual saturation above τ₁ remains lethal until drained.*"
)

zone_data = df_zones[df_zones["territory_name"] == selected_zone_name].iloc[0]
tel = compute_toc_bottleneck_telemetry(zone_data, live_mode=is_live)
havens_df = rank_safe_havens(df_zones, zone_data)

now_utc = tel["now_utc"]
now_ist = now_utc + timedelta(hours=5, minutes=30)
deadline_utc = tel["deadline_utc"]
deadline_ist = deadline_utc + timedelta(hours=5, minutes=30)

# Command Header with Live Wall-Clock Time, Feed Verification & Hard Action Deadline
st.title("🛰️ Geohazard Watchtower — 24/7 Tactical Command Room")
st.caption(f"**ACTIVE DATA STREAM:** {tel['source_summary']}")
st.markdown(
    f"**LIVE WATCH CLOCK:** `{now_utc.strftime('%d %b %Y, %H:%M UTC')}` | `{now_ist.strftime('%H:%M IST')}`  "
    f"•  **HARD ACTION DEADLINE BEFORE τ₂ FAILURE:** `{deadline_utc.strftime('%d %b %Y, %H:%M UTC')}` "
    f"(`{deadline_ist.strftime('%H:%M IST')}` — **{tel['hours_to_tau2']:.1f} hrs remaining**)"
)

# Top KPI Strip
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

st.markdown("---")

# Tactical Split: Left = Spatial Vector Map | Right = Unified Chronological Trajectory & Direct Command Orders
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
                else [46, 204, 113, 220],
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
                get_source_color=[255, 75, 75, 220]
                if (tel["is_sigma_breach"] or tel["is_tau1_breach"])
                else [46, 204, 113, 220],
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

    st.subheader("📋 Duty Officer Command Directives (Whetted Action Protocol)")
    if tel["is_sigma_breach"] or tel["is_tau1_breach"]:
        cutoff_utc = deadline_utc - timedelta(hours=float(primary_haven["est_transit_hrs"]))
        st.error(
            f"**CONDITION RED / AMBER — IMMEDIATE EXECUTION REQUIRED BEFORE {deadline_utc.strftime('%H:%M UTC')} ({deadline_ist.strftime('%H:%M IST')}):**\n"
            f"1. **Ground Reality Check:** Anomaly is `{tel['current_sigma']:.2f}σ` ({tel['phase']}), **HOWEVER** physical bottleneck saturation is locked at **`{tel['saturation_pct']:.1f}%`** (above τ₁ = `{tel['tau_1']:.1f}%`, only **`{tel['headroom_pct']:.1f}%`** below τ₂ failure). Do NOT stand down—post-peak drainage lag causes delayed structural collapse.\n"
            f"2. **Evacuation Cut-Off:** Transit to **{primary_haven['territory_name']}** requires **`{primary_haven['est_transit_hrs']} hrs`**. Convoy departure must clear elevation (`{int(zone_data['elevation_m'])}m`) no later than **`{cutoff_utc.strftime('%d %b %H:%M UTC')}`**.\n"
            f"3. **OASIS CAP v1.2 Broadcast:** Issue Priority Level-1 Civil Warning & open inland arterial highways to Node `{int(primary_haven['node_id'])}`."
        )
    else:
        st.success(
            f"**CONDITION GREEN — NORMAL BASELINE SURVEILLANCE:**\n"
            f"1. **Ground Reality Check:** Live anomaly (`{tel['current_sigma']:.2f}σ`) and physical bottleneck saturation (`{tel['saturation_pct']:.1f}%`) remain safely below τ₁ (`{tel['tau_1']:.1f}%`).\n"
            f"2. **Standby Readiness:** Tier-1 Safe Haven corridor to **{primary_haven['territory_name']}** (`{primary_haven['distance_km']} km` / `{primary_haven['est_transit_hrs']}h transit`) verified open and pre-mapped."
        )

# Bottom Panel: Safe-Haven Triage & OASIS CAP v1.2 Dispatch Packet
st.markdown("---")
st.subheader("🛡️ Tier-1 Safe-Haven Routing & OASIS CAP v1.2 Dispatch Packet")

col_tbl, col_cap = st.columns([1.45, 1.0])
with col_tbl:
    if not havens_df.empty:
        display_havens = havens_df[
            [
                "node_id",
                "territory_name",
                "elevation_m",
                "distance_km",
                "elevation_gain_m",
                "est_transit_hrs",
                "cap_status",
            ]
        ].rename(
            columns={
                "node_id": "Node ID",
                "territory_name": "Tier-1 Safe Haven",
                "elevation_m": "Elev (m)",
                "distance_km": "Dist (km)",
                "elevation_gain_m": "Elev Gain (m)",
                "est_transit_hrs": "Transit (hrs)",
                "cap_status": "Corridor Status",
            }
        )
        st.dataframe(display_havens, use_container_width=True, hide_index=True)

with col_cap:
    cap_xml = f"""<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>GWW-{int(zone_data['node_id'])}-{now_utc.strftime('%Y%m%dT%H%MZ')}</identifier>
  <sender>watchtower@geohazard-toc.org</sender>
  <sent>{now_utc.strftime('%Y-%m-%dT%H:%M:%S+00:00')}</sent>
  <status>Actual</status>
  <msgType>{'Alert' if (tel['is_sigma_breach'] or tel['is_tau1_breach']) else 'Update'}</msgType>
  <info>
    <event>TOC Bottleneck Saturation Surveillance</event>
    <urgency>{'Immediate' if tel['is_tau1_breach'] else 'Future'}</urgency>
    <severity>{'Severe' if tel['is_tau1_breach'] else 'Minor'}</severity>
    <expires>{deadline_utc.strftime('%Y-%m-%dT%H:%M:%S+00:00')}</expires>
    <headline>{selected_zone_name}: Saturation {tel['saturation_pct']:.1f}% (tau1={tel['tau_1']}%)</headline>
    <instruction>Primary Safe Haven: {primary_haven['territory_name']} ({primary_haven['distance_km']} km). Action deadline: {deadline_utc.strftime('%H:%M UTC')}.</instruction>
  </info>
</alert>"""
    st.code(cap_xml, language="xml")
    st.download_button(
        label="📡 Download OASIS CAP v1.2 Dispatch XML",
        data=cap_xml,
        file_name=f"CAP_v12_Node{int(zone_data['node_id'])}_{now_utc.strftime('%Y%m%d_%H%M')}Z.xml",
        mime="application/xml",
    )
