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

with st.expander("🧭 Seismic Depth Attenuation Gate: Junín–Lima (Nov 21, 2026) Validation", expanded=False):
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
