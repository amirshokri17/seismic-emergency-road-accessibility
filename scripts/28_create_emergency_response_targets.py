# -*- coding: utf-8 -*-
"""
28_create_emergency_response_targets.py
---------------------------------------
Create a clean destination/target layer for first-emergency / search-and-rescue
accessibility analysis. Targets are the affected settlements and damage clusters
that emergency services must reach after the earthquake (Amatrice, Accumoli,
Illica, plus optional lower-priority affected communities).

This script does NOT perform routing; it only builds Emergency_Response_Targets
for the next network-accessibility script. It does not modify input layers.
"""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, List, Optional, Tuple

import arcpy

arcpy.env.overwriteOutput = True

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

APRX_PATH = os.environ.get("GPEM_APRX_PATH", "CURRENT")
MAIN_GDB = os.environ.get("GPEM_MAIN_GDB", r"C:\path\to\your_project.gdb")

COMMUNITY_FC = os.path.join(MAIN_GDB, "Community")
DAMAGE_POINTS_FC = os.path.join(MAIN_GDB, "Unified_Damage_Points_Final")
CONFIRMED_DAMAGE_SECTIONS_FC = os.path.join(
    MAIN_GDB, "Unified_Damage_RoadSections_Confirmed_Assessed"
)
VALIDATION_DAMAGE_SECTIONS_FC = os.path.join(
    MAIN_GDB, "Unified_Damage_RoadSections_NeedsValidation_Assessed"
)
ROAD_FC = os.path.join(MAIN_GDB, "Roads_Ideal_OSM_v2_full_clean")

OUTPUT_TARGETS_FC = os.path.join(MAIN_GDB, "Emergency_Response_Targets")
MANUAL_TARGETS_FC = os.path.join(MAIN_GDB, "Emergency_Response_Targets_ManualDigitizing")
QA_CSV = os.path.join(os.environ.get("GPEM_QA_DIR", "qa"), "Emergency_Response_Targets_QA.csv")

CLEAR_OUTPUT = os.environ.get("GPEM_CLEAR_OUTPUT", "false").strip().lower() in {"true", "1", "yes"}

# "PREPARE_MANUAL" -> create empty manual digitizing layer for the user to fill.
# "FINALIZE_MANUAL" -> build Emergency_Response_Targets from digitized points.
MODE = "FINALIZE_MANUAL"

OUTPUT_LAYER_NAME = "Emergency Response Targets"
MANUAL_LAYER_NAME = "Emergency Response Targets Manual Digitizing"
OLD_LAYER_NAMES = {
    "Emergency_Response_Targets",
    "Emergency Response Targets",
}

DAMAGE_PROXIMITY_M = 500.0
TARGET_STATUS_VALUE = "ready_for_accessibility_analysis"

CLUSTER_DIST_M = 700.0
MAX_CLUSTERS = 5

# Text fields searched for settlement-name hints on damage layers.
POINT_TEXT_FIELDS = [
    "COMUNE",
    "AreaName",
    "STRADA",
    "DmgNote",
    "Notes",
    "SourceDamageLayer",
    "DamageType",
]
SECTION_TEXT_FIELDS = [
    "RoadName",
    "ClassReason",
    "DamageType",
    "SourceDamageLayer",
    "Notes",
]

# Required high-priority targets (attributes filled at FINALIZE from these specs).
REQUIRED_TARGETS: List[Dict[str, Any]] = [
    {
        "TargetName": "Amatrice",
        "TargetType": "settlement_center",
        "PriorityLevel": 1,
        "DamageEvidence": "confirmed_damage_nearby",
        "Notes": "Primary affected settlement for first-emergency accessibility.",
    },
    {
        "TargetName": "Accumoli",
        "TargetType": "settlement_center",
        "PriorityLevel": 1,
        "DamageEvidence": "confirmed_damage_nearby",
        "Notes": "Primary affected settlement for first-emergency accessibility.",
    },
    {
        "TargetName": "Illica",
        "TargetType": "affected_community",
        "PriorityLevel": 1,
        "DamageEvidence": "confirmed_damage_nearby",
        "Notes": "Affected community / damage cluster for first-emergency accessibility.",
    },
]
REQUIRED_BY_NAME = {t["TargetName"].lower(): t for t in REQUIRED_TARGETS}
REQUIRED_NAMES = {t["TargetName"] for t in REQUIRED_TARGETS}

