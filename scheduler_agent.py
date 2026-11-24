import logging
from datetime import datetime, timezone
import pandas as pd
from engine import load_territory_matrix, evaluate_all_corridors
from cap_generator import generate_cap_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def build_bounding_polygon(lat: float, lon: float, delta: float = 0.35) -> str:
    """Builds a closed OASIS CAP v1.2 bounding polygon around a corridor centroid."""
    p1 = f"{lat - delta:.4f},{lon - delta:.4f}"
    p2 = f"{lat + delta:.4f},{lon - delta:.4f}"
    p3 = f"{lat + delta:.4f},{lon + delta:.4f}"
    p4 = f"{lat - delta:.4f},{lon + delta:.4f}"
    return f"{p1} {p2} {p3} {p4} {p1}"

def run_watchtower_scan():
    logging.info("Initializing 6-Hour Geohazard Watchtower live scan across all corridors...")
    
    # 1. Load full 34-node matrix and lookup coordinates
    df_zones = load_territory_matrix("nodes_matrix.csv")
    coord_lookup = {}
    for _, z in df_zones.iterrows():
        nid = str(z.get("node_id", "")).strip()
        coord_lookup[nid] = (float(z.get("latitude", 0.0)), float(z.get("longitude", 0.0)))
        if nid.isdigit():
            coord_lookup[str(int(nid))] = coord_lookup[nid]

    logging.info(f"Loaded {len(df_zones)} global monitoring corridors from nodes_matrix.csv.")
    
    # 2. Run live multi-physics & TOC evaluation across every corridor
    now_utc = datetime.now(timezone.utc)
    eval_out = evaluate_all_corridors(df_zones, live_mode=True, now_utc=now_utc)
    
    results_df = df_zones.copy()
    if isinstance(eval_out, tuple):
        for item in eval_out:
            if isinstance(item, pd.DataFrame):
                results_df = item
                break
    elif isinstance(eval_out, pd.DataFrame):
        results_df = eval_out

    # 3. Evaluate corridors using Tactical Command Room Status & Sigma Gates (3.0σ)
    alerts_triggered = 0
    for _, row in results_df.iterrows():
        raw_id = str(row.get("Node", row.get("node_id", "UNK"))).strip()
        node_id = raw_id.zfill(2)
        name = str(row.get("Corridor", row.get("territory_name", "Unknown Corridor")))
        
        lat, lon = coord_lookup.get(raw_id, (float(row.get("latitude", 0.0)), float(row.get("longitude", 0.0))))
        status = str(row.get("Status", row.get("status", ""))).upper()
        
        now_sigma = float(row.get("Now σ", row.get("now_sigma", 0.0)) or 0.0)
        peak_sigma = float(row.get("72h Peak σ", row.get("peak_72h_sigma", 0.0)) or 0.0)
        sat_val = row.get("Saturation", row.get("saturation", "N/A"))
        
        is_red = ("RED" in status) or (now_sigma >= 3.0)
        is_orange = ("ORANGE" in status) or (peak_sigma >= 3.0)
        
        if is_red or is_orange:
            alerts_triggered += 1
            severity = "Extreme" if is_red else "Severe"
            urgency = "Immediate" if is_red else "Expected"
            tier_label = "RED / CRITICAL BREACH" if is_red else "ORANGE / HIGH ALERT"
            
            logging.warning(
                f"[{tier_label}] Node {node_id} ({name}) | Now: {now_sigma:.2f}σ | "
                f"72h Peak: {peak_sigma:.2f}σ (Gate: 3.00σ) | Sat: {sat_val}"
            )
            
            generate_cap_alert(
                alert_id=f"NODE-{node_id}",
                sender="gspersonal.com@gmail.com",
                severity=severity,
                urgency=urgency,
                headline=f"{tier_label}: {name}",
                description=(
                    f"Automated 6-hr Watchtower telemetry scan detected elevated geohazard risk in {name} "
                    f"(Node {node_id}). Status: {status}. Live Now: {now_sigma:.2f}σ, "
                    f"72h Peak: {peak_sigma:.2f}σ (Fixed Anomaly Gate: 3.00σ), Saturation: {sat_val}."
                ),
                area_desc=f"{name} (Lat {lat:.4f}, Lon {lon:.4f})",
                polygon_coords=build_bounding_polygon(lat, lon)
            )

    if alerts_triggered == 0:
        logging.info(f"Scan complete across all {len(results_df)} active corridors. All nodes GREEN / NORMAL (< 3.00σ).")
    else:
        logging.info(f"Scan complete. Generated and archived {alerts_triggered} OASIS CAP v1.2 alert(s) in alerts_archive/.")

if __name__ == "__main__":
    run_watchtower_scan()
