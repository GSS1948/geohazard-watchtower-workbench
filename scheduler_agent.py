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
    
    # 1. Load full 34-node matrix
    df_zones = load_territory_matrix("nodes_matrix.csv")
    logging.info(f"Loaded {len(df_zones)} global monitoring corridors from nodes_matrix.csv.")
    
    # 2. Run live multi-physics & TOC evaluation across every corridor
    now_utc = datetime.now(timezone.utc)
    eval_out = evaluate_all_corridors(df_zones, live_mode=True, now_utc=now_utc)
    
    # Unpack tuple: (telemetry_dict, results_df) or DataFrame directly
    telemetry_dict = {}
    results_df = df_zones.copy()
    if isinstance(eval_out, tuple):
        for item in eval_out:
            if isinstance(item, dict):
                telemetry_dict = item
            elif isinstance(item, pd.DataFrame):
                results_df = item
    elif isinstance(eval_out, pd.DataFrame):
        results_df = eval_out
    elif isinstance(eval_out, dict):
        telemetry_dict = eval_out

    # 3. Evaluate all 34 nodes against Tau-1 and Tau-2
    alerts_triggered = 0
    for _, row in results_df.iterrows():
        raw_id = row.get("node_id", "UNK")
        node_id = str(raw_id).zfill(2)
        name = str(row.get("territory_name", "Unknown Corridor"))
        lat = float(row.get("latitude", 0.0))
        lon = float(row.get("longitude", 0.0))
        tau_1 = float(row.get("tau_1_threshold", 80.0))
        tau_2 = float(row.get("tau_2_ceiling", 95.0))
        
        # Merge telemetry from dictionary if present
        t_data = telemetry_dict.get(raw_id) or telemetry_dict.get(node_id) or telemetry_dict.get(int(raw_id) if str(raw_id).isdigit() else raw_id) or {}
        if not isinstance(t_data, dict):
            t_data = {}
            
        combined = {**row.to_dict(), **t_data}
        
        # Extract numeric index and status across possible field names
        score = 0.0
        for key in ("composite_score", "risk_score", "hazard_index", "index_val", "score", "anomaly_score"):
            if key in combined and combined[key] is not None:
                try:
                    score = float(combined[key])
                    break
                except (ValueError, TypeError):
                    pass
                    
        status = str(combined.get("status", combined.get("alert_level", combined.get("state", "")))).upper()
        
        is_critical = (score >= tau_2) or any(w in status for w in ("CRITICAL", "RED", "BREACH", "EXTREME"))
        is_warning = (score >= tau_1) or any(w in status for w in ("WARNING", "AMBER", "ELEVATED", "SEVERE"))
        
        if is_critical or is_warning:
            alerts_triggered += 1
            severity = "Extreme" if is_critical else "Severe"
            urgency = "Immediate" if is_critical else "Expected"
            tier_label = "TAU-2 CEILING BREACH" if is_critical else "TAU-1 THRESHOLD EXCEEDED"
            
            logging.warning(f"[{tier_label}] Node {node_id} ({name}) | Score: {score:.2f} (Tau-1: {tau_1}, Tau-2: {tau_2})")
            
            generate_cap_alert(
                alert_id=f"NODE-{node_id}",
                sender="gspersonal.com@gmail.com",
                severity=severity,
                urgency=urgency,
                headline=f"{tier_label}: {name}",
                description=(
                    f"Automated 6-hr Watchtower telemetry scan detected elevated geohazard risk in {name} "
                    f"(Node {node_id}). Composite index: {score:.2f} vs Tau-1 ({tau_1}) / Tau-2 ({tau_2})."
                ),
                area_desc=f"{name} (Lat {lat:.4f}, Lon {lon:.4f})",
                polygon_coords=build_bounding_polygon(lat, lon)
            )

    if alerts_triggered == 0:
        logging.info(f"Scan complete across all {len(results_df)} corridors. All nodes within nominal TOC safety bounds.")
    else:
        logging.info(f"Scan complete. Generated and archived {alerts_triggered} OASIS CAP v1.2 alert(s) in alerts_archive/.")

if __name__ == "__main__":
    run_watchtower_scan()
