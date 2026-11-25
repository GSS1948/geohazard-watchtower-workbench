import streamlit as st
import pandas as pd
import numpy as np
import requests
import xml.etree.ElementTree as ET
import math
import re
import os
import glob
from datetime import datetime

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Planetary Geohazard War Room",
    page_icon="🛡️",
    layout="wide"
)

# --- AUTO-REFRESH CONFIGURATION (30-Minute Autonomous Pulse) ---
# Automatically re-runs the script every 30 minutes (1800 seconds) to check live telemetry
from streamlit_autorefresh import st_autorefresh
count = st_autorefresh(interval=1800 * 1000, key="watchtower_autonomous_loop")

# --- 1. GEOSPATIAL & LIVE TELEMETRY HELPERS ---
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

@st.cache_data(ttl=1800)  # Refresh live feeds every 30 minutes
def fetch_live_macro_shocks():
    active_shocks = []
    # USGS Live M4.5+ Earthquakes
    try:
        usgs_url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
        resp = requests.get(usgs_url, timeout=8).json()
        for feat in resp.get("features", []):
            props = feat["properties"]
            coords = feat["geometry"]["coordinates"]
            active_shocks.append({
                "type": "Seismic Shock",
                "title": props.get("title", "USGS Earthquake"),
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "radius_km": 300.0 if float(props.get("mag", 0)) >= 6.0 else 150.0
            })
    except Exception:
        pass

    # GDACS Live Tropical Cyclones & Floods
    try:
        gdacs_url = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"
        resp = requests.get(gdacs_url, timeout=8).json()
        for feat in resp.get("features", []):
            props = feat.get("properties", {})
            geom = feat["geometry"]
            coords = geom.get("coordinates", [])
            event_type = props.get("eventtype", "")
            alert_level = str(props.get("alertlevel", "")).lower()
            if event_type in ["TC", "FL"] and alert_level in ["orange", "red"] and len(coords) >= 2:
                lon = float(coords[0]) if geom.get("type") == "Point" else float(coords[0][0][0])
                lat = float(coords[1]) if geom.get("type") == "Point" else float(coords[0][0][1])
                label = "Tropical Cyclone" if event_type == "TC" else "Severe Flood"
                active_shocks.append({
                    "type": label,
                    "title": props.get("name", label),
                    "lat": lat,
                    "lon": lon,
                    "radius_km": 450.0
                })
    except Exception:
        pass
    return active_shocks

@st.cache_data(ttl=1800)
def check_ground_truth_corroboration(corridor_name):
    """Queries live regional news RSS for physical ground confirmation."""
    location_keyword = corridor_name.split("_")[0]
    query = f"{location_keyword} (flood OR cyclone OR landslide OR earthquake OR evacuation OR waterlogging) when:2d"
    rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    
    try:
        resp = requests.get(rss_url, timeout=6)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")
            if len(items) > 0:
                top_headline = items[0].find("title").text
                return True, f"CONFIRMED ({len(items)} reports): {top_headline[:75]}..."
    except Exception:
        pass
    return False, "UNVERIFIED (No local ground reports in last 48h — Hold Dispatch)"