MANUAL_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("TargetName", "TEXT", 100),
    ("TargetType", "TEXT", 80),
    ("PriorityLevel", "SHORT", None),
    ("DamageEvidence", "TEXT", 120),
    ("TargetStatus", "TEXT", 80),
    ("Notes", "TEXT", 255),
]

# Lowercased token -> canonical target name.
NAME_TOKENS = {
    "amatrice": "Amatrice",
    "accumoli": "Accumoli",
    "illica": "Illica",
}

NAME_FIELD_CANDIDATES = [
    "name",
    "Name",
    "NAME",
    "comune",
    "COMUNE",
    "community",
    "Community",
    "localita",
    "LOCALITA",
    "frazione",
    "FRAZIONE",
]

OUTPUT_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("TargetID", "LONG", None),
    ("TargetName", "TEXT", 100),
    ("TargetType", "TEXT", 80),
    ("PriorityLevel", "SHORT", None),
    ("DamageEvidence", "TEXT", 120),
    ("NearestRoadOID", "LONG", None),
    ("SnapDist_m", "DOUBLE", None),
    ("TargetStatus", "TEXT", 80),
    ("Notes", "TEXT", 255),
]

INSERT_FIELDS = ["SHAPE@"] + [n for n, _, _ in OUTPUT_FIELD_SPECS]

QA_FIELDS = [
    "TargetID",
    "TargetName",
    "TargetType",
    "PriorityLevel",
    "DamageEvidence",
    "NearestRoadOID",
    "SnapDist_m",
    "TargetStatus",
    "QA_Status",
    "QA_Note",
]

SKIP_FIELD_TYPES = frozenset({"OID", "Geometry", "GlobalID", "GUID", "Raster", "Blob"})

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


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    s = safe_text(value)
    if not s:
        return default
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    s = safe_text(value)
    if not s:
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def truncate_text(value: str, max_len: Optional[int]) -> str:
    if max_len is None or max_len <= 0 or len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 3] + "..."


def field_exists(path: str, field_name: str) -> bool:
    try:
        return field_name.lower() in {f.name.lower() for f in arcpy.ListFields(path)}
    except Exception:
        return False


def get_oid_field(fc_path: str) -> str:
    return arcpy.Describe(fc_path).OIDFieldName


def detect_name_field(fc_path: str) -> Optional[str]:
    existing = {f.name.lower(): f.name for f in arcpy.ListFields(fc_path)}
    for cand in NAME_FIELD_CANDIDATES:
        if cand.lower() in existing:
            return existing[cand.lower()]
    return None


def normalize_target_name(raw_name: str) -> Optional[str]:
    n = raw_name.strip().lower()
    if not n:
        return None
    for token, canonical in NAME_TOKENS.items():
        if token in n:
            return canonical
    return None


def geometry_to_point(geom: Any) -> Optional[arcpy.PointGeometry]:
    if geom is None:
        return None
    sr = geom.spatialReference
    try:
        gtype = geom.type.lower()
    except Exception:
        gtype = ""
    try:
        if gtype in ("point", "multipoint"):
            pt = geom.firstPoint if hasattr(geom, "firstPoint") else geom.centroid
            return arcpy.PointGeometry(pt, sr)
        label = getattr(geom, "labelPoint", None)
        if label is not None:
            return arcpy.PointGeometry(label, sr)
        centroid = getattr(geom, "trueCentroid", None) or getattr(geom, "centroid", None)
        if centroid is not None:
            return arcpy.PointGeometry(centroid, sr)
    except Exception:
        pass
    return None


