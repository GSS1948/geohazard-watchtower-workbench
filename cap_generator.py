import xml.etree.ElementTree as ET
from datetime import datetime, timezone

def generate_cap_alert(alert_id, sender, severity, urgency, headline, description, area_desc, polygon_coords):
    """
    Generates an OASIS CAP v1.2 compliant XML alert string for institutional dispatch.
    """
    cap_ns = "urn:oasis:names:tc:emergency:cap:1.2"
    ET.register_namespace('', cap_ns)
    
    # Root Element
    alert = ET.Element(f"{{{cap_ns}}}alert")
    
    # Identifier & Metadata
    ET.SubElement(alert, f"{{{cap_ns}}}identifier").text = f"GEOWATCH-{alert_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    ET.SubElement(alert, f"{{{cap_ns}}}sender").text = sender
    ET.SubElement(alert, f"{{{cap_ns}}}sent").text = datetime.now(timezone.utc).isoformat()
    ET.SubElement(alert, f"{{{cap_ns}}}status").text = "Actual"
    ET.SubElement(alert, f"{{{cap_ns}}}msgType").text = "Alert"
    ET.SubElement(alert, f"{{{cap_ns}}}scope").text = "Public"
    
    # Info Block
    info = ET.SubElement(alert, f"{{{cap_ns}}}info")
    ET.SubElement(info, f"{{{cap_ns}}}category").text = "Geophysical"
    ET.SubElement(info, f"{{{cap_ns}}}event").text = "Automated Geohazard Watchtower Warning"
    ET.SubElement(info, f"{{{cap_ns}}}urgency").text = urgency # Immediate, Expected, etc.
    ET.SubElement(info, f"{{{cap_ns}}}severity").text = severity # Severe, Extreme, etc.
    ET.SubElement(info, f"{{{cap_ns}}}certainty").text = "Observed"
    ET.SubElement(info, f"{{{cap_ns}}}headline").text = headline
    ET.SubElement(info, f"{{{cap_ns}}}description").text = description
    
    # Area Block
    area = ET.SubElement(info, f"{{{cap_ns}}}area")
    ET.SubElement(area, f"{{{cap_ns}}}areaDesc").text = area_desc
    if polygon_coords:
        polygon = ET.SubElement(area, f"{{{cap_ns}}}polygon")
        polygon.text = polygon_coords

    # Return formatted XML string
    xml_tree = ET.ElementTree(alert)
    ET.indent(xml_tree, space="  ")
    
    # Using a safe string conversion
    from io import BytesIO
    f = BytesIO()
    xml_tree.write(f, encoding="utf-8", xml_declaration=True)
    return f.getvalue().decode("utf-8")

if __name__ == "__main__":
    # Test generation locally
    sample_xml = generate_cap_alert(
        alert_id="HK-001",
        sender="gspersonal.com@gmail.com",
        severity="Severe",
        urgency="Immediate",
        headline="Automated LSTM Slope Instability Alert: Hindu Kush Corridor",
        description="Reconstruction error threshold breached in multi-physics telemetry. Potential slope failure detected within 72-hour window.",
        area_desc="Hindu Kush / Northern Transboundary Corridor",
        polygon_coords="36.5,71.0 36.8,71.5 36.2,71.8 36.5,71.0"
    )
    print("--- CAP v1.2 XML Generated Successfully ---")
    print(sample_xml[:500] + "\n[... truncated for preview ...]")
