import streamlit as st
import numpy as np
import pandas as pd

# ==========================================
# PAGE CONFIGURATION & HEADER
# ==========================================
st.set_page_config(
    page_title="Geohazard Watchtower Workbench",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 Geohazard Watchtower Workbench & Production War Room")
st.markdown(
    "**Theory of Constraints (TOC) & Multi-Physics Satellite Telemetry Early-Warning System** | "
    "Global Node Registry: 34 Active Corridor Nodes"
)
st.divider()

# ==========================================
# CORE APP INITIALIZATION & MOCK WORKBENCH
# ==========================================
st.sidebar.header("🧭 Command Room Controls")
active_mode = st.sidebar.radio(
    "Select Operational Mode",
    ["Global Node Status", "Historical Hindcast Verification", "SITREP Export & Dispatch"]
)

if active_mode == "Global Node Status":
    st.subheader("🌐 Federated Global Node Registry (34 Corridors)")
    st.markdown("Monitoring subduction megathrusts, alpine slope failure regimes, and pluvial saturation thresholds worldwide.")
    
    # Sample Node Summary Table
    node_summary = pd.DataFrame([
        {"Node ID": "NODE-01", "Corridor": "Himalayan Cryosphere (Nepal/India)", "Status": "NOMINAL", "τ₁ Margin": "78%"},
        {"Node ID": "NODE-12", "Corridor": "Peru-Chile Subduction Megathrust", "Status": "MONITORED PULSE", "τ₁ Margin": "64%"},
        {"Node ID": "NODE-24", "Corridor": "San Andreas Fault Margin (Cal.)", "Status": "NOMINAL", "τ₁ Margin": "82%"}
    ])
    st.dataframe(node_summary, use_container_width=True, hide_index=True)

elif active_mode == "SITREP Export & Dispatch":
    st.subheader("📋 Operational SITREP & Safe-Haven Dispatch")
    st.markdown("Generate offline operational briefs and automated CAP v1.2 warning packages for civil defense authorities.")
    if st.button("Generate Current Operational SITREP"):
        st.success("SITREP package compiled successfully. Ready for dissemination to regional dispatch nodes.")

# ==========================================
# HISTORICAL HINDCAST & SEISMIC ATTENUATION GATE
# ==========================================
st.divider()
st.subheader("📜 Historical Hindcast & Validation Module")

# --- SEISMIC DEPTH ATTENUATION & NOISE SUPPRESSION GATE (TOC VALIDATION) ---
def evaluate_seismic_bottleneck(magnitude, depth_km, epicentral_dist_km, tau1_pga_g=0.18, tau2_pga_g=0.35):
    hypocentral_dist = np.sqrt(depth_km**2 + epicentral_dist_km**2)
    surface_pga_g = (10**(0.5 * magnitude - 1.8)) / (hypocentral_dist**1.15)
    
    if surface_pga_g >= tau2_pga_g:
        status = "🔴 CRITICAL CASCADE (> τ₂): Safe-Haven Dispatch"
    elif surface_pga_g >= tau1_pga_g:
        status = "🟠 BOTTLENECK BREACH (> τ₁): Tactical Pre-Alert"
    else:
        status = "🟢 MONITORED PULSE (< τ₁): Suppressed (Zero Alert Fatigue)"
    return round(surface_pga_g, 4), status

with st.expander("🧭 Seismic Depth Attenuation Gate: Junín–Lima (Nov 21, 2026) Validation", expanded=True):
    st.markdown(
        "**Why wasn't the M6.7 Junín–Lima earthquake flagged as a red emergency?** "
        "Under Theory of Constraints ($\tau_1$ surface yield threshold = `0.18g`), hypocentral depth governs energy dissipation before reaching urban infrastructure."
    )
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        custom_depth = st.slider("Test Hypocentral Depth (km)", min_value=5, max_value=150, value=108, step=5)
    with col_d2:
        custom_dist = st.slider("Epicentral Distance to Urban Core (km)", min_value=10, max_value=200, value=140, step=10)

    pga_live, verdict_live = evaluate_seismic_bottleneck(6.7, custom_depth, custom_dist)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Simulated Event", "M6.7 Subduction")
    c2.metric("Surface PGA (g)", f"{pga_live} g", delta=f"{round(pga_live - 0.18, 4)} g vs τ₁", delta_color="inverse")
    c3.info(f"**Watchtower Gate:** {verdict_live}")

    # Benchmark Comparison Table
    benchmark_data = []
    for name, mag, dep, dist in [
        ("Junín–Lima Actual (Nov 21, 2026)", 6.7, 108, 140),
        ("Hypothetical Shallow Crustal Slip", 6.7, 15, 35)
    ]:
        pga_b, stat_b = evaluate_seismic_bottleneck(mag, dep, dist)
        benchmark_data.append({
            "Scenario": name,
            "Magnitude": f"M{mag}",
            "Depth (km)": dep,
            "Surface PGA (g)": pga_b,
            "Watchtower Gate Verdict": stat_b
        })
    st.dataframe(pd.DataFrame(benchmark_data), use_container_width=True, hide_index=True)