def project_geom(geom: Any, sr: arcpy.SpatialReference) -> Any:
    if geom is None or sr is None:
        return geom
    src = geom.spatialReference
    if src and src.factoryCode == sr.factoryCode:
        return geom
    try:
        return geom.projectAs(sr)
    except Exception:
        return geom


def load_roads(
    road_fc: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], arcpy.SpatialReference]:
    """Return (all_roads, emergency_usable_roads, spatial_ref)."""
    oid_f = get_oid_field(road_fc)
    sr = arcpy.Describe(road_fc).spatialReference
    has_eu = field_exists(road_fc, "EmergencyUsable")
    fields = [oid_f, "SHAPE@"]
    if has_eu:
        fields.append("EmergencyUsable")

    all_roads: List[Dict[str, Any]] = []
    usable_roads: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(road_fc, fields) as cur:
        for row in cur:
            rec = {fields[i]: row[i] for i in range(len(fields))}
            shape = rec.get("SHAPE@")
            if shape is None:
                continue
            entry = {"oid": safe_int(rec.get(oid_f)), "geom": shape}
            all_roads.append(entry)
            if has_eu and safe_int(rec.get("EmergencyUsable")) == 1:
                usable_roads.append(entry)
    print(
        f"  Loaded {len(all_roads)} roads "
        f"({len(usable_roads)} EmergencyUsable=1) from {os.path.basename(road_fc)}"
    )
    return all_roads, usable_roads, sr


def find_nearest_road(
    pt_geom: Any,
    roads: List[Dict[str, Any]],
    sr: arcpy.SpatialReference,
) -> Tuple[Optional[int], Optional[float]]:
    if pt_geom is None or not roads:
        return None, None
    pt = project_geom(pt_geom, sr)
    best_oid: Optional[int] = None
    best_dist: Optional[float] = None
    for rec in roads:
        try:
            d = pt.distanceTo(project_geom(rec["geom"], sr))
        except Exception:
            continue
        if best_dist is None or d < best_dist:
            best_dist = d
            best_oid = rec["oid"]
    return best_oid, best_dist


def snap_target_to_road(
    pt_geom: Any,
    usable_roads: List[Dict[str, Any]],
    all_roads: List[Dict[str, Any]],
    sr: arcpy.SpatialReference,
) -> Tuple[Optional[int], Optional[float], str]:
    """Prefer EmergencyUsable=1 roads; fall back to any road with a warning note."""
    if usable_roads:
        oid, dist = find_nearest_road(pt_geom, usable_roads, sr)
        if oid is not None:
            return oid, dist, ""
    oid, dist = find_nearest_road(pt_geom, all_roads, sr)
    if oid is not None:
        return oid, dist, "No EmergencyUsable road nearby; snapped to nearest road of any type."
    return None, None, "No road available for snapping."


def load_damage_geometries() -> Dict[str, List[Any]]:
    """Load confirmed/validation section geometries and damage points for proximity."""
    out: Dict[str, List[Any]] = {"confirmed": [], "validation": [], "points": []}
    for key, fc in (
        ("confirmed", CONFIRMED_DAMAGE_SECTIONS_FC),
        ("validation", VALIDATION_DAMAGE_SECTIONS_FC),
        ("points", DAMAGE_POINTS_FC),
    ):
        if not arcpy.Exists(fc):
            print(f"  WARNING: damage layer not found (proximity skipped): {fc}")
            continue
        with arcpy.da.SearchCursor(fc, ["SHAPE@"]) as cur:
            for (shape,) in cur:
                if shape is not None:
                    out[key].append(shape)
        print(f"  Loaded {len(out[key])} {key} geometries.")
    return out


