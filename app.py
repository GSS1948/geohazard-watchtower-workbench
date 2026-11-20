from datetime import timedelta
import numpy as np
import pandas as pd
import streamlit as st
import pydeck as pdk
import engine

st.set_page_config(
    page_title="Geohazard Watchtower Command Room",
    page_icon="🛰️",
    layout="wide",
)

df_zones = engine.load_territory_matrix("Matrix.csv")

st.sidebar.header("📡 Telemetry Feed Mode")
feed_mode = st.sidebar.radio(
    "Select Operational Stream",
    ["Live Real-Time Telemetry (USGS & Meteo)", "3:00 AM Post-Peak Stress-Test Drill"],
    index=0,
)
is_live = feed_mode.startswith("Live")

with st.spinner("Executing planetary 34-node sweep..."):
    telemetry_map, triage_df = engine.evaluate_all_corridors(df_zones, live_mode=is_live)

ranked_corridors = triage_df["Corridor"].tolist()

st.sidebar.markdown("---")
st.sidebar.header("🌐 Active Surveillance Sector")
selected_zone_name = st.sidebar.selectbox(
    "Select Monitored Corridor (Ranked by Severity)",
    ranked_corridors,
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.subheader("📐 Fixed Physical-Statistical Gates")
st.sidebar.markdown(
    f"- **Anomaly Gate (σ):** `{engine.FIXED_SIGMA_GATE:.1f}σ` *(Fixed 99.73% non-random threshold)*\n"
    "- **τ₁ Limit:** *Physical drainage saturation threshold*\n"
    "- **τ₂ Ceiling:** *Irreversible cascade failure limit*"
)

zone_data = df_zones[df_zones["territory_name"] == selected_zone_name].iloc[0]
tel = telemetry_map[selected_zone_name]
havens_df = engine.rank_safe_havens(df_zones, zone_data)

now_utc = tel["now_utc"]
now_ist = now_utc + timedelta(hours=5, minutes=30)
deadline_utc = tel["deadline_utc"]
deadline_ist = deadline_utc + timedelta(hours=5, minutes=30)

st.title("🛰️ Geohazard Watchtower — 24/7 Tactical Command Room")

red_count = int((triage_df["Status"].str.contains("RED")).sum())
orange_count = int((triage_df["Status"].str.contains("ORANGE")).sum())
yellow_count = int((triage_df["Status"].str.contains("YELLOW")).sum())
green_count = int((triage_df["Status"].str.contains("GREEN")).sum())

st.markdown(
    f"**LIVE WATCH CLOCK:** `{now_utc.strftime('%d %b %Y, %H:%M UTC')}` | `{now_ist.strftime('%H:%M IST')}`  "
    f"•  **GLOBAL SWEEP:** `🔴 {red_count} RED` | `🟠 {orange_count} ORANGE` | `🟡 {yellow_count} YELLOW` | `🟢 {green_count} GREEN`"
)

with st.expander(
    f"🌍 Planetary 34-Node Live Triage Board (Auto-Sorted — Top Active Hot-Spot: {ranked_corridors[0]})",
    expanded=True,
):
    def highlight_status(row):
        status = str(row["Status"])
        if "RED" in status:
            return ["background-color: rgba(255, 75, 75, 0.25); color: #ff4b4b"] * len(row)
        elif "ORANGE" in status:
            return ["background-color: rgba(255, 140, 0, 0.25); color: #ffa500"] * len(row)
        elif "YELLOW" in status:
            return ["background-color: rgba(255, 215, 0, 0.20); color: #ffd700"] * len(row)
        else:
            return ["background-color: rgba(46, 204, 113, 0.15); color: #2ecc71"] * len(row)

    display_df = triage_df.drop(columns=["_score"])
    styled_triage_df = display_df.style.apply(highlight_status, axis=1).format(
        {col: "{:.1f}" for col in display_df.select_dtypes(include=["float", "float64"]).columns}
    )
    st.dataframe(
        styled_triage_df,
        use_container_width=True,
        hide_index=True,
        height=210,
    )

st.markdown("---")
st.subheader(f"🎯 Sector Deep-Dive: {selected_zone_name} [{tel['alert_tier']}]")
st.caption(f"**ACTIVE DATA STREAM:** {tel['source_summary']}")

k1, k2, k3, k4 = st.columns(4)
k1.metric(
    f"Current Anomaly (Gate: {engine.FIXED_SIGMA_GATE:.1f}σ)",
    f"{tel['current_sigma']:.1f}σ",
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
    active_color = (
        [255, 50, 50, 230]
        if "RED" in tel["alert_tier"]
        else (
            [255, 140, 0, 220]
            if "ORANGE" in tel["alert_tier"]
            else ([255, 215, 0, 220] if "YELLOW" in tel["alert_tier"] else [46, 204, 113, 220])
        )
    )

    active_point = pd.DataFrame(
        [
            {
                "name": f"{selected_zone_name} ({tel['current_sigma']:.1f}σ | Load {tel['saturation_pct']:.1f}%)",
                "lat": float(zone_data["latitude"]),
                "lon": float(zone_data["longitude"]),
                "color": active_color,
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
                get_source_color=active_color,
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
            "Fixed 3.0σ Gate": [engine.FIXED_SIGMA_GATE] * len(tel["timestamps"]),
        }
    ).set_index("UTC_Time")
    st.line_chart(chart_df)

    st.subheader("📋 Duty Officer Command Directives")
    if "RED" in tel["alert_tier"] or "ORANGE" in tel["alert_tier"]:
        cutoff_utc = deadline_utc - timedelta(hours=float(primary_haven["est_transit_hrs"]))
        st.error(
            f"**{tel['alert_tier']} — ACTION REQUIRED BEFORE {deadline_utc.strftime('%H:%M UTC')} ({deadline_ist.strftime('%H:%M IST')}):**\n"
            f"1. **Meteo Drivers:** Rain (72h): `{tel['total_rain_72h']:.1f} mm` | Max Gust: `{tel['max_gust_kmh']:.1f} km/h` | Pressure: `{tel['min_pressure_hpa']:.1f} hPa`\n"
            f"2. **Bottleneck Status:** Anomaly `{tel['current_sigma']:.1f}σ`, Saturation: **`{tel['saturation_pct']:.1f}%`** (τ₁ Limit: `{tel['tau_1']:.1f}%`).\n"
            f"3. **Evacuation Cut-Off:** Convoy to **{primary_haven['territory_name']}** (`{primary_haven['est_transit_hrs']}h`) must clear elevation no later than **`{cutoff_utc.strftime('%d %b %H:%M UTC')}`**."
        )
    elif "YELLOW" in tel["alert_tier"]:
        st.warning(
            f"**YELLOW / WATCH — PRE-POSITIONING REQUIRED:**\n"
            f"1. **Meteo Drivers:** Rain (72h): `{tel['total_rain_72h']:.1f} mm` | Max Gust: `{tel['max_gust_kmh']:.1f} km/h`\n"
            f"2. **Status:** Sector approaching critical thresholds (`{tel['current_sigma']:.1f}σ`, saturation `{tel['saturation_pct']:.1f}%`).\n"
            f"3. **Action:** Place route to **{primary_haven['territory_name']}** on 1-hour standby notice."
        )
    else:
        st.success(
            f"**GREEN / NORMAL — BASELINE SURVEILLANCE:**\n"
            f"1. **Meteo Drivers:** Rain (72h): `{tel['total_rain_72h']:.1f} mm` | Max Gust: `{tel['max_gust_kmh']:.1f} km/h` | Pressure: `{tel['min_pressure_hpa']:.1f} hPa`\n"
            f"2. **Status:** Anomaly (`{tel['current_sigma']:.1f}σ`) and saturation (`{tel['saturation_pct']:.1f}%`) are stable below τ₁.\n"
            f"3. **Readiness:** Safe Haven corridor to **{primary_haven['territory_name']}** pre-mapped."
        )
