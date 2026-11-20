import streamlit as st
import pandas as pd
import pydeck as pdk
from engine import (
    load_territory_matrix,
    compute_toc_bottleneck_sigma,
    rank_safe_havens,
)

st.set_page_config(
    page_title="Geohazard Watchtower War Room",
    page_icon="🛰️",
    layout="wide",
)

# Load complete 34-corridor spatial matrix
df_zones = load_territory_matrix("Matrix.csv")

# Sidebar Controls
st.sidebar.header("Macro-Region Selection")
selected_zone_name = st.sidebar.selectbox(
    "Select Global Zone (34 Corridors)",
    df_zones["territory_name"].tolist(),
)
threshold_sigma = st.sidebar.slider(
    "Anomaly Security Threshold (σ)",
    min_value=1.0,
    max_value=4.0,
    value=3.0,
    step=0.1,
)
st.sidebar.markdown("---")
st.sidebar.info(
    "**Operational Protocol:**\n"
    "- **τ₁ Threshold:** Early bottleneck saturation warning\n"
    "- **τ₂ Ceiling:** Structural cascade failure limit\n"
    "- **72h Window:** Pre-impact evacuation & CAP v1.2 dispatch"
)

# Extract selected territory parameters
zone_data = df_zones[df_zones["territory_name"] == selected_zone_name].iloc[0]
current_sigma, saturation_pct, mse_curve, is_breach = compute_toc_bottleneck_sigma(
    zone_data, threshold_sigma
)
havens_df = rank_safe_havens(df_zones, zone_data)

# Header
st.title("🛰️ Geohazard Watchtower War Room")
st.markdown(
    "**Theory of Constraints (TOC) Multi-Physics Telemetry & 72-Hour Safe-Haven Triage System**"
)

# Top KPI Strip (4 Inclusive Operational Metrics)
k1, k2, k3, k4 = st.columns(4)
k1.metric(
    "Peak Anomaly Gate (σ)",
    f"{current_sigma:.2f}σ",
    delta="BREACH ALERT" if is_breach else "Within Gate",
    delta_color="inverse" if is_breach else "normal",
)
k2.metric(
    "TOC Bottleneck Saturation",
    f"{saturation_pct:.1f}%",
    delta=f"τ₁ Warning: {zone_data['tau_1_threshold']}%",
    delta_color="off",
)
k3.metric(
    "Structural Ceiling (τ₂)",
    f"{zone_data['tau_2_ceiling']}%",
    delta=f"Elevation: {int(zone_data['elevation_m'])} m",
    delta_color="off",
)
nearest_haven = havens_df.iloc[0]["territory_name"].replace("Tier-1 Safe Haven: ", "") if not havens_df.empty else "N/A"
nearest_dist = f"{havens_df.iloc[0]['distance_km']} km" if not havens_df.empty else ""
k4.metric(
    "Nearest Tier-1 Safe Haven",
    nearest_haven,
    delta=nearest_dist,
    delta_color="off",
)

st.markdown("---")

# Main Tactical Split: 3D Multi-Node Map + 72-Hour Reconstruction Curve
col_map, col_diag = st.columns([1.45, 1.0])

with col_map:
    st.subheader(f"Live Spatial Triage & Contagion Buffer: {selected_zone_name}")

    # Build map layers: Active Node (Red/Green) + All Tier-1 Safe Havens (Cyan) + Evacuation Arc
    active_point = pd.DataFrame([{
        "name": selected_zone_name,
        "lat": float(zone_data["latitude"]),
        "lon": float(zone_data["longitude"]),
        "color": [255, 65, 54, 220] if is_breach else [255, 165, 0, 220],
        "radius": 45000,
    }])

    safe_points = pd.DataFrame([
        {
            "name": r["territory_name"],
            "lat": float(r["latitude"]),
            "lon": float(r["longitude"]),
            "color": [0, 212, 255, 220],
            "radius": 38000,
        }
        for _, r in havens_df.iterrows()
    ])

    map_points = pd.concat([active_point, safe_points], ignore_index=True)

    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=map_points,
            get_position=["lon", "lat"],
            get_fill_color="color",
            get_radius="radius",
            pickable=True,
        )
    ]

    if not havens_df.empty:
        arc_data = pd.DataFrame([{
            "source_lon": float(zone_data["longitude"]),
            "source_lat": float(zone_data["latitude"]),
            "target_lon": float(havens_df.iloc[0]["longitude"]),
            "target_lat": float(havens_df.iloc[0]["latitude"]),
        }])
        layers.append(
            pdk.Layer(
                "ArcLayer",
                data=arc_data,
                get_source_position=["source_lon", "source_lat"],
                get_target_position=["target_lon", "target_lat"],
                get_source_color=[255, 140, 0, 200],
                get_target_color=[0, 212, 255, 200],
                get_width=4,
            )
        )

    view_state = pdk.ViewState(
        latitude=float(zone_data["latitude"]),
        longitude=float(zone_data["longitude"]),
        zoom=4.2,
        pitch=25,
    )

    st.pydeck_chart(
        pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
            initial_view_state=view_state,
            layers=layers,
            tooltip={"text": "{name}"},
        )
    )
    st.caption(
        "🟠 **Amber/Red Node:** Active Monitored Corridor | 🔵 **Cyan Nodes:** Contagion-Free Tier-1 Safe Havens | **Arc:** Primary Evacuation Vector"
    )

with col_diag:
    st.subheader("72-Hour Autoencoder Drift (6h Steps)")
    chart_df = pd.DataFrame({
        "Window": [f"T-{72 - i*6}h" for i in range(len(mse_curve))],
        "Reconstruction MSE": mse_curve,
    }).set_index("Window")
    st.line_chart(chart_df)

    if is_breach:
        st.error(
            f"🚨 **CRITICAL CASCADE WARNING:** {selected_zone_name} exceeded {threshold_sigma:.1f}σ "
            f"(Current: {current_sigma:.2f}σ | Saturation: {saturation_pct:.1f}%). Initiate OASIS CAP v1.2 dispatch."
        )
    elif saturation_pct >= float(zone_data["tau_1_threshold"]):
        st.warning(
            f"⚠️ **BOTTLENECK WATCH (τ₁ BREACHED):** Physical load ({saturation_pct:.1f}%) crossed "
            f"τ₁ threshold ({zone_data['tau_1_threshold']}%). Pre-position Tier-1 Safe Haven logistics."
        )
    else:
        st.success(
            f"✅ **CORRIDOR NOMINAL:** {selected_zone_name} operating below τ₁ ({zone_data['tau_1_threshold']}%) "
            f"and anomaly gate ({threshold_sigma:.1f}σ)."
        )

# Bottom Panel: Inclusive 72-Hour Safe-Haven Triage Matrix
st.markdown("---")
st.subheader("🛡️ 72-Hour Contagion-Free Tier-1 Safe-Haven Dispatch Matrix")
if not havens_df.empty:
    display_havens = havens_df[
        ["node_id", "territory_name", "elevation_m", "distance_km", "elevation_gain_m", "est_transit_hrs", "cap_status"]
    ].rename(
        columns={
            "node_id": "Node ID",
            "territory_name": "Tier-1 Safe Haven",
            "elevation_m": "Elevation (m)",
            "distance_km": "Distance (km)",
            "elevation_gain_m": "Net Elevation Gain (m)",
            "est_transit_hrs": "Est. Transit (hrs)",
            "cap_status": "OASIS CAP v1.2 Dispatch Status",
        }
    )
    st.dataframe(display_havens, use_container_width=True, hide_index=True)