def min_distance_to(
    pt_geom: Any, geoms: List[Any], sr: arcpy.SpatialReference
) -> Optional[float]:
    if pt_geom is None or not geoms:
        return None
    pt = project_geom(pt_geom, sr)
    best: Optional[float] = None
    for g in geoms:
        try:
            d = pt.distanceTo(project_geom(g, sr))
        except Exception:
            continue
        if best is None or d < best:
            best = d
    return best


def mean_center(geoms: List[Any], sr: arcpy.SpatialReference) -> Optional[arcpy.PointGeometry]:
    """Mean center of a list of geometries (each reduced to a representative point)."""
    xs: List[float] = []
    ys: List[float] = []
    for g in geoms:
        pt = geometry_to_point(g)
        if pt is None:
            continue
        pt = project_geom(pt, sr)
        try:
            xs.append(float(pt.firstPoint.X))
            ys.append(float(pt.firstPoint.Y))
        except Exception:
            continue
    if not xs:
        return None
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    return arcpy.PointGeometry(arcpy.Point(cx, cy), sr)


def load_damage_text_records(
    fc_path: str, text_fields: List[str]
) -> List[Dict[str, Any]]:
    """Return [{geom, text}] for a damage layer, combining available text fields."""
    if not arcpy.Exists(fc_path):
        return []
    present = [fn for fn in text_fields if field_exists(fc_path, fn)]
    fields = ["SHAPE@"] + present
    records: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(fc_path, fields) as cur:
        for row in cur:
            rec = {fields[i]: row[i] for i in range(len(fields))}
            shape = rec.get("SHAPE@")
            if shape is None:
                continue
            combined = " ".join(safe_text(rec.get(fn)) for fn in present).lower()
            records.append({"geom": shape, "text": combined})
    return records


def match_geoms_by_token(records: List[Dict[str, Any]], token: str) -> List[Any]:
    tok = token.lower()
    return [r["geom"] for r in records if tok in r["text"]]


def cluster_geometries(
    geoms: List[Any],
    sr: arcpy.SpatialReference,
    dist_m: float,
    max_clusters: int,
) -> List[Tuple[arcpy.PointGeometry, int]]:
    """Greedy distance-threshold clustering. Returns [(centroid, member_count)]."""
    pts: List[arcpy.PointGeometry] = []
    for g in geoms:
        pt = geometry_to_point(g)
        if pt is not None:
            pts.append(project_geom(pt, sr))

    clusters: List[Dict[str, Any]] = []
    for p in pts:
        placed = False
        for c in clusters:
            try:
                if p.distanceTo(c["center"]) <= dist_m:
                    c["members"].append(p)
                    c["center"] = mean_center(c["members"], sr) or c["center"]
                    placed = True
                    break
            except Exception:
                continue
        if not placed:
            clusters.append({"center": p, "members": [p]})

    clusters.sort(key=lambda c: len(c["members"]), reverse=True)
    return [(c["center"], len(c["members"])) for c in clusters[:max_clusters]]


def create_output_fc(out_fc: str, sr: arcpy.SpatialReference) -> None:
    if arcpy.Exists(out_fc):
        if CLEAR_OUTPUT:
            arcpy.management.Delete(out_fc)
        else:
            raise RuntimeError(f"Output exists and CLEAR_OUTPUT is False: {out_fc}")
    gdb, name = os.path.split(out_fc)
    arcpy.management.CreateFeatureclass(gdb, name, "POINT", spatial_reference=sr)
    for fname, ftype, flen in OUTPUT_FIELD_SPECS:
        if ftype == "TEXT":
            arcpy.management.AddField(out_fc, fname, ftype, field_length=flen or 255)
        else:
            arcpy.management.AddField(out_fc, fname, ftype)
    print(f"  Created output FC: {out_fc}")


