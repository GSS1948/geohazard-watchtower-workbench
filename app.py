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
havens_df = engine.rank_safe_havens(df_zones, zone_data, telemetry_map=telemetry_map)

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
    def highlight_vivid_contrast(row):
        status = str(row["Status"])
        if "RED" in status:
            return ["background-color: #D32F2F; color: #FFFFFF; font-weight: 700"] * len(row)
        elif "ORANGE" in status:
            return ["background-color: #EF6C00; color: #FFFFFF; font-weight: 700"] * len(row)
        elif "YELLOW" in status:
            return ["background-color: #FFD600; color: #000000; font-weight: 700"] * len(row)
        else:
            return ["background-color: #2E7D32; color: #FFFFFF; font-weight: 600"] * len(row)

    display_df = triage_df.drop(columns=["_score"])
    styled_triage_df = display_df.style.apply(highlight_vivid_contrast, axis=1).format(
        {col: "{:.1f}" for col in display_df.select_dtypes(include=["float", "float64"]).columns}
    )
    st.dataframe(
        styled_triage_df,
        use_container_width=True,
        hide_index=True,
        height=240,
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
    "Nearest Tactical Safe Haven",
    primary_haven["territory_name"].replace("Tactical Haven: ", "").replace("Tier-1 Safe Haven: ", "")
    if primary_haven is not None
    else "N/A",
    delta=f"{primary_haven['distance_km']} km ({primary_haven['est_transit_hrs']}h transit)"
    if primary_haven is not None
    else "",
    delta_color="off",
)

col_map, col_cmd = st.columns([1.3, 1.1])