# --- 2. LOAD & VERIFY 34-NODE MATRIX ---
def load_and_verify_watchtower():
    csv_files = glob.glob("Geohazard_Watchtower_34Node_*.csv")
    if csv_files:
        latest_csv = max(csv_files, key=os.path.getmtime)
        df = pd.read_csv(latest_csv)
    else:
        st.warning("⚠️ No local CSV snapshot found (`Geohazard_Watchtower_34Node_*.csv`). Displaying baseline preview nodes.")
        df = pd.DataFrame({
            "Node_ID": ["Node_21", "Node_20", "Node_19", "Node_05", "Node_18"],
            "Corridor": ["Chile_Valparaiso_Trench", "Indonesia_Palu_Fault", "Japan_Tohoku_Arc", "Chennai_Coastal_Basin", "Meghalaya_Sohra_Slope"],
            "Hazard_Type": ["Subduction Seismic/Tsunami", "Strike-Slip Liquefaction", "Subduction Megathrust", "Pluvial Urban Flood", "High-Pluvial Karst"],
            "BlackBox_Idx": [1.44, 1.29, 0.95, 0.92, 0.85],
            "Tau2_98th": [1.05, 1.05, 0.99, 0.97, 0.98],
            "Tau1_90th": [0.80, 0.80, 0.75, 0.72, 0.70],
            "DEM_Safe_Haven_15km": ["-33.17°, -71.60° (Elev 553m | +553m S)", "-0.91°, 119.77° (Elev 1942m | +1932m W)", "38.25°, 140.78° (Elev 356m | +305m W)", "13.01°, 80.19° (Elev 36m | +26m SW)", "25.40°, 91.75° (Elev 1823m | +523m N)"]
        })

    df["Gate_Ratio_%"] = ((df["BlackBox_Idx"] / df["Tau2_98th"]) * 100).round(1)
    shocks = fetch_live_macro_shocks()
    
    df["Live_Shock_Flag"] = ""
    df["Ground_Truth"] = "Skipped — Nominal Baseline (<65% Gate)"
    df["Ground_Verified"] = False

    if "Lat" not in df.columns or "Lon" not in df.columns:
        lats, lons = [], []
        for val in df["DEM_Safe_Haven_15km"]:
            m = re.search(r"(-?\d+\.\d+)[°,\s]+(-?\d+\.\d+)", str(val))
            lats.append(float(m.group(1)) if m else 0.0)
            lons.append(float(m.group(2)) if m else 0.0)
        df["Lat"], df["Lon"] = lats, lons

    for idx, row in df.iterrows():
        n_lat, n_lon = float(row["Lat"]), float(row["Lon"])
        matched_events = []
        for shock in shocks:
            dist = haversine_km(n_lat, n_lon, shock["lat"], shock["lon"])
            if dist <= shock["radius_km"]:
                matched_events.append(f"{shock['type']}: {shock['title']} ({int(dist)}km)")
        
        if matched_events:
            df.at[idx, "Live_Shock_Flag"] = " | ".join(matched_events)
            if "Cyclone" not in str(row["Hazard_Type"]):
                df.at[idx, "Hazard_Type"] = f"{row['Hazard_Type']} + {matched_events[0].split(':')[0]}"

        if float(row["Gate_Ratio_%"]) >= 65.0 or matched_events:
            is_verified, evidence = check_ground_truth_corroboration(row["Corridor"])
            df.at[idx, "Ground_Verified"] = is_verified
            df.at[idx, "Ground_Truth"] = evidence

    def assign_tier(row):
        hazard = str(row.get("Hazard_Type", "")).lower()
        gate_ratio = float(row["Gate_Ratio_%"])
        ground_ok = bool(row.get("Ground_Verified", False))
        is_fast_macro = any(k in hazard for k in ["cyclone", "storm", "depression", "pluvial urban flood", "maritime surge"])
        breached = (row["BlackBox_Idx"] >= row["Tau2_98th"]) or (is_fast_macro and gate_ratio >= 75.0)
        
        if breached:
            return "🔴 RED — VERIFIED CRITICAL (DISPATCH)" if ground_ok else "🟠 AMBER — UNVERIFIED ANOMALY (HOLD DISPATCH)"
        elif gate_ratio >= 75.0 and row["BlackBox_Idx"] >= row["Tau1_90th"]:
            return "🟠 AMBER — PRE-CRITICAL"
        elif row["BlackBox_Idx"] >= row["Tau1_90th"]:
            return "🟡 YELLOW — EARLY WATCH"
        else:
            return "🟢 GREEN — NOMINAL"

    df["Alert_Tier"] = df.apply(assign_tier, axis=1)
    return df.sort_values(by="Gate_Ratio_%", ascending=False).reset_index(drop=True)

# --- 3. RENDER WAR ROOM UI ---
st.title("🛡️ Planetary Geohazard Watchtower — Executive War Room")
st.markdown("**Autonomous 72-Hour Bottleneck Surveillance • Two-Key Ground Verification • 15km Safe-Haven Dispatch**")

