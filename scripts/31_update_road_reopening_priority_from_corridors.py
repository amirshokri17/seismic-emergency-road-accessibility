# -*- coding: utf-8 -*-
"""
31_update_road_reopening_priority_from_corridors.py
---------------------------------------------------
Rebuild Emergency_Road_Reopening_Priority from the final
Emergency_Response_Corridor_Network (not from full route outputs).

Only confirmed damaged sections that intersect/are within 5 m of selected
emergency corridor segments are included. Validation-needed sections are not
inserted as confirmed priorities, but can be flagged as nearby uncertainty.
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

import arcpy

arcpy.env.overwriteOutput = True

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

APRX_PATH = os.environ.get("GPEM_APRX_PATH", "CURRENT")
MAIN_GDB = os.environ.get("GPEM_MAIN_GDB", r"C:\path\to\your_project.gdb")

CORRIDOR_FC = os.path.join(MAIN_GDB, "Emergency_Response_Corridor_Network")
CONFIRMED_DAMAGE_ML_FC = os.path.join(
    MAIN_GDB, "Unified_Damage_RoadSections_Confirmed_Assessed"
)
CONFIRMED_DAMAGE_PROF_FC = os.path.join(MAIN_GDB, "Roads_Damage_FromTableOnly")
VALIDATION_DAMAGE_FC = os.path.join(
    MAIN_GDB, "Unified_Damage_RoadSections_NeedsValidation_Assessed"
)

OUTPUT_PRIORITY_FC = os.path.join(MAIN_GDB, "Emergency_Road_Reopening_Priority")
QA_CSV = os.path.join(os.environ.get("GPEM_QA_DIR", "qa"), "Emergency_Road_Reopening_Priority_QA.csv")

CLEAR_OUTPUT = os.environ.get("GPEM_CLEAR_OUTPUT", "false").strip().lower() in {"true", "1", "yes"}

WORKING_SR = arcpy.SpatialReference(3065)
DAMAGE_TOUCH_M = 5.0
DEFAULT_PROF_CLASS = 2

OUTPUT_LAYER_NAME = "Emergency Road Reopening Priority"
OLD_LAYER_NAMES = {
    "Emergency Road Reopening Priority",
    "Emergency_Road_Reopening_Priority",
    "Emergency_Road_Reopening_Priority_1",
    "Emergency_Road_Reopening_Priority_2",
}

OUTPUT_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("PriorityID", "LONG", None),
    ("SourceDamageLayer", "TEXT", 100),
    ("SourceDamageOID", "LONG", None),
    ("DamageClass", "SHORT", None),
    ("RoadName", "TEXT", 150),
    ("RoadType", "TEXT", 80),
    ("AvailableWidth_m", "DOUBLE", None),
    ("TargetsAffected", "TEXT", 255),
    ("ServiceGroupsAffected", "TEXT", 255),
    ("UsedByRouteCount", "LONG", None),
    ("PrimaryRouteUseCount", "LONG", None),
    ("CriticalRouteCount", "LONG", None),
    ("CorridorSegmentCount", "LONG", None),
    ("PriorityLevel", "SHORT", None),
    ("PriorityReason", "TEXT", 255),
    ("ValidationNearby", "SHORT", None),
]

QA_FIELDS = [
    "PriorityID",
    "SourceDamageLayer",
    "SourceDamageOID",
    "DamageClass",
    "RoadName",
    "RoadType",
    "AvailableWidth_m",
    "TargetsAffected",
    "ServiceGroupsAffected",
    "UsedByRouteCount",
    "PrimaryRouteUseCount",
    "CriticalRouteCount",
    "CorridorSegmentCount",
    "PriorityLevel",
    "ValidationNearby",
    "QA_Status",
    "QA_Note",
]

DMG_CLASS_FIELDS = ["DamageClass", "DmgClass_Pre", "DmgClass", "Class", "DamageClass_Pre"]
DMG_AVAIL_FIELDS = ["AvailableWidth_m", "AvailWidth_m", "UsableWidth_m"]
DMG_NAME_FIELDS = ["RoadName", "name", "NAME", "STRADA"]
DMG_TYPE_FIELDS = ["RoadType", "highway", "fclass", "type"]


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


def pick_field(fc_path: str, candidates: List[str]) -> Optional[str]:
    existing = {f.name.lower(): f.name for f in arcpy.ListFields(fc_path)}
    for c in candidates:
        if c.lower() in existing:
            return existing[c.lower()]
    return None


def get_oid_field(fc_path: str) -> str:
    return arcpy.Describe(fc_path).OIDFieldName


def project_geom(g: Any) -> Any:
    if g is None:
        return None
    try:
        src = g.spatialReference
        if src and src.factoryCode == WORKING_SR.factoryCode:
            return g
        return g.projectAs(WORKING_SR)
    except Exception:
        return g


def load_corridors(corridor_fc: str) -> List[Dict[str, Any]]:
    if not arcpy.Exists(corridor_fc):
        return []
    oid_f = get_oid_field(corridor_fc)
    fields = [
        oid_f,
        "SHAPE@",
        "CorridorID",
        "SourceRoadOID",
        "RoadName",
        "RoadType",
        "RoadGroup",
        "EmergencyUsable",
        "TargetsServed",
        "ServiceGroupsServed",
        "RouteUseCount",
        "PrimaryRouteUseCount",
        "CriticalRouteUseCount",
        "RouteDamageClass",
        "ValidationFlag",
        "MinAvailableWidth_m",
        "EmergencyAccessClass",
        "ReopeningPriorityLevel",
    ]
    sections: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(corridor_fc, fields) as cur:
        for row in cur:
            rec = {fields[i]: row[i] for i in range(len(fields))}
            geom = project_geom(rec.get("SHAPE@"))
            if geom is None or geom.length <= 0:
                continue
            sections.append(
                {
                    "oid": safe_int(rec.get(oid_f)),
                    "geom": geom,
                    "extent": geom.extent,
                    "CorridorID": safe_int(rec.get("CorridorID")),
                    "SourceRoadOID": safe_int(rec.get("SourceRoadOID")),
                    "RoadName": safe_text(rec.get("RoadName")),
                    "RoadType": safe_text(rec.get("RoadType")),
                    "RoadGroup": safe_text(rec.get("RoadGroup")),
                    "EmergencyUsable": safe_int(rec.get("EmergencyUsable"), 1),
                    "TargetsServed": safe_text(rec.get("TargetsServed")),
                    "ServiceGroupsServed": safe_text(rec.get("ServiceGroupsServed")),
                    "RouteUseCount": safe_int(rec.get("RouteUseCount"), 0) or 0,
                    "PrimaryRouteUseCount": safe_int(rec.get("PrimaryRouteUseCount"), 0) or 0,
                    "CriticalRouteUseCount": safe_int(rec.get("CriticalRouteUseCount"), 0) or 0,
                    "RouteDamageClass": safe_int(rec.get("RouteDamageClass"), 0) or 0,
                    "ValidationFlag": safe_int(rec.get("ValidationFlag"), 0) or 0,
                    "MinAvailableWidth_m": safe_float(rec.get("MinAvailableWidth_m")),
                    "EmergencyAccessClass": safe_text(rec.get("EmergencyAccessClass")),
                    "ReopeningPriorityLevel": safe_int(rec.get("ReopeningPriorityLevel"), 0) or 0,
                }
            )
    return sections


def load_confirmed_damage(fc_path: str, source_label: str) -> Tuple[List[Dict[str, Any]], bool]:
    if not arcpy.Exists(fc_path):
        return [], False
    oid_f = get_oid_field(fc_path)
    f_class = pick_field(fc_path, DMG_CLASS_FIELDS)
    f_avail = pick_field(fc_path, DMG_AVAIL_FIELDS)
    f_name = pick_field(fc_path, DMG_NAME_FIELDS)
    f_type = pick_field(fc_path, DMG_TYPE_FIELDS)
    used_default_class = False

    fields = [oid_f, "SHAPE@"]
    for f in (f_class, f_avail, f_name, f_type):
        if f and f not in fields:
            fields.append(f)

    rows: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(fc_path, fields) as cur:
        for row in cur:
            rec = {fields[i]: row[i] for i in range(len(fields))}
            geom = project_geom(rec.get("SHAPE@"))
            if geom is None or geom.length <= 0:
                continue
            dclass = safe_int(rec.get(f_class), None) if f_class else None
            if dclass is None:
                dclass = DEFAULT_PROF_CLASS
                if source_label == "Professor_confirmed":
                    used_default_class = True
            rows.append(
                {
                    "SourceDamageLayer": source_label,
                    "SourceDamageOID": safe_int(rec.get(oid_f)),
                    "geom": geom,
                    "extent": geom.extent,
                    "DamageClass": dclass,
                    "AvailableWidth_m": safe_float(rec.get(f_avail)) if f_avail else None,
                    "RoadName": safe_text(rec.get(f_name)) if f_name else "",
                    "RoadType": safe_text(rec.get(f_type)) if f_type else "",
                }
            )
    return rows, used_default_class


def load_validation_damage(fc_path: str) -> List[Dict[str, Any]]:
    if not arcpy.Exists(fc_path):
        return []
    rows: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(fc_path, ["SHAPE@"]) as cur:
        for (geom_raw,) in cur:
            geom = project_geom(geom_raw)
            if geom is None or geom.length <= 0:
                continue
            rows.append({"geom": geom, "extent": geom.extent})
    return rows


def match_corridors_to_damage(
    damage_geom: Any,
    damage_ext: Any,
    corridors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for c in corridors:
        ext = c["extent"]
        if (
            damage_ext.XMax + DAMAGE_TOUCH_M < ext.XMin
            or damage_ext.XMin - DAMAGE_TOUCH_M > ext.XMax
            or damage_ext.YMax + DAMAGE_TOUCH_M < ext.YMin
            or damage_ext.YMin - DAMAGE_TOUCH_M > ext.YMax
        ):
            continue
        try:
            if damage_geom.distanceTo(c["geom"]) <= DAMAGE_TOUCH_M:
                matched.append(c)
        except Exception:
            continue
    return matched


def derive_priority(
    damage_class: int,
    avail_w: Optional[float],
    max_crit_routes: int,
    max_primary_routes: int,
    matched_corridors: List[Dict[str, Any]],
) -> Tuple[int, str]:
    has_critical_access = any(
        c["EmergencyAccessClass"] == "critical_or_blocked" for c in matched_corridors
    )
    has_restricted_access = any(
        c["EmergencyAccessClass"] == "restricted" for c in matched_corridors
    )

    if (
        damage_class == 3
        or has_critical_access
        or max_crit_routes > 0
        or (avail_w is not None and avail_w < 2.5)
    ):
        return 1, "Priority 1: critical corridor bottleneck for emergency access."

    if (
        damage_class == 2
        or has_restricted_access
        or (max_primary_routes > 0 and damage_class >= 2)
        or (avail_w is not None and avail_w < 4.5)
    ):
        return 2, "Priority 2: restricted corridor segment affecting selected emergency access."

    return 3, "Priority 3: lower-impact damage on selected emergency corridor."


def create_output_fc(path: str) -> None:
    if arcpy.Exists(path):
        if CLEAR_OUTPUT:
            arcpy.management.Delete(path)
        else:
            raise RuntimeError(f"Output exists and CLEAR_OUTPUT is False: {path}")
    gdb, name = os.path.split(path)
    arcpy.management.CreateFeatureclass(gdb, name, "POLYLINE", spatial_reference=WORKING_SR)
    for fname, ftype, flen in OUTPUT_FIELD_SPECS:
        if ftype == "TEXT":
            arcpy.management.AddField(path, fname, ftype, field_length=flen or 255)
        else:
            arcpy.management.AddField(path, fname, ftype)


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
                v = row.get(col, "")
                if col == "AvailableWidth_m":
                    fv = safe_float(v)
                    out[col] = f"{fv:.3f}" if fv is not None else ""
                else:
                    out[col] = safe_text(v)
            writer.writerow(out)
    print(f"  Wrote QA CSV: {QA_CSV}")


def open_project() -> Optional[Any]:
    try:
        return arcpy.mp.ArcGISProject("CURRENT")
    except Exception:
        pass
    try:
        return arcpy.mp.ArcGISProject(APRX_PATH)
    except Exception as ex:
        print(f"  WARNING: Could not open project: {ex}")
        return None


def update_map() -> None:
    aprx = open_project()
    if aprx is None:
        return
    for m in aprx.listMaps():
        for lyr in list(m.listLayers()):
            try:
                if lyr.name in OLD_LAYER_NAMES:
                    m.removeLayer(lyr)
            except Exception:
                continue
    try:
        m = aprx.activeMap if aprx.activeMap else aprx.listMaps()[0]
    except Exception:
        print("  WARNING: No map available to add output layer.")
        return
    if not arcpy.Exists(OUTPUT_PRIORITY_FC):
        return
    try:
        lyr = m.addDataFromPath(OUTPUT_PRIORITY_FC)
        if lyr:
            lyr.name = OUTPUT_LAYER_NAME
    except Exception as ex:
        print(f"  WARNING: could not add output layer: {ex}")
        return
    ok = True
    try:
        sym = lyr.symbology
        if hasattr(sym, "updateRenderer"):
            sym.updateRenderer("UniqueValueRenderer")
            sym.renderer.fields = ["PriorityLevel"]
            colors = {"1": [220, 0, 0, 100], "2": [255, 140, 0, 100], "3": [255, 220, 0, 100]}
            for grp in sym.renderer.groups:
                for itm in grp.items:
                    val = str(itm.values[0][0])
                    rgb = colors.get(val)
                    if rgb:
                        itm.symbol.color = {"RGB": rgb}
            lyr.symbology = sym
        else:
            ok = False
    except Exception:
        ok = False
    if not ok:
        print("Symbolize Emergency Road Reopening Priority manually by PriorityLevel.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 72)
    print("31_update_road_reopening_priority_from_corridors.py")
    print("=" * 72)

    if not arcpy.Exists(CORRIDOR_FC):
        print(f"ERROR: Corridor layer not found: {CORRIDOR_FC}")
        return 1

    print("Loading corridor network...")
    corridors = load_corridors(CORRIDOR_FC)
    print(f"  Corridor segments loaded: {len(corridors)}")
    if not corridors:
        print("ERROR: No corridor segments loaded.")
        return 1

    print("Loading confirmed damage sections...")
    ml_damage, ml_default = load_confirmed_damage(CONFIRMED_DAMAGE_ML_FC, "ML_confirmed")
    prof_damage, prof_default = load_confirmed_damage(
        CONFIRMED_DAMAGE_PROF_FC, "Professor_confirmed"
    )
    print(f"  Confirmed ML damage sections loaded: {len(ml_damage)}")
    print(f"  Professor damage sections loaded:    {len(prof_damage)}")

    validation = load_validation_damage(VALIDATION_DAMAGE_FC)
    print(f"  Validation sections loaded:          {len(validation)}")

    damage_rows = ml_damage + prof_damage

    create_output_fc(OUTPUT_PRIORITY_FC)
    out_fields = [n for n, _, _ in OUTPUT_FIELD_SPECS]
    out_text_len = {n: l for n, t, l in OUTPUT_FIELD_SPECS if t == "TEXT"}

    created = 0
    skipped_not_on_corridor = 0
    validation_nearby_count = 0
    priority_counter: Counter = Counter()
    source_counter: Counter = Counter()
    qa_rows: List[Dict[str, Any]] = []

    priority_id = 0
    with arcpy.da.InsertCursor(OUTPUT_PRIORITY_FC, ["SHAPE@"] + out_fields) as ic:
        for dmg in damage_rows:
            matched = match_corridors_to_damage(dmg["geom"], dmg["extent"], corridors)
            if not matched:
                skipped_not_on_corridor += 1
                continue

            # Aggregate corridor usage/significance.
            targets_set: Set[str] = set()
            groups_set: Set[str] = set()
            route_use_max = 0
            primary_use_max = 0
            critical_use_max = 0
            min_corridor_avail: Optional[float] = None
            for c in matched:
                t = safe_text(c.get("TargetsServed"))
                if t:
                    for x in [p.strip() for p in t.split(",") if p.strip()]:
                        targets_set.add(x)
                g = safe_text(c.get("ServiceGroupsServed"))
                if g:
                    for x in [p.strip() for p in g.split(",") if p.strip()]:
                        groups_set.add(x)
                route_use_max = max(route_use_max, c["RouteUseCount"])
                primary_use_max = max(primary_use_max, c["PrimaryRouteUseCount"])
                critical_use_max = max(critical_use_max, c["CriticalRouteUseCount"])
                cav = c.get("MinAvailableWidth_m")
                if cav is not None and (min_corridor_avail is None or cav < min_corridor_avail):
                    min_corridor_avail = cav

            # Validation nearby means this confirmed section is also near validation sections.
            val_nearby = 0
            for v in validation:
                ext = v["extent"]
                dext = dmg["extent"]
                if (
                    dext.XMax + DAMAGE_TOUCH_M < ext.XMin
                    or dext.XMin - DAMAGE_TOUCH_M > ext.XMax
                    or dext.YMax + DAMAGE_TOUCH_M < ext.YMin
                    or dext.YMin - DAMAGE_TOUCH_M > ext.YMax
                ):
                    continue
                try:
                    if dmg["geom"].distanceTo(v["geom"]) <= DAMAGE_TOUCH_M:
                        val_nearby = 1
                        break
                except Exception:
                    continue

            avail_w = dmg["AvailableWidth_m"]
            if dmg["DamageClass"] == 3:
                avail_w = 0.0
            elif avail_w is None:
                avail_w = min_corridor_avail

            priority_level, reason = derive_priority(
                dmg["DamageClass"], avail_w, critical_use_max, primary_use_max, matched
            )

            if (
                dmg["SourceDamageLayer"] == "Professor_confirmed"
                and prof_default
                and "default Class 2" not in reason
            ):
                reason += " Professor damage without class; default Class 2 used."

            if val_nearby == 1:
                reason += " Validation-needed damage is also nearby; field check recommended."

            priority_id += 1
            vals_map = {
                "PriorityID": priority_id,
                "SourceDamageLayer": dmg["SourceDamageLayer"],
                "SourceDamageOID": dmg["SourceDamageOID"],
                "DamageClass": dmg["DamageClass"],
                "RoadName": dmg["RoadName"] or safe_text(matched[0].get("RoadName")),
                "RoadType": dmg["RoadType"] or safe_text(matched[0].get("RoadType")),
                "AvailableWidth_m": avail_w,
                "TargetsAffected": ", ".join(sorted(targets_set)),
                "ServiceGroupsAffected": ", ".join(sorted(groups_set)),
                "UsedByRouteCount": route_use_max,
                "PrimaryRouteUseCount": primary_use_max,
                "CriticalRouteCount": critical_use_max,
                "CorridorSegmentCount": len(matched),
                "PriorityLevel": priority_level,
                "PriorityReason": reason,
                "ValidationNearby": val_nearby,
            }

            vals = [dmg["geom"]]
            for fn in out_fields:
                v = vals_map.get(fn)
                if fn in out_text_len and isinstance(v, str):
                    v = truncate_text(v, out_text_len[fn])
                vals.append(v)
            ic.insertRow(vals)

            created += 1
            priority_counter[priority_level] += 1
            source_counter[dmg["SourceDamageLayer"]] += 1
            if val_nearby == 1:
                validation_nearby_count += 1

            qa_rows.append(
                {
                    "PriorityID": priority_id,
                    "SourceDamageLayer": dmg["SourceDamageLayer"],
                    "SourceDamageOID": dmg["SourceDamageOID"],
                    "DamageClass": dmg["DamageClass"],
                    "RoadName": vals_map["RoadName"],
                    "RoadType": vals_map["RoadType"],
                    "AvailableWidth_m": avail_w,
                    "TargetsAffected": vals_map["TargetsAffected"],
                    "ServiceGroupsAffected": vals_map["ServiceGroupsAffected"],
                    "UsedByRouteCount": route_use_max,
                    "PrimaryRouteUseCount": primary_use_max,
                    "CriticalRouteCount": critical_use_max,
                    "CorridorSegmentCount": len(matched),
                    "PriorityLevel": priority_level,
                    "ValidationNearby": val_nearby,
                    "QA_Status": "ok",
                    "QA_Note": reason,
                }
            )

    write_qa_csv(qa_rows)
    try:
        update_map()
    except Exception as ex:
        print(f"WARNING: map update failed: {ex}")

    print("\n" + "=" * 72)
    print("QA SUMMARY — Road Reopening Priority from Corridors")
    print("=" * 72)
    print(f"  Corridor segments loaded:      {len(corridors)}")
    print(f"  Confirmed ML sections loaded:  {len(ml_damage)}")
    print(f"  Professor sections loaded:     {len(prof_damage)}")
    print(f"  Validation sections loaded:    {len(validation)}")
    print(f"  Priority sections created:     {created}")
    print(f"  Skipped confirmed not on corridor: {skipped_not_on_corridor}")
    print("  Count by PriorityLevel:")
    for k in sorted(priority_counter.keys()):
        print(f"      - Priority {k}: {priority_counter[k]}")
    print("  Count by SourceDamageLayer:")
    for k, v in sorted(source_counter.items(), key=lambda kv: -kv[1]):
        print(f"      - {k}: {v}")
    print(f"  Count with ValidationNearby=1: {validation_nearby_count}")
    print(f"  Output path:                   {OUTPUT_PRIORITY_FC}")
    print(f"  QA CSV path:                   {QA_CSV}")
    print()
    print("  Methodological note:")
    print("    Emergency_Road_Reopening_Priority is rebuilt from the final")
    print("    Emergency_Response_Corridor_Network. It includes only confirmed")
    print("    damaged road sections that affect selected emergency corridors from")
    print("    emergency services to Amatrice, Accumoli, and Illica. Priority is")
    print("    assigned using damage class, available width, corridor usage,")
    print("    critical-route involvement, and nearby validation uncertainty.")
    print("=" * 72 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