def insert_target(cursor: Any, target: Dict[str, Any]) -> None:
    text_len = {n: l for n, t, l in OUTPUT_FIELD_SPECS if t == "TEXT"}
    row_vals: List[Any] = [target["geometry"]]
    for fname, _, _ in OUTPUT_FIELD_SPECS:
        val = target.get(fname)
        if fname in text_len and isinstance(val, str):
            val = truncate_text(val, text_len[fname])
        row_vals.append(val)
    cursor.insertRow(row_vals)


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


def open_project() -> Optional[arcpy.mp.ArcGISProject]:
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        return aprx
    except Exception:
        pass
    try:
        return arcpy.mp.ArcGISProject(APRX_PATH)
    except Exception as ex:
        print(f"  WARNING: Could not open project: {ex}")
        return None


def add_output_to_map(out_fc: str) -> None:
    aprx = open_project()
    if aprx is None:
        return
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
            _apply_priority_symbology(lyr)
    except Exception as ex:
        print(f"  WARNING: Could not add output layer to map: {ex}")


def _apply_priority_symbology(lyr: Any) -> None:
    try:
        sym = lyr.symbology
        if hasattr(sym, "updateRenderer"):
            sym.updateRenderer("UniqueValueRenderer")
            sym.renderer.fields = ["PriorityLevel"]
            lyr.symbology = sym
            print("  Applied unique-value symbology by PriorityLevel.")
            return
    except Exception:
        pass
    print("Symbolize manually by PriorityLevel.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def create_manual_fc(manual_fc: str, sr: arcpy.SpatialReference) -> None:
    if arcpy.Exists(manual_fc):
        if CLEAR_OUTPUT:
            arcpy.management.Delete(manual_fc)
        else:
            print(f"  Manual layer already exists (kept): {manual_fc}")
            return
    gdb, name = os.path.split(manual_fc)
    arcpy.management.CreateFeatureclass(gdb, name, "POINT", spatial_reference=sr)
    for fname, ftype, flen in MANUAL_FIELD_SPECS:
        if ftype == "TEXT":
            arcpy.management.AddField(manual_fc, fname, ftype, field_length=flen or 255)
        else:
            arcpy.management.AddField(manual_fc, fname, ftype)
    print(f"  Created empty manual digitizing FC: {manual_fc}")


def add_manual_to_map(manual_fc: str) -> None:
    aprx = open_project()
    if aprx is None:
        return
    for m in aprx.listMaps():
        for lyr in list(m.listLayers()):
            try:
                if lyr.name == MANUAL_LAYER_NAME:
                    m.removeLayer(lyr)
            except Exception:
                continue
    try:
        m = aprx.activeMap if aprx.activeMap else aprx.listMaps()[0]
    except Exception:
        print("  WARNING: No map available to add manual layer.")
        return
    try:
        lyr = m.addDataFromPath(manual_fc)
        if lyr:
            lyr.name = MANUAL_LAYER_NAME
            print(f"  Added manual layer to map: {MANUAL_LAYER_NAME}")
    except Exception as ex:
        print(f"  WARNING: Could not add manual layer to map: {ex}")


def prepare_manual() -> int:
    if not arcpy.Exists(ROAD_FC):
        print(f"ERROR: Road network not found: {ROAD_FC}")
        return 1
    road_sr = arcpy.Describe(ROAD_FC).spatialReference

    create_manual_fc(MANUAL_TARGETS_FC, road_sr)
    add_manual_to_map(MANUAL_TARGETS_FC)

    print("\n" + "=" * 72)
    print("PREPARE_MANUAL — digitizing instructions")
    print("=" * 72)
    print("  1. Manually digitize ONE point for Amatrice, Accumoli, and Illica.")
    print("  2. Place each point on/near the main road access focus or settlement center.")
    print("  3. Fill TargetName exactly: Amatrice, Accumoli, Illica.")
    print("  4. Fill TargetType / PriorityLevel if desired; otherwise FINALIZE_MANUAL")
    print("     will fill them from REQUIRED_TARGETS.")
    print("  5. Save edits.")
    print('  6. Rerun this script with MODE = "FINALIZE_MANUAL".')
    print(f"  Manual layer: {MANUAL_TARGETS_FC}")
    print("=" * 72 + "\n")
    return 0


def finalize_manual() -> int:
    if not arcpy.Exists(ROAD_FC):
        print(f"ERROR: Road network not found: {ROAD_FC}")
        return 1
    if not arcpy.Exists(MANUAL_TARGETS_FC):
        print(f"ERROR: Manual digitizing layer not found: {MANUAL_TARGETS_FC}")
        print('  Run MODE = "PREPARE_MANUAL" first, then digitize the targets.')
        return 1

    manual_count = int(arcpy.management.GetCount(MANUAL_TARGETS_FC).getOutput(0))
    if manual_count == 0:
        print("ERROR: Manual digitizing layer has no points. Digitize targets first.")
        return 1

    all_roads, usable_roads, road_sr = load_roads(ROAD_FC)
    if not all_roads:
        print("ERROR: Road network is empty.")
        return 1

    # Read manually digitized points.
    manual_fields = ["SHAPE@"] + [
        n for n, _, _ in MANUAL_FIELD_SPECS if field_exists(MANUAL_TARGETS_FC, n)
    ]
    manual_points: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(MANUAL_TARGETS_FC, manual_fields) as cur:
        for row in cur:
            rec = {manual_fields[i]: row[i] for i in range(len(manual_fields))}
            geom = rec.get("SHAPE@")
            if geom is None:
                continue
            manual_points.append(rec)
    manual_read = len(manual_points)
    print(f"  Manual targets read: {manual_read}")

    targets: List[Dict[str, Any]] = []
    qa_rows: List[Dict[str, Any]] = []
    used_names: set = set()
    required_present: List[str] = []

    for rec in manual_points:
        geom = rec.get("SHAPE@")
        raw_name = safe_text(rec.get("TargetName"))
        spec = REQUIRED_BY_NAME.get(raw_name.lower())

        if spec is not None:
            tname = spec["TargetName"]
            if tname in used_names:
                continue  # one target per unique required name
            targets.append(
                {
                    "geometry": geom,
                    "TargetName": tname,
                    "TargetType": spec["TargetType"],
                    "PriorityLevel": spec["PriorityLevel"],
                    "DamageEvidence": spec["DamageEvidence"],
                    "Notes": spec["Notes"],
                }
            )
            used_names.add(tname)
            required_present.append(tname)
        else:
            # Optional extra manually digitized target.
            name = raw_name if raw_name else f"Manual Target {len(targets) + 1}"
            if name in used_names:
                continue
            prio = safe_int(rec.get("PriorityLevel"), 2) or 2
            man_notes = safe_text(rec.get("Notes"))
            targets.append(
                {
                    "geometry": geom,
                    "TargetName": name,
                    "TargetType": "additional_response_target",
                    "PriorityLevel": prio,
                    "DamageEvidence": "manual_target",
                    "Notes": man_notes or "Additional manually digitized response target.",
                }
            )
            used_names.add(name)

    skipped_required = [n for n in REQUIRED_NAMES if n not in used_names]
    for tname in skipped_required:
        spec = REQUIRED_BY_NAME[tname.lower()]
        qa_rows.append(
            {
                "TargetID": "",
                "TargetName": tname,
                "TargetType": spec["TargetType"],
                "PriorityLevel": spec["PriorityLevel"],
                "DamageEvidence": spec["DamageEvidence"],
                "NearestRoadOID": "",
                "SnapDist_m": "",
                "TargetStatus": "",
                "QA_Status": "skipped_required_target",
                "QA_Note": "Not digitized in manual layer; coordinates not invented.",
            }
        )
        print(f"  WARNING: required target missing (not digitized): {tname}")

    # --- Create output and insert with snapping ---
    create_output_fc(OUTPUT_TARGETS_FC, road_sr)

    n_snapped = 0
    max_snap: Optional[float] = None
    target_id = 0
    target_names_created: List[str] = []

    with arcpy.da.InsertCursor(OUTPUT_TARGETS_FC, INSERT_FIELDS) as ic:
        for tgt in targets:
            target_id += 1
            road_oid, snap_dist, snap_note = snap_target_to_road(
                tgt["geometry"], usable_roads, all_roads, road_sr
            )
            notes = tgt.get("Notes", "")
            if snap_note:
                notes = (notes + " " + snap_note).strip()

            if road_oid is not None:
                n_snapped += 1
                if snap_dist is not None and (max_snap is None or snap_dist > max_snap):
                    max_snap = snap_dist

            record = {
                "geometry": tgt["geometry"],
                "TargetID": target_id,
                "TargetName": tgt["TargetName"],
                "TargetType": tgt["TargetType"],
                "PriorityLevel": tgt["PriorityLevel"],
                "DamageEvidence": tgt["DamageEvidence"],
                "NearestRoadOID": road_oid,
                "SnapDist_m": round(snap_dist, 3) if snap_dist is not None else None,
                "TargetStatus": TARGET_STATUS_VALUE,
                "Notes": notes,
            }
            insert_target(ic, record)
            target_names_created.append(tgt["TargetName"])

            qa_rows.append(
                {
                    "TargetID": target_id,
                    "TargetName": tgt["TargetName"],
                    "TargetType": tgt["TargetType"],
                    "PriorityLevel": tgt["PriorityLevel"],
                    "DamageEvidence": tgt["DamageEvidence"],
                    "NearestRoadOID": road_oid if road_oid is not None else "",
                    "SnapDist_m": snap_dist,
                    "TargetStatus": TARGET_STATUS_VALUE,
                    "QA_Status": "created",
                    "QA_Note": notes,
                }
            )

    write_qa_csv(qa_rows)
    add_output_to_map(OUTPUT_TARGETS_FC)

    final_count = int(arcpy.management.GetCount(OUTPUT_TARGETS_FC).getOutput(0))

    present_names = [n for n in REQUIRED_NAMES if n in used_names]

    print("\n" + "=" * 72)
    print("QA SUMMARY — Emergency Response Targets (FINALIZE_MANUAL)")
    print("=" * 72)
    print(f"  Manual digitizing layer:      {MANUAL_TARGETS_FC}")
    print(f"  Road network:                 {ROAD_FC}")
    print(f"  Output target layer:          {OUTPUT_TARGETS_FC}")
    print(f"  Manual targets read:          {manual_read}")
    print(f"  Final targets created:        {final_count}")
    print(f"  Target names created:         {', '.join(target_names_created) or '(none)'}")
    print(f"  Required targets present:     {', '.join(present_names) or '(none)'}")
    if skipped_required:
        print(f"  Required targets missing:     {', '.join(skipped_required)}")
    else:
        print("  Required targets missing:     none")
    if max_snap is not None:
        print(f"  Maximum SnapDist_m:           {max_snap:.3f}")
    print(f"  QA CSV:                       {QA_CSV}")
    print()
    print("  Methodological note:")
    print("    Emergency_Response_Targets defines the demand points for first-emergency")
    print("    accessibility analysis. These targets represent affected settlements or")
    print("    damage clusters that emergency services must reach during the search-and-")
    print("    rescue and evacuation phase.")
    print("=" * 72 + "\n")
    return 0


def main() -> int:
    print("=" * 72)
    print("28_create_emergency_response_targets.py")
    print(f"MODE = {MODE}")
    print("=" * 72)

    if MODE == "PREPARE_MANUAL":
        return prepare_manual()
    if MODE == "FINALIZE_MANUAL":
        return finalize_manual()

    print(f"ERROR: Unknown MODE '{MODE}'. Use 'PREPARE_MANUAL' or 'FINALIZE_MANUAL'.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