# Status Bar & Manual Override
col_status, col_btn = [st.columns([3, 1])[0], st.columns([3, 1])[1]]
with col_status:
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    st.info(f"🟢 **SYSTEM ON GUARD (Autonomous Mode Active):** Background telemetry polling every 30 mins. Last Refreshed: `{current_time_str}` (Cycle #{count})")
with col_btn:
    if st.button("🔄 Force Immediate Poll", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

df = load_and_verify_watchtower()

# Top Executive Metrics Bar
c_red = df["Alert_Tier"].str.contains("🔴 RED").sum()
c_amb = df["Alert_Tier"].str.contains("🟠 AMBER").sum()
c_yel = df["Alert_Tier"].str.contains("🟡 YELLOW").sum()
c_grn = df["Alert_Tier"].str.contains("🟢 GREEN").sum()

m1, m2, m3, m4 = st.columns(4)
m1.metric("🔴 Red (Verified Dispatch)", f"{c_red:02d}")
m2.metric("🟠 Amber (Hold / Pre-Critical)", f"{c_amb:02d}")
m3.metric("🟡 Yellow (Early Watch)", f"{c_yel:02d}")
m4.metric("🟢 Green (Nominal Baseline)", f"{c_grn:02d}")

st.markdown("---")

# Priority Field Dispatch Cards
st.subheader("🚨 Priority Field Dispatch & Duty Officer Directives")
priority_df = df[df["Alert_Tier"].str.contains("🔴 RED|🟠 AMBER", na=False)]

if priority_df.empty:
    st.success("🟢 ALL CLEAR: No corridors currently in RED or AMBER status.")
else:
    for _, row in priority_df.iterrows():
        is_red = "🔴 RED" in str(row["Alert_Tier"])
        with st.container(border=True):
            col_a, col_b = st.columns([3, 1])
            with col_a:
                if is_red:
                    st.error(f"**{row['Alert_Tier']}  |  {row['Node_ID']} : {row['Corridor']}**")
                else:
                    st.warning(f"**{row['Alert_Tier']}  |  {row['Node_ID']} : {row['Corridor']}**")
                st.markdown(f"**Hazard Type:** `{row['Hazard_Type']}` &nbsp;|&nbsp; **Gate Saturation:** `{row['Gate_Ratio_%']}%`")
                st.markdown(f"**Ground Verification:** {row['Ground_Truth']}")
                st.markdown(f"**15km Safe Haven Vector:** 📍 `{row['DEM_Safe_Haven_15km']}`")
            with col_b:
                m = re.search(r"(-?\d+\.\d+)[°,\s]+(-?\d+\.\d+)", str(row["DEM_Safe_Haven_15km"]))
                if m:
                    maps_url = f"https://www.google.com/maps/search/?api=1&query={m.group(1)},{m.group(2)}"
                    st.link_button("🗺️ Open Safe Haven Pin", maps_url, use_container_width=True)

# Yellow Watch & Green Baseline Summary Strip
yellow_df = df[df["Alert_Tier"].str.contains("🟡 YELLOW", na=False)]
if not yellow_df.empty:
    st.info(f"🟡 **YELLOW — EARLY WATCH ({len(yellow_df)} Corridors Building Stress):** " + ", ".join([f"{r['Node_ID']} ({r['Corridor']} - {r['Gate_Ratio_%']}%)" for _, r in yellow_df.iterrows()]))
else:
    st.success(f"🟢 **REMAINING SYSTEM POSTURE:** 0 Corridors in Yellow Watch. All remaining {c_grn} global corridors are operating within Nominal Baseline.")

st.markdown("---")

# Master 34-Corridor Posture Matrix
st.subheader("📋 Master 34-Corridor Operational Posture Matrix")
display_cols = ["Node_ID", "Corridor", "Hazard_Type", "Gate_Ratio_%", "Alert_Tier", "Ground_Truth", "DEM_Safe_Haven_15km"]
avail_cols = [c for c in display_cols if c in df.columns]

def color_tiers(row):
    tier = str(row.get("Alert_Tier", ""))
    if "🔴 RED" in tier:
        return ["background-color: #ffebee; color: #b71c1c; font-weight: bold;"] * len(row)
    elif "🟠 AMBER" in tier:
        return ["background-color: #fff3e0; color: #e65100; font-weight: bold;"] * len(row)
    elif "🟡 YELLOW" in tier:
        return ["background-color: #fffde7; color: #f57f17;"] * len(row)
    return ["background-color: #e8f5e9; color: #1b5e20;"] * len(row)

st.dataframe(df[avail_cols].style.apply(color_tiers, axis=1), use_container_width=True, hide_index=True)
