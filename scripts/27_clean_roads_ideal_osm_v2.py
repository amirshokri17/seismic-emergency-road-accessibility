# -*- coding: utf-8 -*-
"""
27_clean_roads_ideal_osm_v2.py
------------------------------
Clean the raw OSM road network layer (eRoads_Ideal_OSM_v2_raw) into a standardized
polyline feature class (Roads_Ideal_OSM_v2_full_clean). Network completeness first:
KEEP every valid polyline (only null/zero-length geometries are skipped) and only
standardize the attribute table, classifying EmergencyUsable / NetworkRole rather
than filtering road types out.

Does NOT overwrite Roads_Ideal_OSM or Roads_Ideal_OSM_v2_clean, does NOT delete the
raw layer, and does NOT modify damage point or damage road-section layers.
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import arcpy

arcpy.env.overwriteOutput = True

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

APRX_PATH = os.environ.get("GPEM_APRX_PATH", "CURRENT")
MAIN_GDB = os.environ.get("GPEM_MAIN_GDB", r"C:\path\to\your_project.gdb")

RAW_SERVICE_URL = os.environ.get("GPEM_ROADS_SERVICE_URL", "")

RAW_LAYER_NAME = "eRoads_Ideal_OSM_v2_raw"
RAW_LOCAL_FC = os.path.join(MAIN_GDB, "eRoads_Ideal_OSM_v2_raw_import_tmp")

OUTPUT_FC = os.path.join(MAIN_GDB, "Roads_Ideal_OSM_v2_full_clean")

QA_CSV = os.path.join(os.environ.get("GPEM_QA_DIR", "qa"), "Roads_Ideal_OSM_v2_full_clean_QA.csv")

CLEAR_OUTPUT = os.environ.get("GPEM_CLEAR_OUTPUT", "false").strip().lower() in {"true", "1", "yes"}

OUTPUT_LAYER_NAME = "Roads Ideal OSM v2 Full Clean"

RAW_LAYER_PREFERRED_NAMES = [
    "eRoads_Ideal_OSM_v2_raw",
    "Roads_Ideal_OSM_v2_raw",
]
RAW_NAME_CONTAINS = "roads_ideal_osm_v2"

OLD_LAYER_NAMES = {
    "Roads_Ideal_OSM_v2_full_clean",
    "Roads Ideal OSM v2 Full Clean",
}

LANE_WIDTH_M = 3.25
MIN_GEOM_LENGTH_M = 0.0

# Highways treated as non-vehicle paths (kept, but EmergencyUsable=0).
PEDESTRIAN_ONLY_HIGHWAYS = {
    "footway",
    "path",
    "pedestrian",
    "cycleway",
    "steps",
    "bridleway",
}

VEHICLE_HIGHWAYS = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "road",
}

OUTPUT_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("RoadID", "LONG", None),
    ("SourceOSMID", "TEXT", 80),
    ("RoadName", "TEXT", 150),
    ("RoadRef", "TEXT", 80),
    ("RoadType", "TEXT", 80),
    ("RoadGroup", "TEXT", 80),
    ("Surface", "TEXT", 80),
    ("Access", "TEXT", 80),
    ("MotorVehicle", "TEXT", 80),
    ("ServiceType", "TEXT", 80),
    ("TrackType", "TEXT", 80),
    ("Bridge", "SHORT", None),
    ("Tunnel", "SHORT", None),
    ("Ford", "SHORT", None),
    ("Lanes", "DOUBLE", None),
    ("Width_m", "DOUBLE", None),
    ("WidthSource", "TEXT", 60),
    ("RoadWidthProxy_m", "DOUBLE", None),
    ("EmergencyUsable", "SHORT", None),
    ("NetworkRole", "TEXT", 100),
    ("QA_Status", "TEXT", 80),
    ("QA_Note", "TEXT", 255),
]

INSERT_FIELDS = ["SHAPE@"] + [n for n, _, _ in OUTPUT_FIELD_SPECS]

QA_FIELDS = [
    "SourceOID",
    "SourceOSMID",
    "RoadName",
    "RoadRef",
    "RoadType",
    "RoadGroup",
    "Surface",
    "Access",
    "MotorVehicle",
    "Lanes",
    "Width_m",
    "WidthSource",
    "RoadWidthProxy_m",
    "EmergencyUsable",
    "NetworkRole",
    "QA_Status",
    "QA_Note",
]

SKIP_FIELD_TYPES = frozenset({"OID", "Geometry", "GlobalID", "GUID", "Raster", "Blob"})

RAW_OSMID_FIELDS = ["F_id", "osm_id", "id"]
RAW_NAME_FIELDS = ["name", "official_name", "name_it", "loc_name", "old_name"]
RAW_REF_FIELDS = ["ref", "old_ref"]
RAW_MOTOR_FIELDS = ["motor_vehicle", "motorcar", "vehicle", "access"]
RAW_HIGHWAY_FIELDS = ["highway", "fclass", "type", "class"]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in ("none", "null", "<null>", "nan"):
        return ""
    return s


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    s = safe_text(value)
    if not s:
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    s = safe_text(value)
    if not s:
        return default
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


def truncate_text(value: str, max_len: Optional[int]) -> str:
    if max_len is None or max_len <= 0 or len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 3] + "..."


def row_to_dict(row: Tuple[Any, ...], fields: List[str]) -> Dict[str, Any]:
    return {fields[i]: row[i] for i in range(len(fields))}


def first_non_empty(row: Dict[str, str], field_names: List[str]) -> str:
    for fn in field_names:
        val = row.get(fn.lower(), "")
        if val:
            return val
    return ""


def parse_numeric(value: Any) -> Optional[float]:
    s = safe_text(value)
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def open_project() -> Optional[arcpy.mp.ArcGISProject]:
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        print("  Using CURRENT ArcGIS Pro project.")
        return aprx
    except Exception:
        pass
    try:
        aprx = arcpy.mp.ArcGISProject(APRX_PATH)
        print(f"  Opened project from disk: {APRX_PATH}")
        return aprx
    except Exception as ex:
        print(f"  ERROR: Could not open any ArcGIS Pro project: {ex}")
        return None


def find_raw_layer(aprx: arcpy.mp.ArcGISProject) -> Optional[Any]:
    all_layers: List[Any] = []
    for m in aprx.listMaps():
        for lyr in m.listLayers():
            try:
                if lyr.isFeatureLayer:
                    all_layers.append(lyr)
            except Exception:
                continue

    preferred_lower = [n.lower() for n in RAW_LAYER_PREFERRED_NAMES]
    for lyr in all_layers:
        try:
            if lyr.name.lower() in preferred_lower:
                print(f"  Found raw layer (preferred name): {lyr.name}")
                return lyr
        except Exception:
            continue

    for lyr in all_layers:
        try:
            if RAW_NAME_CONTAINS in lyr.name.lower():
                print(f"  Found raw layer (pattern match): {lyr.name}")
                return lyr
        except Exception:
            continue

    return None


def copy_service_to_local(service_url: str, out_fc: str) -> str:
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    last_error = None
    try:
        fs = arcpy.FeatureSet()
        fs.load(service_url)
        arcpy.management.CopyFeatures(fs, out_fc)
        if arcpy.Exists(out_fc):
            count = int(arcpy.management.GetCount(out_fc).getOutput(0))
            if count > 0:
                print(f"  Copied hosted service via FeatureSet.load -> {out_fc} ({count})")
                return out_fc
            last_error = "copied but feature count is 0"
    except Exception as ex:
        last_error = f"FeatureSet.load failed: {ex}"

    try:
        if arcpy.Exists(out_fc):
            arcpy.management.Delete(out_fc)
    except Exception:
        pass

    try:
        tmp_layer = "roads_v2_raw_tmp_layer"
        arcpy.management.MakeFeatureLayer(service_url, tmp_layer)
        arcpy.management.CopyFeatures(tmp_layer, out_fc)
        try:
            arcpy.management.Delete(tmp_layer)
        except Exception:
            pass
        if arcpy.Exists(out_fc):
            count = int(arcpy.management.GetCount(out_fc).getOutput(0))
            if count > 0:
                print(f"  Copied hosted service via MakeFeatureLayer -> {out_fc} ({count})")
                return out_fc
            last_error = "MakeFeatureLayer copied but count is 0"
    except Exception as ex:
        last_error = f"MakeFeatureLayer failed: {ex}"

    raise RuntimeError(
        f"Could not copy hosted FeatureServer layer.\nURL: {service_url}\n"
        f"Last error: {last_error}"
    )


def create_output_fc(out_fc: str, spatial_ref: arcpy.SpatialReference) -> None:
    if arcpy.Exists(out_fc):
        if CLEAR_OUTPUT:
            arcpy.management.Delete(out_fc)
        else:
            raise RuntimeError(
                f"Output already exists and CLEAR_OUTPUT is False: {out_fc}"
            )
    gdb, name = os.path.split(out_fc)
    arcpy.management.CreateFeatureclass(
        gdb, name, "POLYLINE", spatial_reference=spatial_ref
    )
    for fname, ftype, flen in OUTPUT_FIELD_SPECS:
        if ftype == "TEXT":
            arcpy.management.AddField(out_fc, fname, ftype, field_length=flen or 255)
        else:
            arcpy.management.AddField(out_fc, fname, ftype)
    print(f"  Created clean output FC: {out_fc}")


def detect_road_type(row: Dict[str, str]) -> str:
    for fn in RAW_HIGHWAY_FIELDS:
        val = row.get(fn, "").lower()
        if val:
            return val
    return ""


def is_access_restricted(row: Dict[str, str]) -> Tuple[bool, str]:
    """Return (restricted, reason) for explicit private / motor-no tags."""
    access = row.get("access", "").lower()
    if access == "private":
        return True, "access_private"
    for fn in ("motor_vehicle", "motorcar", "vehicle"):
        if row.get(fn, "").lower() == "no":
            return True, f"{fn}_no"
    return False, ""


def classify_road_group(road_type: str) -> str:
    if road_type in ("motorway", "trunk", "primary"):
        return "main_corridor"
    if road_type in ("secondary", "tertiary"):
        return "secondary_connector"
    if road_type in ("residential", "living_street", "unclassified", "road"):
        return "local_access"
    if road_type == "service":
        return "service_access"
    if road_type == "track":
        return "low_capacity_track"
    if road_type in PEDESTRIAN_ONLY_HIGHWAYS:
        return "non_vehicle_path"
    return "unknown_road"


def estimate_width_proxy(road_type: str) -> float:
    if road_type in ("motorway", "trunk", "primary", "main"):
        return 7.5
    if road_type == "secondary":
        return 6.5
    if road_type == "tertiary":
        return 5.5
    if road_type in ("residential", "living_street", "unclassified", "local", "road"):
        return 4.5
    if road_type == "service":
        return 3.5
    if road_type in ("track", "path", "footway", "cycleway", "pedestrian", "steps", "bridleway"):
        return 2.5
    return 4.5


def compute_width_fields(
    row: Dict[str, str], road_type: str
) -> Tuple[Optional[float], str, float]:
    width_m = parse_numeric(row.get("width", ""))
    lanes = parse_numeric(row.get("lanes", ""))

    if width_m is not None and width_m > 0:
        return width_m, "osm_width", estimate_width_proxy(road_type)

    if lanes is not None and lanes > 0:
        return lanes * LANE_WIDTH_M, "lanes_estimate", estimate_width_proxy(road_type)

    return None, "not_available", estimate_width_proxy(road_type)


def flag_yes_no(value: str) -> int:
    v = safe_text(value).lower()
    if v and v != "no":
        return 1
    return 0


def classify_emergency_usable(row: Dict[str, str], road_type: str) -> int:
    if road_type in PEDESTRIAN_ONLY_HIGHWAYS:
        return 0

    restricted, _ = is_access_restricted(row)
    if restricted:
        return 0

    if road_type in VEHICLE_HIGHWAYS:
        return 1
    if road_type in ("service", "track"):
        return 1

    # Unknown / untagged road type: assume vehicle-capable unless restricted.
    return 1


def classify_network_role(road_group: str, emergency_usable: int) -> str:
    if emergency_usable == 0:
        return "not_suitable_for_emergency_vehicle_access"
    mapping = {
        "main_corridor": "main_emergency_corridor",
        "secondary_connector": "secondary_emergency_connector",
        "local_access": "local_settlement_access",
        "service_access": "service_or_facility_access",
        "low_capacity_track": "low_capacity_possible_access",
        "non_vehicle_path": "not_suitable_for_emergency_vehicle_access",
        "unknown_road": "local_settlement_access",
    }
    return mapping.get(road_group, "local_settlement_access")


def classify_qa(road_type: str, road_group: str, emergency_usable: int, restricted: bool) -> Tuple[str, str]:
    if restricted:
        return (
            "kept_restricted_access",
            "Kept for network completeness; explicit private/no-vehicle access, "
            "not suitable for emergency vehicle routing.",
        )
    if road_group == "non_vehicle_path":
        return (
            "kept_non_vehicle_path",
            "Kept for network continuity; pedestrian/cycle path, not for emergency vehicles.",
        )
    if road_group == "low_capacity_track":
        return (
            "kept_low_capacity_track",
            "Kept as low-capacity track; possible but low-reliability emergency vehicle access.",
        )
    return (
        "kept_vehicle_road",
        "Kept as vehicle road; suitable for emergency vehicle access.",
    )


def geometry_to_2d_if_needed(geom: Any) -> Optional[Any]:
    if geom is None:
        return None
    try:
        length = geom.length
        if length is None or length <= MIN_GEOM_LENGTH_M:
            return None
        return geom
    except Exception:
        pass
    try:
        sr = geom.spatialReference
        array = geom.getPart(0)
        if array is None or array.count == 0:
            return None
        new_array = arcpy.Array()
        for i in range(array.count):
            pt = array.getObject(i)
            if pt:
                new_array.add(arcpy.Point(pt.X, pt.Y))
        if new_array.count < 2:
            return None
        return arcpy.Polyline(new_array, sr, False, False)
    except Exception:
        return None


def build_road_record(
    norm: Dict[str, str],
    source_oid: Any,
    geom: Any,
) -> Dict[str, Any]:
    road_type = detect_road_type(norm)
    road_group = classify_road_group(road_type)
    width_m, width_source, width_proxy = compute_width_fields(norm, road_type)
    lanes = parse_numeric(norm.get("lanes", ""))
    emergency_usable = classify_emergency_usable(norm, road_type)
    network_role = classify_network_role(road_group, emergency_usable)

    motor_vehicle = first_non_empty(norm, RAW_MOTOR_FIELDS)
    restricted, _ = is_access_restricted(norm)
    qa_status, qa_note = classify_qa(road_type, road_group, emergency_usable, restricted)

    return {
        "geometry": geom,
        "SourceOID": source_oid,
        "SourceOSMID": first_non_empty(norm, RAW_OSMID_FIELDS) or safe_text(source_oid),
        "RoadName": first_non_empty(norm, RAW_NAME_FIELDS),
        "RoadRef": first_non_empty(norm, RAW_REF_FIELDS),
        "RoadType": road_type,
        "RoadGroup": road_group,
        "Surface": norm.get("surface", ""),
        "Access": norm.get("access", ""),
        "MotorVehicle": motor_vehicle,
        "ServiceType": norm.get("service", ""),
        "TrackType": norm.get("tracktype", ""),
        "Bridge": flag_yes_no(norm.get("bridge", "")),
        "Tunnel": flag_yes_no(norm.get("tunnel", "")),
        "Ford": flag_yes_no(norm.get("ford", "")),
        "Lanes": lanes,
        "Width_m": width_m,
        "WidthSource": width_source,
        "RoadWidthProxy_m": width_proxy,
        "EmergencyUsable": emergency_usable,
        "NetworkRole": network_role,
        "QA_Status": qa_status,
        "QA_Note": qa_note,
    }


def write_qa_csv(rows: List[Dict[str, Any]]) -> None:
    out_dir = os.path.dirname(QA_CSV)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(QA_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out: Dict[str, str] = {}
            for col in QA_FIELDS:
                val = row.get(col, "")
                if col in ("Lanes", "Width_m", "RoadWidthProxy_m"):
                    fv = safe_float(val)
                    out[col] = f"{fv:.2f}" if fv is not None else ""
                elif col in ("EmergencyUsable", "SourceOID", "Bridge", "Tunnel", "Ford"):
                    iv = safe_int(val)
                    out[col] = safe_text(iv) if iv is not None else safe_text(val)
                else:
                    out[col] = safe_text(val)
            writer.writerow(out)
    print(f"  Wrote QA CSV: {QA_CSV}")


def add_output_to_map(aprx: arcpy.mp.ArcGISProject, out_fc: str) -> None:
    for m in aprx.listMaps():
        for lyr in list(m.listLayers()):
            try:
                if lyr.name in OLD_LAYER_NAMES:
                    m.removeLayer(lyr)
                    print(f"  Removed old map layer: {lyr.name}")
            except Exception:
                continue

    try:
        m = aprx.activeMap if aprx.activeMap else aprx.listMaps()[0]
    except Exception:
        print("  WARNING: No map available to add output layer.")
        return

    try:
        lyr = m.addDataFromPath(out_fc)
        if lyr:
            lyr.name = OUTPUT_LAYER_NAME
            print(f"  Added layer to map: {OUTPUT_LAYER_NAME}")
    except Exception as ex:
        print(f"  WARNING: Could not add output layer to map: {ex}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 72)
    print("27_clean_roads_ideal_osm_v2.py")
    print("=" * 72)

    aprx = open_project()
    raw_source_path: str
    source_descr: str

    if aprx is not None:
        raw_layer = find_raw_layer(aprx)
    else:
        raw_layer = None

    if raw_layer is not None:
        raw_source_path = raw_layer
        try:
            source_descr = f"map layer '{raw_layer.name}'"
        except Exception:
            source_descr = "map layer"
        print(f"  Using {source_descr}")
    else:
        print("  Raw layer not found in map; copying hosted FeatureServer...")
        if not RAW_SERVICE_URL:
            raise RuntimeError("Set GPEM_ROADS_SERVICE_URL or add the raw OSM roads layer to the ArcGIS map.")
        raw_source_path = copy_service_to_local(RAW_SERVICE_URL, RAW_LOCAL_FC)
        source_descr = "hosted FeatureServer service"

    desc = arcpy.Describe(raw_source_path)
    spatial_ref = desc.spatialReference
    oid_field = desc.OIDFieldName

    raw_fields = [
        f.name for f in arcpy.ListFields(raw_source_path) if f.type not in SKIP_FIELD_TYPES
    ]
    field_lower_map = {f.lower(): f for f in raw_fields}

    create_output_fc(OUTPUT_FC, spatial_ref)

    cursor_fields = [oid_field, "SHAPE@"] + raw_fields

    kept: List[Dict[str, Any]] = []
    qa_rows: List[Dict[str, Any]] = []
    raw_count = 0
    skipped_invalid_geom = 0

    with arcpy.da.SearchCursor(raw_source_path, cursor_fields) as cur:
        for row in cur:
            raw_count += 1
            rec = row_to_dict(row, cursor_fields)
            source_oid = rec.get(oid_field)
            raw_geom = rec.get("SHAPE@")

            norm: Dict[str, str] = {}
            for fl, orig in field_lower_map.items():
                norm[fl] = safe_text(rec.get(orig))

            # Only skip truly invalid geometry (null / zero-length). Keep everything else.
            geom = geometry_to_2d_if_needed(raw_geom)
            if geom is None:
                skipped_invalid_geom += 1
                qa_rows.append(
                    {
                        "SourceOID": source_oid,
                        "SourceOSMID": first_non_empty(norm, RAW_OSMID_FIELDS),
                        "RoadName": first_non_empty(norm, RAW_NAME_FIELDS),
                        "RoadRef": first_non_empty(norm, RAW_REF_FIELDS),
                        "RoadType": detect_road_type(norm),
                        "RoadGroup": "",
                        "Surface": norm.get("surface", ""),
                        "Access": norm.get("access", ""),
                        "MotorVehicle": first_non_empty(norm, RAW_MOTOR_FIELDS),
                        "Lanes": "",
                        "Width_m": "",
                        "WidthSource": "",
                        "RoadWidthProxy_m": "",
                        "EmergencyUsable": 0,
                        "NetworkRole": "not_suitable_for_emergency_vehicle_access",
                        "QA_Status": "invalid_geometry_skipped",
                        "QA_Note": "null or zero-length geometry",
                    }
                )
                continue

            kept.append(build_road_record(norm, source_oid, geom))

    type_counter: Counter = Counter()
    group_counter: Counter = Counter()
    width_source_counter: Counter = Counter()
    n_emergency_usable = 0
    n_not_usable = 0
    road_id = 0
    text_len = {n: l for n, t, l in OUTPUT_FIELD_SPECS if t == "TEXT"}

    with arcpy.da.InsertCursor(OUTPUT_FC, INSERT_FIELDS) as ic:
        for road_rec in kept:
            road_id += 1
            road_rec["RoadID"] = road_id
            row_vals: List[Any] = [road_rec["geometry"]]
            for fname, _, _ in OUTPUT_FIELD_SPECS:
                val = road_rec.get(fname)
                if fname in text_len and isinstance(val, str):
                    val = truncate_text(val, text_len[fname])
                row_vals.append(val)
            ic.insertRow(row_vals)

            type_counter[road_rec["RoadType"]] += 1
            group_counter[road_rec["RoadGroup"]] += 1
            width_source_counter[road_rec["WidthSource"]] += 1
            if road_rec["EmergencyUsable"] == 1:
                n_emergency_usable += 1
            else:
                n_not_usable += 1

            qa_rows.append(
                {
                    "SourceOID": road_rec["SourceOID"],
                    "SourceOSMID": road_rec["SourceOSMID"],
                    "RoadName": road_rec["RoadName"],
                    "RoadRef": road_rec["RoadRef"],
                    "RoadType": road_rec["RoadType"],
                    "RoadGroup": road_rec["RoadGroup"],
                    "Surface": road_rec["Surface"],
                    "Access": road_rec["Access"],
                    "MotorVehicle": road_rec["MotorVehicle"],
                    "Lanes": road_rec["Lanes"],
                    "Width_m": road_rec["Width_m"],
                    "WidthSource": road_rec["WidthSource"],
                    "RoadWidthProxy_m": road_rec["RoadWidthProxy_m"],
                    "EmergencyUsable": road_rec["EmergencyUsable"],
                    "NetworkRole": road_rec["NetworkRole"],
                    "QA_Status": road_rec["QA_Status"],
                    "QA_Note": road_rec["QA_Note"],
                }
            )

    write_qa_csv(qa_rows)

    if aprx is not None:
        add_output_to_map(aprx, OUTPUT_FC)

    final_count = int(arcpy.management.GetCount(OUTPUT_FC).getOutput(0))

    print("\n" + "=" * 72)
    print("QA SUMMARY — Roads Ideal OSM v2 Full Clean")
    print("=" * 72)
    print(f"  Raw source used:              {source_descr}")
    print(f"  Raw features read:            {raw_count}")
    print(f"  Output roads created:         {final_count}")
    print(f"  Invalid geometry skipped:     {skipped_invalid_geom}")
    print(f"  EmergencyUsable = 1:          {n_emergency_usable}")
    print(f"  EmergencyUsable = 0:          {n_not_usable}")
    print("  Count by RoadType:")
    for rtype, cnt in sorted(type_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        label = rtype if rtype else "(untagged)"
        print(f"    {label:<24} {cnt}")
    print("  Count by RoadGroup:")
    for rgroup, cnt in sorted(group_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {rgroup:<28} {cnt}")
    print("  Width source counts:")
    for src, cnt in sorted(width_source_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {src:<20} {cnt}")
    print(f"  Output feature class:         {OUTPUT_FC}")
    print(f"  QA CSV:                       {QA_CSV}")
    print("=" * 72 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())