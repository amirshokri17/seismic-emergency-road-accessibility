# -*- coding: utf-8 -*-
"""
26_clean_emergency_service_centers.py
-------------------------------------
Clean and standardize the Overpass/OSM emergency-service import (already in the
ArcGIS Pro map) into one local point feature class with a minimal, useful
schema. Classifies facility types (Italian-aware), matches each facility to the
nearest reference road, removes duplicates, and writes a QA report.

Emergency_Service_Centers is a cleaned OSM/Overpass-derived emergency-service
candidate layer (health, fire, police/carabinieri, civil-protection,
ambulance/first-aid, municipality, government coordination). It EXCLUDES shelter
candidates, which are defined separately in the next phase.
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

ROAD_FC = os.path.join(MAIN_GDB, "Roads_Ideal_OSM")
FALLBACK_ROAD_FC = os.path.join(MAIN_GDB, "Roads_In_AerialCoverage_Clipped")

OUTPUT_FC = os.path.join(MAIN_GDB, "Emergency_Service_Centers")

QA_CSV = os.path.join(os.environ.get("GPEM_QA_DIR", "qa"), "Emergency_Service_Centers_QA.csv")

CLEAR_OUTPUT = os.environ.get("GPEM_CLEAR_OUTPUT", "false").strip().lower() in {"true", "1", "yes"}
CLEAR_RAW_FROM_MAP_ONLY = False

OUTPUT_LAYER_NAME = "Emergency Service Centers"

RAW_LAYER_PREFERRED_NAMES = [
    "emergency_services_roads_extent_JSONToFeatures",
    "emergency_serv_JSONToFeature",
    "Emergency_Service_Centers_OSM",
]
RAW_NAME_CONTAINS_PRIMARY = "emergency"
RAW_NAME_CONTAINS_SECONDARY = ["jsontofeatures", "osm", "services"]

OLD_LAYER_NAMES = {
    "Emergency_Service_Centers",
    "Emergency Service Centers",
    "emergency_serv_JSONToFeature",
    "Emergency_Service_Centers_OSM",
}

SNAP_OK_M = 50.0
DUP_DIST_M = 10.0

SOURCE_VALUE = "OpenStreetMap / Overpass import"
VERIFICATION_VALUE = "needs_verification"
ACCESS_STATUS_VALUE = "not_assessed"
ACCESS_NOTE_BASE = "Cleaned emergency-service candidate; accessibility assessment pending."
NOTE_SNAPPED = " Snapped to nearby road."
NOTE_FAR = " Farther than 50 m from reference road; check manually."

OUTPUT_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("FacilityID", "LONG", None),
    ("FacilityName", "TEXT", 150),
    ("FacilityType", "TEXT", 80),
    ("FacilitySubtype", "TEXT", 100),
    ("OperatorName", "TEXT", 150),
    ("Municipality", "TEXT", 100),
    ("Address", "TEXT", 200),
    ("Phone", "TEXT", 80),
    ("Email", "TEXT", 120),
    ("Website", "TEXT", 200),
    ("Source", "TEXT", 80),
    ("SourceOSMID", "TEXT", 80),
    ("VerificationStatus", "TEXT", 60),
    ("NearestRoadOID", "LONG", None),
    ("SnapDist_m", "DOUBLE", None),
    ("AccessStatus", "TEXT", 80),
    ("AccessNote", "TEXT", 255),
    ("LONG", "DOUBLE", None),
    ("LAT", "DOUBLE", None),
]

INSERT_FIELDS = ["SHAPE@"] + [n for n, _, _ in OUTPUT_FIELD_SPECS]

QA_FIELDS = [
    "FacilityID",
    "SourceOSMID",
    "FacilityName",
    "FacilityType",
    "FacilitySubtype",
    "Municipality",
    "NearestRoadOID",
    "SnapDist_m",
    "VerificationStatus",
    "AccessStatus",
    "QA_Status",
    "QA_Note",
]

SKIP_FIELD_TYPES = frozenset({"OID", "Geometry", "GlobalID", "GUID", "Raster", "Blob"})

RAW_NAME_FIELDS = ["name", "operator", "amenity", "healthcare", "emergency", "office"]
RAW_MUNI_FIELDS = ["addr_city", "addr_suburb", "comune", "municipality"]
RAW_OSMID_FIELDS = ["osm_id", "id", "F_id"]

# Explicit non-emergency / shelter / public-space tags -> skip.
NON_EMERGENCY_AMENITY = {
    "school",
    "kindergarten",
    "college",
    "university",
    "parking",
    "parking_space",
    "place_of_worship",
    "restaurant",
    "cafe",
    "bar",
    "fast_food",
    "bank",
    "marketplace",
    "library",
    "theatre",
    "cinema",
    "community_centre",
    "shelter",
    "fuel",
    "fountain",
    "bench",
}

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
            nl = lyr.name.lower()
        except Exception:
            continue
        if RAW_NAME_CONTAINS_PRIMARY in nl and any(
            tok in nl for tok in RAW_NAME_CONTAINS_SECONDARY
        ):
            print(f"  Found raw layer (pattern match): {lyr.name}")
            return lyr

    for lyr in all_layers:
        try:
            if RAW_NAME_CONTAINS_PRIMARY in lyr.name.lower():
                print(f"  Found raw layer (emergency only): {lyr.name}")
                return lyr
        except Exception:
            continue

    return None


def create_clean_output_fc(out_fc: str, spatial_ref: arcpy.SpatialReference) -> None:
    if arcpy.Exists(out_fc):
        if CLEAR_OUTPUT:
            arcpy.management.Delete(out_fc)
        else:
            raise RuntimeError(
                f"Output already exists and CLEAR_OUTPUT is False: {out_fc}"
            )
    gdb, name = os.path.split(out_fc)
    arcpy.management.CreateFeatureclass(
        gdb, name, "POINT", spatial_reference=spatial_ref
    )
    for fname, ftype, flen in OUTPUT_FIELD_SPECS:
        if ftype == "TEXT":
            arcpy.management.AddField(out_fc, fname, ftype, field_length=flen or 255)
        else:
            arcpy.management.AddField(out_fc, fname, ftype)
    print(f"  Created clean output FC: {out_fc}")


def build_address(row: Dict[str, str]) -> str:
    street = row.get("addr_street", "")
    housenumber = row.get("addr_housenumber", "")
    postcode = row.get("addr_postcode", "")
    city = row.get("addr_city", "")
    line1 = " ".join(p for p in (street, housenumber) if p)
    line2 = " ".join(p for p in (postcode, city) if p)
    return ", ".join(p for p in (line1, line2) if p)


def is_non_emergency_candidate(row: Dict[str, str]) -> bool:
    """True for shelters / schools / sports / parking / camp / hotel / church /
    generic public space / marketplace, unless clearly an emergency facility."""
    amenity = row.get("amenity", "").lower()
    healthcare = row.get("healthcare", "").lower()
    emergency = row.get("emergency", "").lower()
    office = row.get("office", "").lower()
    tourism = row.get("tourism", "").lower()
    leisure = row.get("leisure", "").lower()
    shop = row.get("shop", "").lower()
    building = row.get("building", "").lower()

    # Clear emergency signals always win.
    if amenity in (
        "hospital",
        "clinic",
        "doctors",
        "pharmacy",
        "fire_station",
        "police",
        "emergency_service",
        "townhall",
    ):
        return False
    if healthcare in ("hospital", "clinic", "doctor", "pharmacy"):
        return False
    if emergency:
        return False
    if office == "government":
        return False

    if tourism or leisure or shop:
        return True
    if amenity in NON_EMERGENCY_AMENITY:
        return True
    if amenity == "place_of_worship" or building in ("church", "chapel", "cathedral"):
        return True
    return False


def _contains_any(text: str, tokens: List[str]) -> bool:
    return any(tok in text for tok in tokens)


def classify_facility_type(row: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """Return (FacilityType, FacilitySubtype), or None to skip the feature."""
    amenity = row.get("amenity", "").lower()
    healthcare = row.get("healthcare", "").lower()
    emergency = row.get("emergency", "").lower()
    office = row.get("office", "").lower()
    name = row.get("name", "").lower()
    operator = row.get("operator", "").lower()
    description = row.get("description", "").lower()
    description_it = row.get("description_it", "").lower()
    townhall_type = row.get("townhall_type", "").lower()
    text = " ".join(
        (name, operator, description, description_it, townhall_type)
    ).strip()

    if amenity == "hospital" or healthcare == "hospital":
        return "hospital", "hospital"

    if amenity in ("clinic", "doctors") or healthcare in ("clinic", "doctor"):
        return "health_center", (healthcare or amenity or "health_center")

    if amenity == "pharmacy" or healthcare == "pharmacy" or "farmacia" in text:
        return "pharmacy_first_aid", "pharmacy"

    fire_tokens = [
        "vigili del fuoco",
        "vvf",
        "v.v.f.",
        "corpo nazionale vigili del fuoco",
        "distaccamento",
        "presidio vigili del fuoco",
        "caserma vigili del fuoco",
    ]
    if amenity == "fire_station" or _contains_any(text, fire_tokens):
        if "comando" in text:
            sub = "comando_vvf"
        elif "distaccamento" in text:
            sub = "distaccamento_vvf"
        elif "presidio" in text:
            sub = "presidio_vvf"
        else:
            sub = "fire_station"
        return "fire_station", sub

    police_tokens = [
        "carabinieri",
        "arma dei carabinieri",
        "polizia",
        "polizia locale",
        "polizia municipale",
        "questura",
        "commissariato",
    ]
    if amenity == "police" or _contains_any(text, police_tokens):
        if "carabinieri" in text:
            sub = "carabinieri"
        elif "polizia locale" in text or "polizia municipale" in text:
            sub = "polizia_locale"
        else:
            sub = "police"
        return "police_carabinieri", sub

    cp_tokens = [
        "protezione civile",
        "centro operativo comunale",
        "coc",
        "centro operativo misto",
        "com",
        "centro operativo avanzato",
        "coa",
        "sala operativa",
    ]
    if (
        amenity == "emergency_service"
        or "disaster_response" in emergency
        or "civil_protection" in emergency
        or _contains_any(text, cp_tokens)
    ):
        return "civil_protection_center", "civil_protection_or_emergency_service"

    ambulance_tokens = [
        "118",
        "ambulanza",
        "croce rossa",
        "cri",
        "croce verde",
        "misericordia",
        "pubblica assistenza",
        "guardia medica",
        "punto di primo intervento",
    ]
    if emergency == "ambulance_station" or _contains_any(text, ambulance_tokens):
        return "ambulance_first_aid", "ambulance_or_first_aid"

    muni_tokens = [
        "comune di",
        "municipio",
        "sede comunale",
        "palazzo comunale",
        "ufficio comunale",
    ]
    if amenity == "townhall" or _contains_any(text, muni_tokens):
        return "municipality_coordination", "townhall_or_municipality"

    if office == "government":
        return "government_office", "government"

    return None


def geometry_to_point(geom: Any) -> Optional[arcpy.PointGeometry]:
    if geom is None:
        return None
    try:
        gtype = geom.type.lower()
    except Exception:
        gtype = ""
    sr = geom.spatialReference
    try:
        if gtype in ("point", "multipoint"):
            pt = geom.firstPoint if hasattr(geom, "firstPoint") else geom.centroid
            return arcpy.PointGeometry(pt, sr)
        centroid = getattr(geom, "trueCentroid", None) or getattr(geom, "centroid", None)
        if centroid is not None:
            return arcpy.PointGeometry(centroid, sr)
    except Exception:
        pass
    return None


def calculate_wgs84_lonlat(
    geom: Any,
) -> Tuple[Optional[float], Optional[float]]:
    if geom is None:
        return None, None
    try:
        wgs = arcpy.SpatialReference(4326)
        pt = geom.projectAs(wgs)
        if pt and pt.firstPoint:
            return float(pt.firstPoint.X), float(pt.firstPoint.Y)
    except Exception:
        pass
    return None, None


def load_roads() -> Tuple[Optional[str], List[Tuple[int, Any]]]:
    road_fc = ROAD_FC if arcpy.Exists(ROAD_FC) else FALLBACK_ROAD_FC
    if not arcpy.Exists(road_fc):
        print("  WARNING: No road FC found; nearest-road matching skipped.")
        return None, []
    oid_f = arcpy.Describe(road_fc).OIDFieldName
    roads: List[Tuple[int, Any]] = []
    with arcpy.da.SearchCursor(road_fc, [oid_f, "SHAPE@"]) as cur:
        for oid, shape in cur:
            if shape is not None:
                roads.append((int(oid), shape))
    print(f"  Loaded {len(roads)} road geometries from {os.path.basename(road_fc)}")
    return road_fc, roads


def find_nearest_road(
    point_geom: Any, roads: List[Tuple[int, Any]]
) -> Tuple[Optional[int], Optional[float]]:
    if point_geom is None or not roads:
        return None, None
    best_oid: Optional[int] = None
    best_dist: Optional[float] = None
    for oid, road_geom in roads:
        try:
            dist = point_geom.distanceTo(road_geom)
        except Exception:
            continue
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_oid = oid
    return best_oid, best_dist


def is_duplicate(
    fac: Dict[str, Any],
    kept: List[Dict[str, Any]],
    seen_osmids: set,
) -> Tuple[bool, str]:
    osmid = fac["SourceOSMID"]
    if osmid and osmid in seen_osmids:
        return True, "duplicate SourceOSMID"
    for prev in kept:
        if (
            prev["FacilityName"]
            and prev["FacilityName"] == fac["FacilityName"]
            and prev["FacilityType"] == fac["FacilityType"]
        ):
            try:
                d = fac["geometry"].distanceTo(prev["geometry"])
            except Exception:
                d = None
            if d is not None and d <= DUP_DIST_M:
                return True, f"same name+type within {DUP_DIST_M:.0f} m"
    return False, ""


def build_access_note(snap_dist: Optional[float]) -> str:
    if snap_dist is None:
        note = ACCESS_NOTE_BASE
    elif snap_dist <= SNAP_OK_M:
        note = ACCESS_NOTE_BASE + NOTE_SNAPPED
    else:
        note = ACCESS_NOTE_BASE + NOTE_FAR
    return truncate_text(note, 255)


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
                if col == "SnapDist_m":
                    fv = safe_float(val)
                    out[col] = f"{fv:.2f}" if fv is not None else ""
                else:
                    out[col] = safe_text(val)
            writer.writerow(out)
    print(f"  Wrote QA CSV: {QA_CSV}")


def add_output_to_map(aprx: arcpy.mp.ArcGISProject, out_fc: str, raw_layer: Any) -> None:
    raw_name = None
    try:
        raw_name = raw_layer.name if raw_layer is not None else None
    except Exception:
        raw_name = None

    for m in aprx.listMaps():
        for lyr in list(m.listLayers()):
            try:
                lname = lyr.name
            except Exception:
                continue
            remove = lname in OLD_LAYER_NAMES
            if CLEAR_RAW_FROM_MAP_ONLY and raw_name and lname == raw_name:
                remove = True
            if remove:
                try:
                    m.removeLayer(lyr)
                    print(f"  Removed old map layer: {lname}")
                except Exception:
                    pass

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
            _apply_facility_symbology(lyr)
    except Exception as ex:
        print(f"  WARNING: Could not add output layer to map: {ex}")


def _apply_facility_symbology(lyr: Any) -> None:
    try:
        sym = lyr.symbology
        if hasattr(sym, "updateRenderer"):
            sym.updateRenderer("UniqueValueRenderer")
            sym.renderer.fields = ["FacilityType"]
            lyr.symbology = sym
            print("  Applied unique-value symbology by FacilityType.")
            return
    except Exception:
        pass
    print("  Apply symbols manually by FacilityType.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 72)
    print("26_clean_emergency_service_centers.py")
    print("=" * 72)

    aprx = open_project()
    if aprx is None:
        return 1

    raw_layer = find_raw_layer(aprx)
    if raw_layer is None:
        print("  ERROR: Could not find the raw emergency-service import layer in any map.")
        print("  Looked for preferred names and 'emergency' + (JSONToFeatures/osm/services).")
        return 1

    raw_source_path = raw_layer
    desc = arcpy.Describe(raw_source_path)
    spatial_ref = desc.spatialReference

    raw_fields = [
        f.name for f in arcpy.ListFields(raw_source_path) if f.type not in SKIP_FIELD_TYPES
    ]
    oid_field = desc.OIDFieldName
    field_lower_map = {f.lower(): f for f in raw_fields}

    create_clean_output_fc(OUTPUT_FC, spatial_ref)
    road_fc, roads = load_roads()

    cursor_fields = [oid_field, "SHAPE@"] + raw_fields

    facilities: List[Dict[str, Any]] = []
    raw_count = 0
    skipped_non_emergency = 0

    with arcpy.da.SearchCursor(raw_source_path, cursor_fields) as cur:
        for row in cur:
            raw_count += 1
            rec = row_to_dict(row, cursor_fields)
            raw_oid = rec.get(oid_field)
            raw_geom = rec.get("SHAPE@")

            norm: Dict[str, str] = {}
            for fl, orig in field_lower_map.items():
                norm[fl] = safe_text(rec.get(orig))

            if is_non_emergency_candidate(norm):
                skipped_non_emergency += 1
                continue

            classification = classify_facility_type(norm)
            if classification is None:
                skipped_non_emergency += 1
                continue
            facility_type, facility_subtype = classification

            point_geom = geometry_to_point(raw_geom)
            if point_geom is None:
                skipped_non_emergency += 1
                continue

            facility_name = first_non_empty(norm, RAW_NAME_FIELDS)
            operator_name = norm.get("operator", "")
            municipality = first_non_empty(norm, RAW_MUNI_FIELDS)
            address = build_address(norm)
            phone = norm.get("phone", "")
            email = norm.get("email", "")
            website = norm.get("website", "")
            source_osmid = first_non_empty(norm, RAW_OSMID_FIELDS) or safe_text(raw_oid)

            near_oid, snap_dist = find_nearest_road(point_geom, roads)
            lon, lat = calculate_wgs84_lonlat(point_geom)
            access_note = build_access_note(snap_dist)

            facilities.append(
                {
                    "geometry": point_geom,
                    "raw_oid": raw_oid,
                    "FacilityName": facility_name,
                    "FacilityType": facility_type,
                    "FacilitySubtype": facility_subtype,
                    "OperatorName": operator_name,
                    "Municipality": municipality,
                    "Address": address,
                    "Phone": phone,
                    "Email": email,
                    "Website": website,
                    "Source": SOURCE_VALUE,
                    "SourceOSMID": source_osmid,
                    "VerificationStatus": VERIFICATION_VALUE,
                    "NearestRoadOID": near_oid,
                    "SnapDist_m": snap_dist,
                    "AccessStatus": ACCESS_STATUS_VALUE,
                    "AccessNote": access_note,
                    "LONG": lon,
                    "LAT": lat,
                }
            )

    print(f"  Raw features read: {raw_count}")
    print(f"  Skipped as non-emergency/shelter/unclassified: {skipped_non_emergency}")

    qa_rows: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    seen_osmids: set = set()
    n_dup = 0

    for fac in facilities:
        dup, reason = is_duplicate(fac, kept, seen_osmids)
        if dup:
            n_dup += 1
            qa_rows.append(
                {
                    "FacilityID": "",
                    "SourceOSMID": fac["SourceOSMID"],
                    "FacilityName": fac["FacilityName"],
                    "FacilityType": fac["FacilityType"],
                    "FacilitySubtype": fac["FacilitySubtype"],
                    "Municipality": fac["Municipality"],
                    "NearestRoadOID": fac["NearestRoadOID"],
                    "SnapDist_m": fac["SnapDist_m"],
                    "VerificationStatus": fac["VerificationStatus"],
                    "AccessStatus": fac["AccessStatus"],
                    "QA_Status": "duplicate_skipped",
                    "QA_Note": reason,
                }
            )
            continue
        if fac["SourceOSMID"]:
            seen_osmids.add(fac["SourceOSMID"])
        kept.append(fac)

    type_counter: Counter = Counter()
    n_far = 0
    facility_id = 0
    text_len = {n: l for n, t, l in OUTPUT_FIELD_SPECS if t == "TEXT"}

    with arcpy.da.InsertCursor(OUTPUT_FC, INSERT_FIELDS) as ic:
        for fac in kept:
            facility_id += 1
            fac["FacilityID"] = facility_id
            row_vals: List[Any] = [fac["geometry"]]
            for fname, _, _ in OUTPUT_FIELD_SPECS:
                val = fac.get(fname)
                if fname in text_len and isinstance(val, str):
                    val = truncate_text(val, text_len[fname])
                row_vals.append(val)
            ic.insertRow(row_vals)

            type_counter[fac["FacilityType"]] += 1
            far = fac["SnapDist_m"] is not None and fac["SnapDist_m"] > SNAP_OK_M
            if far:
                n_far += 1

            qa_rows.append(
                {
                    "FacilityID": facility_id,
                    "SourceOSMID": fac["SourceOSMID"],
                    "FacilityName": fac["FacilityName"],
                    "FacilityType": fac["FacilityType"],
                    "FacilitySubtype": fac["FacilitySubtype"],
                    "Municipality": fac["Municipality"],
                    "NearestRoadOID": fac["NearestRoadOID"],
                    "SnapDist_m": fac["SnapDist_m"],
                    "VerificationStatus": fac["VerificationStatus"],
                    "AccessStatus": fac["AccessStatus"],
                    "QA_Status": "kept",
                    "QA_Note": (
                        "Farther than 50 m from reference road; check manually."
                        if far
                        else "Snapped to nearby road."
                        if fac["SnapDist_m"] is not None
                        else "No reference road available."
                    ),
                }
            )

    write_qa_csv(qa_rows)
    add_output_to_map(aprx, OUTPUT_FC, raw_layer)

    final_count = int(arcpy.management.GetCount(OUTPUT_FC).getOutput(0))

    print("\n" + "=" * 72)
    print("QA SUMMARY — Emergency Service Centers")
    print("=" * 72)
    try:
        print(f"  Raw layer used:               {raw_layer.name}")
    except Exception:
        print("  Raw layer used:               (unavailable)")
    print(f"  Raw features read:            {raw_count}")
    print(f"  Output facilities created:    {final_count}")
    print(f"  Duplicates skipped:           {n_dup}")
    print(f"  Skipped non-emergency:        {skipped_non_emergency}")
    print(f"  Facilities with SnapDist>50m: {n_far}")
    if road_fc:
        print(f"  Reference road FC:            {os.path.basename(road_fc)}")
    print("  Count by FacilityType:")
    for ftype, cnt in sorted(type_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {ftype:<32} {cnt}")
    print(f"  Output feature class:         {OUTPUT_FC}")
    print(f"  QA CSV:                       {QA_CSV}")
    print("=" * 72 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())