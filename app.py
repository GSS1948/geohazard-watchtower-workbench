import streamlit as st
import numpy as np
import pandas as pd
import pydeck as pdk
from engine import load_territory_matrix, compute_toc_bottleneck_sigma

st.set_page_config(page_title="Geohazard Watchtower War Room", layout="wide")

st.title("🛰️ Geohazard Watchtower War Room")
st.markdown("**Theory of Constraints (TOC) Multi-Physics Telemetry & 72-Hour Triage Dashboard**")

# Sidebar Controls
st.sidebar.header("Macro-Region Selection")
nodes_df = load_territory_matrix()
selected_zone = st.sidebar.selectbox("Select Global Zone", nodes_df['territory_name'].values)

threshold_sigma = st.sidebar.slider("Anomaly Security Threshold (σ)", 1.0, 4.0, 3.0, 0.1)

# Filter data for selected zone
zone_data = nodes_df[nodes_df['territory_name'] == selected_zone].iloc[0]

st.subheader(f"Live Spatial Triage: {selected_zone}")

# Run Black Box computation
np.random.seed(42)
mock_stream = np.cumsum(np.random.normal(0.05, 0.2, 10)) + 10.0
current_sigma, mse_curve, is_breach = compute_toc_bottleneck_sigma(mock_stream, threshold_sigma)

# Display Map using PyDeck centered on zone coordinates
lat, lon = float(zone_data['latitude']), float(zone_data['longitude'])
view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=7, pitch=30)

marker_color = [255, 50, 50, 200] if is_breach else [0, 220, 100, 200]

map_df = pd.DataFrame({
    'lat': [lat],
    'lon': [lon],
    'zone': [selected_zone],
    'status': ['Active Breach' if is_breach else 'Stable']
})

map_layer = pdk.Layer(
    "ScatterplotLayer",
    data=map_df,
    get_position='[lon, lat]',
    get_fill_color=marker_color,
    get_radius=20000,
    pickable=True,
)

r = pdk.Deck(
    layers=[map_layer],
    initial_view_state=view_state,
    map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    tooltip={"text": "{zone}\nStatus: {status}"}
)
st.pydeck_chart(r)

# Metrics & Chart
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Neural Reconstruction MSE")
    chart_data = pd.DataFrame({"MSE": mse_curve}, index=range(1, len(mse_curve) + 1))
    st.line_chart(chart_data)

with col2:
    st.subheader("Triage Telemetry")
    st.metric(
        label="Current Peak Anomaly Gate", 
        value=f"{current_sigma:.2f}σ", 
        delta="Active Breach" if is_breach else "Nominal"
    )
    if is_breach:
        st.error(f"⚠️ **CRITICAL TOC BOTTLENECK BREACH DETECTED** at {selected_zone}! 72-hour cascading hazard vector active.")
    else:
        st.success(f"✅ Corridor stable under current σ threshold ({threshold_sigma}).")
