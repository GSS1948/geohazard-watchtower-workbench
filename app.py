import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk

st.set_page_config(
    page_title="Geohazard Watchtower War Room",
    page_icon="🛰️",
    layout="wide"
)

st.title("🛰️ Geohazard Watchtower War Room")
st.markdown("**Theory of Constraints (TOC) Multi-Physics Telemetry & 72-Hour Triage Dashboard**")

# Sidebar Controls for Macro-Regions
st.sidebar.header("Macro-Region Selection")
region = st.sidebar.selectbox(
    "Select Global Zone",
    [
        "Himalayan Tectonic Arc (Nepal/India)",
        "Andean Fault Zones",
        "Japanese Volcanic Ridges (Miyagi)",
        "Wayanad Monsoonal Escarpments"
    ]
)

threshold = st.sidebar.slider("Anomaly Security Threshold ($\sigma$)", 1.0, 4.0, 3.0, 0.1)

# Main Display Area
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"Live Spatial Triage: {region}")

    # Sample coordinate data for demo rendering
    map_data = pd.DataFrame({
        'lat': [28.2375, 28.2450, 28.2100, 28.2550],
        'lon': [84.8655, 84.8720, 84.8400, 84.8900],
        'status': ['Safe Haven (★)', 'Amber Alert', 'Red Alert Gate', 'Safe Haven (★)'],
        'color': [[0, 255, 0, 160], [255, 165, 0, 160], [255, 0, 0, 160], [0, 255, 0, 160]]
    })

    layer = pdk.Layer(
        "ScatterplotLayer",
        map_data,
        get_position=["lon", "lat"],
        get_color="color",
        get_radius=500,
        pickable=True,
    )

    view_state = pdk.ViewState(
        latitude=map_data["lat"].mean(),
        longitude=map_data["lon"].mean(),
        zoom=10,
        pitch=40,
    )

    r = pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip={"text": "Status: {status}"})
    st.pydeck_chart(r)

with col2:
    st.subheader("Neural Reconstruction MSE")
    loss_df = pd.DataFrame({
        'Time Step': range(1, 11),
        'MSE Loss': [0.12, 0.15, 0.18, 0.22, 0.31, 0.45, 0.88, 1.45, 2.10, 3.85]
    })
    st.line_chart(loss_df.set_index('Time Step'))
    st.metric(label="Current Peak Anomaly Gate", value=f"{threshold}$\sigma$", delta="Active Breach")

st.markdown("---")
st.info("💡 **Tip:** This War Room app runs locally or via Streamlit Community Cloud, providing real-time evaluation alongside your GitHub Jupyter notebook.")
