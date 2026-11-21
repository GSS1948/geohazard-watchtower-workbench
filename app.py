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

    # Append Ground SITREP Summary Box
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