with col_map:
    st.subheader(f"Spatial Contagion & Safe Haven Stars (★): {selected_zone_name}")
    active_color = (
        [211, 47, 47, 245]
        if "RED" in tel["alert_tier"]
        else (
            [239, 108, 0, 245]
            if "ORANGE" in tel["alert_tier"]
            else ([255, 214, 0, 245] if "YELLOW" in tel["alert_tier"] else [46, 125, 50, 245])
        )
    )

    active_point = pd.DataFrame(
        [
            {
                "name": f"DISASTER CENTER: {selected_zone_name} ({tel['current_sigma']:.1f}σ | Saturation {tel['saturation_pct']:.1f}%)",
                "lat": float(zone_data["latitude"]),
                "lon": float(zone_data["longitude"]),
                "color": active_color,
                "radius": 24000,
            }
        ]
    )
    safe_points = pd.DataFrame(
        [
            {
                "name": f"★ SAFE HAVEN: {r['territory_name']} | {r['distance_km']} km | +{r['elevation_gain_m']}m elev",
                "lat": float(r["latitude"]),
                "lon": float(r["longitude"]),
                "color": [16, 185, 129, 235],
                "radius": 18000,
                "star": "★",
            }
            for _, r in havens_df.iterrows()
        ]
    )
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=pd.concat([active_point, safe_points.drop(columns=["star"])], ignore_index=True),
            get_position=["lon", "lat"],
            get_fill_color="color",
            get_radius="radius",
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            data=safe_points,
            get_position=["lon", "lat"],
            get_text="star",
            get_size=26,
            get_color=[255, 255, 255, 255],
            get_alignment_baseline="'center'",
            get_text_anchor="'middle'",
            pickable=True,
        ),
    ]
    top_havens = havens_df.head(3)
    if not top_havens.empty:
        arc_data = pd.DataFrame(
            [
                {
                    "source_lon": float(zone_data["longitude"]),
                    "source_lat": float(zone_data["latitude"]),
                    "target_lon": float(r["longitude"]),
                    "target_lat": float(r["latitude"]),
                }
                for _, r in top_havens.iterrows()
            ]
        )
        layers.append(
            pdk.Layer(
                "ArcLayer",
                data=arc_data,
                get_source_position=["source_lon", "source_lat"],
                get_target_position=["target_lon", "target_lat"],
                get_source_color=active_color,
                get_target_color=[255, 255, 255, 240],
                get_width=4,
            )
        )
    st.pydeck_chart(
        pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
            initial_view_state=pdk.ViewState(
                latitude=float(zone_data["latitude"]),
                longitude=float(zone_data["longitude"]),
                zoom=6.2,
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

    st.subheader("📋 Duty Officer Command Directives & SITREP")
    gmaps_url = (
        f"https://www.google.com/maps/dir/?api=1&origin={zone_data['latitude']},{zone_data['longitude']}"
        f"&destination={primary_haven['latitude']},{primary_haven['longitude']}"
        if primary_haven is not None
        else "#"
    )
    
    if "RED" in tel["alert_tier"] or "ORANGE" in tel["alert_tier"]:
        cutoff_utc = deadline_utc - timedelta(hours=float(primary_haven["est_transit_hrs"]))
        st.error(
            f"**{tel['alert_tier']} — ACTION REQUIRED BEFORE {deadline_utc.strftime('%H:%M UTC')} ({deadline_ist.strftime('%H:%M IST')}):**\n"
            f"1. **Meteo Drivers:** Rain (72h): `{tel['total_rain_72h']:.1f} mm` | Max Gust: `{tel['max_gust_kmh']:.1f} km/h` | Pressure: `{tel['min_pressure_hpa']:.1f} hPa`\n"
            f"2. **Bottleneck Status:** Anomaly `{tel['current_sigma']:.1f}σ`, Saturation: **`{tel['saturation_pct']:.1f}%`** (τ₁ Limit: `{tel['tau_1']:.1f}%`).\n"
            f"3. **Immediate Tactical Evacuation:** Move to **{primary_haven['territory_name']}** (`{primary_haven['distance_km']} km` / `{primary_haven['est_transit_hrs']}h`) — [Open Google Maps Route]({gmaps_url})."
        )
    elif "YELLOW" in tel["alert_tier"]:
        st.warning(
            f"**YELLOW / WATCH — PRE-POSITIONING REQUIRED:**\n"
            f"1. **Meteo Drivers:** Rain (72h): `{tel['total_rain_72h']:.1f} mm` | Max Gust: `{tel['max_gust_kmh']:.1f} km/h`\n"
            f"2. **Status:** Sector approaching critical thresholds (`{tel['current_sigma']:.1f}σ`, saturation `{tel['saturation_pct']:.1f}%`).\n"
            f"3. **Action:** Place route to **{primary_haven['territory_name']}** (`{primary_haven['distance_km']} km`) on 1-hour standby — [Open Google Maps Route]({gmaps_url})."
        )
    else:
        st.success(
            f"**GREEN / NORMAL — BASELINE SURVEILLANCE:**\n"
            f"1. **Meteo Drivers:** Rain (72h): `{tel['total_rain_72h']:.1f} mm` | Max Gust: `{tel['max_gust_kmh']:.1f} km/h` | Pressure: `{tel['min_pressure_hpa']:.1f} hPa`\n"
            f"2. **Status:** Anomaly (`{tel['current_sigma']:.1f}σ`) and saturation (`{tel['saturation_pct']:.1f}%`) are stable below τ₁.\n"
            f"3. **Readiness:** Tactical corridor to **{primary_haven['territory_name']}** (`{primary_haven['distance_km']} km`) pre-mapped — [Open Google Maps Route]({gmaps_url})."
        )

    with st.expander("📝 Live Ground SITREP & Scenario Analysis", expanded=True):
        st.markdown(
            f"#### 1. Telemetry Breakdown for {selected_zone_name}\n"
            f"- **Meteo Drivers:** Over the past 72 hours, cumulative rainfall is at **{tel['total_rain_72h']:.1f} mm**, max wind gusts are gentle at **{tel['max_gust_kmh']:.1f} km/h**, and barometric pressure is stable at **{tel['min_pressure_hpa']:.1f} hPa**.\n"
            f"- **Bottleneck Status:** Basin drainage saturation is pinned at **{tel['saturation_pct']:.1f}%**, breaching the $\\tau_1$ drainage limit of **{tel['tau_1']:.1f}%**.\n"
            f"- **Anomaly Phase:** Current anomaly is registering at **{tel['current_sigma']:.1f}σ** ({tel['phase']}).\n\n"
            f"#### 2. Likely Situation & Scenario on the Ground\n"
            f"- **Basin Waterlogging & Standing Water:** With no active cyclone core or gale-force winds overhead, the reality on the ground is severe, persistent regional waterlogging and drainage backup. Held inside a low-lying basin at **{int(zone_data['elevation_m'])}m** elevation, agricultural fields and canals are operating at near-maximum volumetric capacity.\n"
            f"- **Operational Relief & Lag:** Because wind gusts are minimal and the anomaly has cooled from its peak, the acute structural threat of storm-surge destruction has passed. Authorities are managing post-peak drainage lag, saturated embankments, and local mobility constraints.\n"
            f"- **Evacuation Runway:** Local convoys toward nearby tactical upland tiles (such as **{primary_haven['territory_name']}**, `{primary_haven['distance_km']} km` away) maintain a clear operational window."
        )

st.markdown("---")
st.subheader("⭐ Practical Safe Haven Proximity & Google Maps Evacuation Matrix")
st.caption("Immediate tactical safe tiles (110–220 km) ranked first for civil administration, followed by strategic reserves.")
if not havens_df.empty:
    haven_display = havens_df[
        ["territory_name", "haven_tier", "distance_km", "elevation_gain_m", "est_transit_hrs", "latitude", "longitude"]
    ].copy()
    haven_display["Google Maps Route"] = haven_display.apply(
        lambda r: f"https://www.google.com/maps/dir/?api=1&origin={zone_data['latitude']},{zone_data['longitude']}&destination={r['latitude']},{r['longitude']}",
        axis=1,
    )
    haven_display = haven_display[
        ["territory_name", "haven_tier", "distance_km", "elevation_gain_m", "est_transit_hrs", "Google Maps Route"]
    ]
    haven_display.columns = [
        "Safe Haven Corridor",
        "Operational Tier",
        "Distance (km)",
        "Elevation Gain (m)",
        "Transit (hrs)",
        "Google Maps Route",
    ]
    st.dataframe(
        haven_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Google Maps Route": st.column_config.LinkColumn("Google Maps Route", display_text="🗺️ Open Route")
        },
    )
else:
    st.info("No safe havens registered in matrix.")
