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
