# -*- coding: utf-8 -*-
"""
29_emergency_service_accessibility_analysis.py
----------------------------------------------
First-emergency / Search-and-Rescue accessibility assessment.

Evaluates whether emergency service centers can reach the emergency response
targets (Amatrice, Accumoli, Illica) over Roads_Ideal_OSM_v2_full_clean, using
BOTH confirmed damage sources as conservative routing penalties. Custom Dijkstra
(no Network Analyst). Produces route, target-status, and road-reopening-priority
layers. Shelters are out of scope (later phase).

Methodological note:
This script assesses first-emergency accessibility from emergency service centers
to affected targets using the updated road network and both confirmed road-damage
sources. Damage classes are translated into conservative routing penalties for the
search-and-rescue phase. Class 3 damage is treated as blocked in the conservative
scenario; if no conservative path exists, a degraded path is mapped to identify
critical bottlenecks. Validation-needed damage sections are treated as uncertainty,
not confirmed blockage.
"""

from __future__ import annotations

import csv
import heapq
import math
import os
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import arcpy

arcpy.env.overwriteOutput = True

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

APRX_PATH = os.environ.get("GPEM_APRX_PATH", "CURRENT")
MAIN_GDB = os.environ.get("GPEM_MAIN_GDB", r"C:\path\to\your_project.gdb")

ROAD_FC = os.path.join(MAIN_GDB, "Roads_Ideal_OSM_v2_full_clean")
EMERGENCY_SERVICES_FC = os.path.join(MAIN_GDB, "Emergency_Service_Centers")
TARGETS_FC = os.path.join(MAIN_GDB, "Emergency_Response_Targets")
CONFIRMED_DAMAGE_ML_FC = os.path.join(
    MAIN_GDB, "Unified_Damage_RoadSections_Confirmed_Assessed"
)
CONFIRMED_DAMAGE_PROF_FC = os.path.join(MAIN_GDB, "Roads_Damage_FromTableOnly")
VALIDATION_DAMAGE_FC = os.path.join(
    MAIN_GDB, "Unified_Damage_RoadSections_NeedsValidation_Assessed"
)

ROUTES_OUTPUT_FC = os.path.join(MAIN_GDB, "Emergency_Accessibility_Routes")
TARGET_STATUS_FC = os.path.join(MAIN_GDB, "Emergency_Target_Accessibility_Status")
ROAD_PRIORITY_FC = os.path.join(MAIN_GDB, "Emergency_Road_Reopening_Priority")
CORRIDOR_OUTPUT_FC = os.path.join(MAIN_GDB, "Emergency_Response_Corridor_Network")

QA_CSV = os.path.join(os.environ.get("GPEM_QA_DIR", "qa"), "Emergency_Accessibility_QA.csv")

CLEAR_OUTPUT = os.environ.get("GPEM_CLEAR_OUTPUT", "false").strip().lower() in {"true", "1", "yes"}

# Metric working spatial reference for all routing geometry (Monte Mario / Italy 1).
# Source layers may be geographic (degrees); routing requires metres.
WORKING_SR = arcpy.SpatialReference(3065)

# Graph / routing parameters.
NODE_ROUNDING_M = 1.0
DAMAGE_TOUCH_M = 5.0
DEFAULT_CONFIRMED_CLASS = 2  # used when a confirmed source has no class field
LANE_PROXY_WIDTH_M = 3.25

# Damage-adjusted cost multipliers.
MULT_CLASS1 = 1.5
MULT_CLASS2 = 5.0
MULT_CLASS3_DEGRADED = 100.0
MULT_VALIDATION = 2.0

ROUTES_PER_GROUP = 2

# Target-based candidate screening.
MAX_CANDIDATE_SERVICES_PER_GROUP = 3
SCREENING_RADIUS_KM = {
    "health_emergency": 30.0,
    "fire_response": 45.0,
    "security": 35.0,
    "coordination": 35.0,
}
FALLBACK_NEAREST_OUTSIDE_RADIUS = 1

# Damage-exposure thresholds for nuanced AccessStatus.
CLASS2_RESTRICTED_LENGTH_KM = 0.25
NARROW_WIDTH_RESTRICTED_M = 2.5
ROUTE_OVERLAP_REDUCE_THRESHOLD = 0.70
MIN_WIDTH_CRITICAL_M = 2.5
MIN_WIDTH_RESTRICTED_M = 4.5
NARROW_ROAD_M = 4.5

# Service-group classification by FacilityType.
FACILITY_GROUP: Dict[str, str] = {
    "hospital": "health_emergency",
    "health_center": "health_emergency",
    "ambulance_first_aid": "health_emergency",
    "health_first_aid_support": "health_emergency",
    "fire_station": "fire_response",
    "police_carabinieri": "security",
    "civil_protection_center": "coordination",
    "municipality_coordination": "coordination",
    "government_office": "coordination",
}
ESSENTIAL_GROUPS = ["health_emergency", "fire_response", "security", "coordination"]

# Status ordering (worst first).
STATUS_RANK = {
    "critical": 6,
    "restricted": 5,
    "partially_restricted": 4,
    "uncertain": 3,
    "accessible_with_caution": 2,
    "accessible": 1,
    "no_route": 7,
    "no_facility_available": 0,
}

OUTPUT_LAYER_ROUTES = "Emergency Accessibility Routes"
OUTPUT_LAYER_TARGETS = "Emergency Target Accessibility Status"
OUTPUT_LAYER_PRIORITY = "Emergency Road Reopening Priority"
OUTPUT_LAYER_CORRIDOR = "Emergency Response Corridor Network"
OLD_LAYER_NAMES = {
    "Emergency_Accessibility_Routes",
    OUTPUT_LAYER_ROUTES,
    "Emergency_Target_Accessibility_Status",
    OUTPUT_LAYER_TARGETS,
    "Emergency_Road_Reopening_Priority",
    OUTPUT_LAYER_PRIORITY,
    "Emergency_Response_Corridor_Network",
    OUTPUT_LAYER_CORRIDOR,
    "Emergency_Network_Scenario",
    "Emergency Network Scenario",
    "Emergency_Accessibility_Routes_1",
    "Emergency_Accessibility_Routes_2",
    "Emergency_Accessibility_Routes_3",
    "Roads_Ideal_OSM_v2_clean",
    "Roads Ideal OSM v2 Clean",
    "eRoads_Ideal_OSM_v2_raw",
}

ROUTE_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("RouteID", "LONG", None),
    ("OriginFacilityID", "LONG", None),
    ("OriginName", "TEXT", 150),
    ("OriginType", "TEXT", 80),
    ("ServiceGroup", "TEXT", 80),
    ("TargetID", "LONG", None),
    ("TargetName", "TEXT", 100),
    ("RouteRank", "SHORT", None),
    ("RouteLength_km", "DOUBLE", None),
    ("RouteCost", "DOUBLE", None),
    ("MaxDamageClass", "SHORT", None),
    ("Class1_Count", "SHORT", None),
    ("Class2_Count", "SHORT", None),
    ("Class3_Count", "SHORT", None),
    ("Validation_Count", "SHORT", None),
    ("MinAvailableWidth_m", "DOUBLE", None),
    ("RouteDamageClass", "SHORT", None),
    ("RouteDamageLabel", "TEXT", 120),
    ("Class1_Length_km", "DOUBLE", None),
    ("Class2_Length_km", "DOUBLE", None),
    ("Class3_Length_km", "DOUBLE", None),
    ("DamageExposureRatio", "DOUBLE", None),
    ("CandidateDistance_km", "DOUBLE", None),
    ("WithinScreeningRadius", "SHORT", None),
    ("SelectionReason", "TEXT", 120),
    ("RouteOverlapWithPrimary", "DOUBLE", None),
    ("AccessStatus", "TEXT", 80),
    ("RedundancyLevel", "TEXT", 80),
    ("ScenarioUsed", "TEXT", 80),
    ("RouteNote", "TEXT", 255),
]

TARGET_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("TargetID", "LONG", None),
    ("TargetName", "TEXT", 100),
    ("BestHealthAccess", "TEXT", 80),
    ("BestFireAccess", "TEXT", 80),
    ("BestSecurityAccess", "TEXT", 80),
    ("BestCoordinationAccess", "TEXT", 80),
    ("OverallAccessStatus", "TEXT", 80),
    ("OverallRedundancy", "TEXT", 80),
    ("PriorityForIntervention", "SHORT", None),
    ("StatusNote", "TEXT", 255),
    ("TargetAccessStrategy", "TEXT", 500),
    ("PrimaryHealthFacility", "TEXT", 150),
    ("PrimaryFireFacility", "TEXT", 150),
    ("PrimarySecurityFacility", "TEXT", 150),
    ("PrimaryCoordinationFacility", "TEXT", 150),
]

PRIORITY_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("PriorityID", "LONG", None),
    ("SourceDamageLayer", "TEXT", 100),
    ("DamageClass", "SHORT", None),
    ("RoadName", "TEXT", 150),
    ("RoadType", "TEXT", 80),
    ("AvailableWidth_m", "DOUBLE", None),
    ("UsedByRouteCount", "LONG", None),
    ("CriticalRouteCount", "LONG", None),
    ("PriorityLevel", "SHORT", None),
    ("PriorityReason", "TEXT", 255),
]

CORRIDOR_FIELD_SPECS: List[Tuple[str, str, Optional[int]]] = [
    ("CorridorID", "LONG", None),
    ("SourceRoadOID", "LONG", None),
    ("RoadName", "TEXT", 150),
    ("RoadType", "TEXT", 80),
    ("RoadGroup", "TEXT", 80),
    ("NetworkRole", "TEXT", 100),
    ("EmergencyUsable", "SHORT", None),
    ("RoadWidth_m", "DOUBLE", None),
    ("TargetsServed", "TEXT", 255),
    ("ServiceGroupsServed", "TEXT", 255),
    ("RouteUseCount", "LONG", None),
    ("PrimaryRouteUseCount", "LONG", None),
    ("CriticalRouteUseCount", "LONG", None),
    ("RouteDamageClass", "SHORT", None),
    ("RouteDamageLabel", "TEXT", 120),
    ("ValidationFlag", "SHORT", None),
    ("MinAvailableWidth_m", "DOUBLE", None),
    ("EmergencyAccessClass", "TEXT", 100),
    ("AccessCostFactor", "DOUBLE", None),
    ("ReopeningPriorityLevel", "SHORT", None),
    ("CorridorNote", "TEXT", 255),
]

QA_FIELDS = [
    "RouteID",
    "OriginName",
    "OriginType",
    "ServiceGroup",
    "TargetName",
    "RouteRank",
    "RouteLength_km",
    "RouteCost",
    "MaxDamageClass",
    "Class1_Count",
    "Class2_Count",
    "Class3_Count",
    "Validation_Count",
    "MinAvailableWidth_m",
    "RouteDamageClass",
    "RouteDamageLabel",
    "CandidateDistance_km",
    "WithinScreeningRadius",
    "SelectionReason",
    "Class2_Length_km",
    "Class3_Length_km",
    "DamageExposureRatio",
    "RouteOverlapWithPrimary",
    "AccessStatus",
    "RedundancyLevel",
    "ScenarioUsed",
    "TargetAccessStrategy",
    "QA_Note",
]

# Field-name candidates for flexible damage layers.
DMG_CLASS_FIELDS = [
    "DamageClass", "DmgClass", "DmgClass_Pre", "DamageClass_Pre", "Class",
]
DMG_AVAILWIDTH_FIELDS = ["AvailableWidth_m", "AvailWidth_m", "UsableWidth_m"]
DMG_ROADWIDTH_FIELDS = ["RoadWidth_m", "Width_m", "RoadWidthProxy_m"]
DMG_ROADNAME_FIELDS = ["RoadName", "name", "NAME", "STRADA", "strada"]
DMG_ROADTYPE_FIELDS = ["RoadType", "highway", "fclass", "type"]

# Field-name candidates for the road network.
ROAD_NAME_FIELDS = ["RoadName", "name", "NAME", "STRADA"]
ROAD_TYPE_FIELDS = ["RoadType", "highway", "fclass", "type"]
ROAD_GROUP_FIELDS = ["RoadGroup"]
ROAD_WIDTH_FIELDS = ["Width_m"]
ROAD_PROXY_FIELDS = ["RoadWidthProxy_m"]
ROAD_EU_FIELDS = ["EmergencyUsable"]
ROAD_NETROLE_FIELDS = ["NetworkRole"]

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


def pick_field(fc_path: str, candidates: List[str]) -> Optional[str]:
    existing = {f.name.lower(): f.name for f in arcpy.ListFields(fc_path)}
    for c in candidates:
        if c.lower() in existing:
            return existing[c.lower()]
    return None


def node_key(x: float, y: float) -> Tuple[int, int]:
    return (int(round(x / NODE_ROUNDING_M)), int(round(y / NODE_ROUNDING_M)))


def project_geom_to_working(g: Any) -> Any:
    """Project a geometry to WORKING_SR (metric). Returns input on failure."""
    if g is None:
        return None
    try:
        src = g.spatialReference
        if src and src.factoryCode == WORKING_SR.factoryCode:
            return g
        return g.projectAs(WORKING_SR)
    except Exception:
        return g


def iter_polyline_points(polyline: Any):
    """Yield vertices part-by-part; yields None at part breaks to stop joining."""
    for i in range(polyline.partCount):
        part = polyline.getPart(i)
        for pnt in part:
            if pnt is not None:
                yield pnt
            else:
                yield None
        yield None  # explicit part break


def create_fc(path: str, geom_type: str, sr: arcpy.SpatialReference,
              specs: List[Tuple[str, str, Optional[int]]]) -> None:
    if arcpy.Exists(path):
        if CLEAR_OUTPUT:
            arcpy.management.Delete(path)
        else:
            raise RuntimeError(f"Output exists and CLEAR_OUTPUT is False: {path}")
    gdb, name = os.path.split(path)
    arcpy.management.CreateFeatureclass(gdb, name, geom_type, spatial_reference=sr)
    for fname, ftype, flen in specs:
        if ftype == "TEXT":
            arcpy.management.AddField(path, fname, ftype, field_length=flen or 255)
        else:
            arcpy.management.AddField(path, fname, ftype)


# ---------------------------------------------------------------------------
# GRAPH CONSTRUCTION
# ---------------------------------------------------------------------------


class Graph:
    def __init__(self) -> None:
        self.node_coord: Dict[int, Tuple[float, float]] = {}
        self.key_to_id: Dict[Tuple[int, int], int] = {}
        self.adj: Dict[int, List[Tuple[int, int]]] = defaultdict(list)  # node -> [(nbr, edge_idx)]
        self.edges: List[Dict[str, Any]] = []
        self.eu1_nodes: Set[int] = set()

    def get_node(self, x: float, y: float) -> int:
        k = node_key(x, y)
        nid = self.key_to_id.get(k)
        if nid is None:
            nid = len(self.key_to_id)
            self.key_to_id[k] = nid
            self.node_coord[nid] = (x, y)
        return nid

    def add_edge(self, n1: int, n2: int, attrs: Dict[str, Any]) -> None:
        if n1 == n2:
            return
        idx = len(self.edges)
        self.edges.append(attrs)
        self.adj[n1].append((n2, idx))
        self.adj[n2].append((n1, idx))
        if attrs.get("eu") == 1:
            self.eu1_nodes.add(n1)
            self.eu1_nodes.add(n2)


def load_roads_into_graph(
    road_fc: str,
) -> Tuple[Graph, arcpy.SpatialReference, Dict[str, Any]]:
    source_sr = arcpy.Describe(road_fc).spatialReference
    sr = WORKING_SR  # all routing geometry is metric (EPSG:3065)
    oid_f = get_oid_field(road_fc)
    f_name = pick_field(road_fc, ROAD_NAME_FIELDS)
    f_type = pick_field(road_fc, ROAD_TYPE_FIELDS)
    f_group = pick_field(road_fc, ROAD_GROUP_FIELDS)
    f_width = pick_field(road_fc, ROAD_WIDTH_FIELDS)
    f_proxy = pick_field(road_fc, ROAD_PROXY_FIELDS)
    f_eu = pick_field(road_fc, ROAD_EU_FIELDS)
    f_role = pick_field(road_fc, ROAD_NETROLE_FIELDS)

    fields = [oid_f, "SHAPE@"]
    for f in (f_name, f_type, f_group, f_width, f_proxy, f_eu, f_role):
        if f and f not in fields:
            fields.append(f)

    diag = {
        "source_sr_name": source_sr.name if source_sr else "Unknown",
        "source_sr_code": source_sr.factoryCode if source_sr else 0,
        "features_read": 0,
        "features_valid": 0,
        "skipped_zero_length": 0,
    }

    graph = Graph()
    with arcpy.da.SearchCursor(road_fc, fields) as cur:
        for row in cur:
            diag["features_read"] += 1
            rec = {fields[i]: row[i] for i in range(len(fields))}
            shape = rec.get("SHAPE@")
            shape = project_geom_to_working(shape)
            if shape is None or shape.length <= 0:
                diag["skipped_zero_length"] += 1
                continue
            diag["features_valid"] += 1
            road_attrs = {
                "RoadOID": safe_int(rec.get(oid_f)),
                "RoadName": safe_text(rec.get(f_name)) if f_name else "",
                "RoadType": safe_text(rec.get(f_type)) if f_type else "",
                "RoadGroup": safe_text(rec.get(f_group)) if f_group else "",
                "Width_m": safe_float(rec.get(f_width)) if f_width else None,
                "RoadWidthProxy_m": safe_float(rec.get(f_proxy)) if f_proxy else None,
                "eu": safe_int(rec.get(f_eu), 1) if f_eu else 1,
                "NetworkRole": safe_text(rec.get(f_role)) if f_role else "",
            }
            prev_node: Optional[int] = None
            prev_xy: Optional[Tuple[float, float]] = None
            for pnt in iter_polyline_points(shape):
                if pnt is None:
                    # Part break: do not connect across parts.
                    prev_node = None
                    prev_xy = None
                    continue
                nid = graph.get_node(pnt.X, pnt.Y)
                if prev_node is not None and prev_xy is not None:
                    seg_len = math.hypot(pnt.X - prev_xy[0], pnt.Y - prev_xy[1])
                    if seg_len > 0:
                        edge = dict(road_attrs)
                        edge["base_len"] = seg_len
                        edge["p1"] = prev_xy
                        edge["p2"] = (pnt.X, pnt.Y)
                        edge["max_conf_class"] = 0
                        edge["touched_confirmed"] = set()
                        edge["touched_validation"] = set()
                        graph.add_edge(prev_node, nid, edge)
                prev_node = nid
                prev_xy = (pnt.X, pnt.Y)
    return graph, sr, diag


# ---------------------------------------------------------------------------
# DAMAGE LOADING & ASSIGNMENT
# ---------------------------------------------------------------------------


def load_damage_sections(
    fc_path: str, source_label: str, is_validation: bool
) -> List[Dict[str, Any]]:
    if not arcpy.Exists(fc_path):
        print(f"  WARNING: damage layer not found ({source_label}): {fc_path}")
        return []
    f_class = pick_field(fc_path, DMG_CLASS_FIELDS)
    f_avail = pick_field(fc_path, DMG_AVAILWIDTH_FIELDS)
    f_rw = pick_field(fc_path, DMG_ROADWIDTH_FIELDS)
    f_name = pick_field(fc_path, DMG_ROADNAME_FIELDS)
    f_type = pick_field(fc_path, DMG_ROADTYPE_FIELDS)

    fields = ["SHAPE@"]
    for f in (f_class, f_avail, f_rw, f_name, f_type):
        if f and f not in fields:
            fields.append(f)

    sections: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(fc_path, fields) as cur:
        for row in cur:
            rec = {fields[i]: row[i] for i in range(len(fields))}
            geom = rec.get("SHAPE@")
            geom = project_geom_to_working(geom)
            if geom is None:
                continue
            if is_validation:
                dclass = 0
            else:
                dclass = safe_int(rec.get(f_class), None) if f_class else None
                if dclass is None:
                    dclass = DEFAULT_CONFIRMED_CLASS
            road_width = safe_float(rec.get(f_rw)) if f_rw else None
            avail = safe_float(rec.get(f_avail)) if f_avail else None
            if avail is None and not is_validation and road_width is not None:
                if dclass == 1:
                    avail = 0.75 * road_width
                elif dclass == 2:
                    avail = 0.50 * road_width
                elif dclass == 3:
                    avail = 0.0
            sections.append(
                {
                    "geom": geom,
                    "extent": geom.extent,
                    "DamageClass": dclass,
                    "AvailableWidth_m": avail,
                    "RoadWidth_m": road_width,
                    "RoadName": safe_text(rec.get(f_name)) if f_name else "",
                    "RoadType": safe_text(rec.get(f_type)) if f_type else "",
                    "SourceDamageLayer": source_label,
                    "is_validation": is_validation,
                }
            )
    print(f"  Loaded {len(sections)} sections from {source_label}.")
    return sections


def _extents_overlap(e1: Any, e2: Any, pad: float) -> bool:
    return not (
        e1.XMax + pad < e2.XMin
        or e1.XMin - pad > e2.XMax
        or e1.YMax + pad < e2.YMin
        or e1.YMin - pad > e2.YMax
    )


def assign_damage_to_edges(
    graph: Graph,
    confirmed: List[Dict[str, Any]],
    validation: List[Dict[str, Any]],
    sr: arcpy.SpatialReference,
) -> None:
    """Tag each edge with the confirmed/validation damage section indices it touches."""
    all_dmg = [("c", i, s) for i, s in enumerate(confirmed)] + [
        ("v", i, s) for i, s in enumerate(validation)
    ]
    if not all_dmg:
        return
    for edge in graph.edges:
        x1, y1 = edge["p1"]
        x2, y2 = edge["p2"]
        e_xmin, e_xmax = min(x1, x2), max(x1, x2)
        e_ymin, e_ymax = min(y1, y2), max(y1, y2)
        edge_geom: Optional[arcpy.Polyline] = None
        for kind, idx, sec in all_dmg:
            ext = sec["extent"]
            if (
                e_xmax + DAMAGE_TOUCH_M < ext.XMin
                or e_xmin - DAMAGE_TOUCH_M > ext.XMax
                or e_ymax + DAMAGE_TOUCH_M < ext.YMin
                or e_ymin - DAMAGE_TOUCH_M > ext.YMax
            ):
                continue
            if edge_geom is None:
                arr = arcpy.Array([arcpy.Point(x1, y1), arcpy.Point(x2, y2)])
                edge_geom = arcpy.Polyline(arr, sr)
            try:
                d = edge_geom.distanceTo(sec["geom"])
            except Exception:
                continue
            if d <= DAMAGE_TOUCH_M:
                if kind == "c":
                    edge["touched_confirmed"].add(idx)
                    if sec["DamageClass"] and sec["DamageClass"] > edge["max_conf_class"]:
                        edge["max_conf_class"] = sec["DamageClass"]
                else:
                    edge["touched_validation"].add(idx)


# ---------------------------------------------------------------------------
# SNAPPING
# ---------------------------------------------------------------------------


def snap_point_to_node(
    pt_geom: Any, graph: Graph
) -> Tuple[Optional[int], float, bool]:
    """Snap to nearest node on an EmergencyUsable=1 road; fall back to any node.

    Returns (node_id, snap_dist_m, low_confidence).
    """
    if pt_geom is None:
        return None, 0.0, False
    try:
        px, py = pt_geom.firstPoint.X, pt_geom.firstPoint.Y
    except Exception:
        return None, 0.0, False

    def nearest(node_ids: Any) -> Tuple[Optional[int], float]:
        best_id: Optional[int] = None
        best_d = float("inf")
        for nid in node_ids:
            cx, cy = graph.node_coord[nid]
            d = math.hypot(px - cx, py - cy)
            if d < best_d:
                best_d = d
                best_id = nid
        return best_id, best_d

    if graph.eu1_nodes:
        nid, d = nearest(graph.eu1_nodes)
        if nid is not None:
            return nid, d, False
    nid, d = nearest(graph.node_coord.keys())
    return nid, d, True


# ---------------------------------------------------------------------------
# DIJKSTRA
# ---------------------------------------------------------------------------


def edge_cost(edge: Dict[str, Any], allow_class3: bool, degraded: bool) -> Optional[float]:
    cls = edge["max_conf_class"]
    if cls == 3:
        if not allow_class3:
            return None
        mult = MULT_CLASS3_DEGRADED
    elif cls == 2:
        mult = MULT_CLASS2
    elif cls == 1:
        mult = MULT_CLASS1
    elif edge["touched_validation"]:
        mult = MULT_VALIDATION
    else:
        mult = 1.0
    return edge["base_len"] * mult


def dijkstra(
    graph: Graph,
    source: int,
    allow_eu0: bool,
    allow_class3: bool,
    degraded: bool,
) -> Tuple[Dict[int, float], Dict[int, int], Dict[int, int]]:
    dist: Dict[int, float] = {source: 0.0}
    pred_node: Dict[int, int] = {}
    pred_edge: Dict[int, int] = {}
    pq: List[Tuple[float, int]] = [(0.0, source)]
    visited: Set[int] = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, eidx in graph.adj[u]:
            if v in visited:
                continue
            edge = graph.edges[eidx]
            if not allow_eu0 and edge.get("eu") == 0:
                continue
            c = edge_cost(edge, allow_class3, degraded)
            if c is None:
                continue
            nd = d + c
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                pred_node[v] = u
                pred_edge[v] = eidx
                heapq.heappush(pq, (nd, v))
    return dist, pred_node, pred_edge


def reconstruct_edges(
    source: int, dest: int, pred_node: Dict[int, int], pred_edge: Dict[int, int]
) -> Optional[List[int]]:
    """Edges from source-rooted tree back to dest. Returns edge indices dest->source."""
    if dest == source:
        return []
    if dest not in pred_node:
        return None
    edges: List[int] = []
    nodes: List[int] = [dest]
    cur = dest
    guard = 0
    while cur != source:
        eidx = pred_edge.get(cur)
        nxt = pred_node.get(cur)
        if eidx is None or nxt is None:
            return None
        edges.append(eidx)
        cur = nxt
        nodes.append(cur)
        guard += 1
        if guard > len(pred_node) + 5:
            return None
    return edges


def node_path(
    source: int, dest: int, pred_node: Dict[int, int]
) -> List[int]:
    nodes = [dest]
    cur = dest
    guard = 0
    while cur != source:
        nxt = pred_node.get(cur)
        if nxt is None:
            break
        nodes.append(nxt)
        cur = nxt
        guard += 1
        if guard > len(pred_node) + 5:
            break
    nodes.reverse()
    return nodes


# ---------------------------------------------------------------------------
# EXPOSURE & STATUS
# ---------------------------------------------------------------------------


def route_exposure(
    edge_indices: List[int],
    graph: Graph,
    confirmed: List[Dict[str, Any]],
) -> Dict[str, Any]:
    conf_idx: Set[int] = set()
    val_idx: Set[int] = set()
    edge_set: Set[int] = set()
    length_m = 0.0
    c1_len = c2_len = c3_len = 0.0
    for eidx in edge_indices:
        edge = graph.edges[eidx]
        length_m += edge["base_len"]
        edge_set.add(eidx)
        conf_idx |= edge["touched_confirmed"]
        val_idx |= edge["touched_validation"]
        # Attribute edge length to its worst confirmed class bucket.
        ecls = edge["max_conf_class"]
        if ecls == 1:
            c1_len += edge["base_len"]
        elif ecls == 2:
            c2_len += edge["base_len"]
        elif ecls == 3:
            c3_len += edge["base_len"]

    c1 = c2 = c3 = 0
    max_class = 0
    min_avail: Optional[float] = None
    for i in conf_idx:
        sec = confirmed[i]
        cls = sec["DamageClass"] or 0
        if cls == 1:
            c1 += 1
        elif cls == 2:
            c2 += 1
        elif cls == 3:
            c3 += 1
        if cls > max_class:
            max_class = cls
        aw = sec["AvailableWidth_m"]
        if aw is not None and (min_avail is None or aw < min_avail):
            min_avail = aw

    damaged_len = c1_len + c2_len + c3_len
    exposure_ratio = (damaged_len / length_m) if length_m > 0 else 0.0

    return {
        "conf_idx": conf_idx,
        "val_idx": val_idx,
        "edge_set": edge_set,
        "length_m": length_m,
        "Class1_Count": c1,
        "Class2_Count": c2,
        "Class3_Count": c3,
        "Validation_Count": len(val_idx),
        "MaxDamageClass": max_class,
        "MinAvailableWidth_m": min_avail,
        "Class1_Length_m": c1_len,
        "Class2_Length_m": c2_len,
        "Class3_Length_m": c3_len,
        "DamageExposureRatio": exposure_ratio,
    }


def classify_access_status(exposure: Dict[str, Any], degraded: bool) -> str:
    min_w = exposure["MinAvailableWidth_m"]
    c2_len_km = exposure["Class2_Length_m"] / 1000.0

    # critical
    if degraded or exposure["Class3_Count"] > 0 or (min_w is not None and min_w == 0):
        return "critical"

    # restricted (Class 2 present, no Class 3)
    if exposure["Class2_Count"] > 0:
        if (
            c2_len_km >= CLASS2_RESTRICTED_LENGTH_KM
            or exposure["Class2_Count"] >= 2
            or (min_w is not None and min_w < NARROW_WIDTH_RESTRICTED_M)
        ):
            return "restricted"
        return "partially_restricted"

    # uncertain (validation only, no confirmed Class 2/3)
    if exposure["Validation_Count"] > 0:
        return "uncertain"

    # accessible_with_caution (only Class 1)
    if exposure["Class1_Count"] > 0:
        return "accessible_with_caution"

    return "accessible"


def build_target_strategy(target_name: str, overall: str) -> str:
    name = (target_name or "").lower()
    if "amatrice" in name:
        base = (
            "Use closest available health/fire/security/coordination routes. "
            "Maintain at least one primary access corridor and prioritize damaged "
            "sections on routes entering the town."
        )
    elif "accumoli" in name:
        base = (
            "Prioritize continuity of the main access corridor and backup connection "
            "because local access depends on limited road redundancy."
        )
    elif "illica" in name:
        base = (
            "Prioritize local access from the nearest main corridor; narrow local roads "
            "and damage exposure should be checked carefully."
        )
    else:
        base = (
            "Use closest available emergency service routes per group and maintain at "
            "least one primary access corridor."
        )
    if overall == "critical":
        base += " Immediate road reopening or alternative access verification is required."
    elif overall == "restricted":
        base += (" Access is possible but operationally restricted; damaged bottlenecks "
                 "should be prioritized.")
    elif overall == "uncertain":
        base += " Validation-needed sections should be checked before deployment."
    return base


def route_damage_class(exposure: Dict[str, Any]) -> Tuple[int, str]:
    """Worst confirmed damage class crossed, mirroring the damage road-section layers.

    0 = no confirmed class crossed (or validation-only uncertainty).
    """
    if exposure["Class3_Count"] > 0:
        return 3, "high_damage_exposure"
    if exposure["Class2_Count"] > 0:
        return 2, "medium_damage_exposure"
    if exposure["Class1_Count"] > 0:
        return 1, "low_damage_exposure"
    if exposure["Validation_Count"] > 0:
        return 0, "validation_uncertainty_only"
    return 0, "no_confirmed_damage"


def edge_damage_class(edge: Dict[str, Any]) -> Tuple[int, str]:
    cls = edge.get("max_conf_class", 0) or 0
    if cls == 3:
        return 3, "high_damage_exposure"
    if cls == 2:
        return 2, "medium_damage_exposure"
    if cls == 1:
        return 1, "low_damage_exposure"
    if edge.get("touched_validation"):
        return 0, "validation_uncertainty_only"
    return 0, "no_confirmed_damage"


def derive_corridor_road_width(edge: Dict[str, Any]) -> float:
    w = safe_float(edge.get("Width_m"))
    if w is not None and w > 0:
        return w
    proxy = safe_float(edge.get("RoadWidthProxy_m"))
    if proxy is not None and proxy > 0:
        return proxy
    rt = safe_text(edge.get("RoadType")).lower()
    if rt in ("motorway", "trunk", "primary"):
        return 7.5
    if rt == "secondary":
        return 6.5
    if rt == "tertiary":
        return 5.5
    if rt in ("residential", "living_street", "unclassified", "road"):
        return 4.5
    if rt == "service":
        return 3.5
    if rt in ("track", "path", "footway", "cycleway", "pedestrian"):
        return 2.5
    return 4.5


def classify_corridor_access(
    eu: int,
    rdc: int,
    val_flag: int,
    min_avail: Optional[float],
    road_width: Optional[float],
) -> str:
    if eu == 0:
        return "not_suitable_for_emergency_vehicle_access"
    if rdc == 3:
        return "critical_or_blocked"
    if min_avail is not None and min_avail < MIN_WIDTH_CRITICAL_M:
        return "critical_or_blocked"
    if rdc == 2 and road_width is not None and road_width < NARROW_ROAD_M:
        return "critical_or_blocked"
    if rdc == 2:
        return "restricted"
    if min_avail is not None and min_avail < MIN_WIDTH_RESTRICTED_M:
        return "restricted"
    if val_flag == 1 and road_width is not None and road_width < NARROW_ROAD_M:
        return "restricted"
    if val_flag == 1:
        return "uncertain_validation_needed"
    if rdc == 1:
        return "open_with_caution"
    return "open"


def corridor_cost_factor(access_class: str) -> float:
    if access_class == "open":
        return 1.0
    if access_class == "open_with_caution":
        return 1.5
    if access_class == "restricted":
        return 5.0
    if access_class == "critical_or_blocked":
        return 100.0
    if access_class == "uncertain_validation_needed":
        return 2.0
    if access_class == "not_suitable_for_emergency_vehicle_access":
        return 100.0
    return 1.0


def route_overlap_ratio(edges_a: Set[int], edges_b: Set[int]) -> float:
    if not edges_a or not edges_b:
        return 0.0
    shared = len(edges_a & edges_b)
    return shared / min(len(edges_a), len(edges_b))


def redundancy_level(route_statuses: List[str], overlap_ratio: float = 0.0) -> str:
    good = [s for s in route_statuses if s in ("accessible", "accessible_with_caution")]
    mid = [s for s in route_statuses
           if s in ("partially_restricted", "restricted", "uncertain")]
    usable = good + mid
    only_critical = (
        all(s in ("critical", "no_route") for s in route_statuses)
        if route_statuses else True
    )

    if len(good) >= 2:
        level = "high"    elif len(good) >= 1 and len(mid) >= 1:
        level = "medium"
    elif len(usable) == 1:
        level = "low"
    elif only_critical:
        level = "critical"
    else:
        level = "low"

    # Routes that share most geometry are not truly independent.
    if overlap_ratio > ROUTE_OVERLAP_REDUCE_THRESHOLD and level in ("high", "medium"):
        level = "medium" if level == "high" else "low"
    return level


# ---------------------------------------------------------------------------
# MAP
# ---------------------------------------------------------------------------


def open_project() -> Optional[arcpy.mp.ArcGISProject]:
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
        print("  WARNING: No map available to add output layers.")
        return
    added = []
    for fc, name, field in (
        (CORRIDOR_OUTPUT_FC, OUTPUT_LAYER_CORRIDOR, "EmergencyAccessClass"),
        (ROUTES_OUTPUT_FC, OUTPUT_LAYER_ROUTES, "RouteDamageClass"),
        (TARGET_STATUS_FC, OUTPUT_LAYER_TARGETS, "OverallAccessStatus"),
        (ROAD_PRIORITY_FC, OUTPUT_LAYER_PRIORITY, "PriorityLevel"),
    ):
        if not arcpy.Exists(fc):
            continue
        try:
            lyr = m.addDataFromPath(fc)
            if lyr:
                lyr.name = name
                added.append((lyr, field))
        except Exception as ex:
            print(f"  WARNING: could not add {name}: {ex}")
    # RGB colors for corridor EmergencyAccessClass.
    access_colors = {
        "open": [0, 168, 0, 100],
        "open_with_caution": [150, 230, 120, 100],
        "uncertain_validation_needed": [90, 130, 200, 100],
        "restricted": [255, 140, 0, 100],
        "critical_or_blocked": [220, 0, 0, 100],
        "not_suitable_for_emergency_vehicle_access": [150, 150, 150, 100],
    }
    # RGB colors for route damage class (same logic as the damage road-section layers).
    damage_class_colors = {
        "0": [130, 130, 130, 100],   # grey/blue: no confirmed damage / validation-only
        "1": [0, 168, 0, 100],       # green: low damage exposure
        "2": [255, 170, 0, 100],     # yellow/orange: medium damage exposure
        "3": [220, 0, 0, 100],       # red: high damage exposure
    }
    ok = True
    for lyr, field in added:
        try:
            sym = lyr.symbology
            if hasattr(sym, "updateRenderer"):
                sym.updateRenderer("UniqueValueRenderer")
                sym.renderer.fields = [field]
                if field == "EmergencyAccessClass":
                    for grp in sym.renderer.groups:
                        for itm in grp.items:
                            val = str(itm.values[0][0])
                            rgb = access_colors.get(val)
                            if rgb:
                                itm.symbol.color = {"RGB": rgb}
                if field == "RouteDamageClass":
                    for grp in sym.renderer.groups:
                        for itm in grp.items:
                            val = str(itm.values[0][0])
                            rgb = damage_class_colors.get(val)
                            if rgb:
                                itm.symbol.color = {"RGB": rgb}
                lyr.symbology = sym
        except Exception:
            ok = False
    if not ok:
        print("Symbolize Emergency Response Corridor Network manually by EmergencyAccessClass.")


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
                if col in (
                    "RouteLength_km", "RouteCost", "MinAvailableWidth_m",
                    "CandidateDistance_km", "Class2_Length_km", "Class3_Length_km",
                    "DamageExposureRatio", "RouteOverlapWithPrimary",
                ):
                    fv = safe_float(val)
                    out[col] = f"{fv:.3f}" if fv is not None else ""
                else:
                    out[col] = safe_text(val)
            writer.writerow(out)
    print(f"  Wrote QA CSV: {QA_CSV}")


def build_polyline(nodes: List[int], graph: Graph, sr: arcpy.SpatialReference) -> Optional[arcpy.Polyline]:
    if len(nodes) < 2:
        return None
    arr = arcpy.Array()
    for nid in nodes:
        x, y = graph.node_coord[nid]
        arr.add(arcpy.Point(x, y))
    try:
        return arcpy.Polyline(arr, sr)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 72)
    print("29_emergency_service_accessibility_analysis.py")
    print("=" * 72)

    for path, label in (
        (ROAD_FC, "Road network"),
        (EMERGENCY_SERVICES_FC, "Emergency services"),
        (TARGETS_FC, "Targets"),
    ):
        if not arcpy.Exists(path):
            print(f"ERROR: {label} not found: {path}")
            return 1

    print("Building graph from road network...")
    graph, sr, diag = load_roads_into_graph(ROAD_FC)
    print("  --- Graph construction diagnostics ---")
    print(f"  Road source SR:   {diag['source_sr_name']} (factoryCode={diag['source_sr_code']})")
    print(f"  Working SR:       {WORKING_SR.name} (factoryCode={WORKING_SR.factoryCode})")
    print(f"  Road features read:               {diag['features_read']}")
    print(f"  Road features with valid geometry:{diag['features_valid']}")
    print(f"  Skipped zero-length geometries:   {diag['skipped_zero_length']}")
    print(f"  Graph nodes:                      {len(graph.node_coord)}")
    print(f"  Graph edges:                      {len(graph.edges)}")
    print("  Sample first 5 node coordinates:")
    for nid in list(graph.node_coord.keys())[:5]:
        cx, cy = graph.node_coord[nid]
        print(f"      node {nid}: ({cx:.2f}, {cy:.2f})")

    if len(graph.node_coord) < 10 or len(graph.edges) == 0:
        print("Graph construction failed. Check spatial reference/projection and vertex extraction.")
        return 1

    # Damage sources.
    confirmed = (
        load_damage_sections(CONFIRMED_DAMAGE_ML_FC, "Confirmed_ML", False)
        + load_damage_sections(CONFIRMED_DAMAGE_PROF_FC, "Confirmed_Professor", False)
    )
    validation = load_damage_sections(VALIDATION_DAMAGE_FC, "NeedsValidation", True)
    print("Assigning damage to edges...")
    assign_damage_to_edges(graph, confirmed, validation, sr)

    # Load emergency services.
    svc_oid = get_oid_field(EMERGENCY_SERVICES_FC)
    f_fid = pick_field(EMERGENCY_SERVICES_FC, ["FacilityID"])
    f_fname = pick_field(EMERGENCY_SERVICES_FC, ["FacilityName"])
    f_ftype = pick_field(EMERGENCY_SERVICES_FC, ["FacilityType"])
    svc_fields = [svc_oid, "SHAPE@"]
    for f in (f_fid, f_fname, f_ftype):
        if f and f not in svc_fields:
            svc_fields.append(f)

    services: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(EMERGENCY_SERVICES_FC, svc_fields) as cur:
        for row in cur:
            rec = {svc_fields[i]: row[i] for i in range(len(svc_fields))}
            geom = project_geom_to_working(rec.get("SHAPE@"))
            if geom is None:
                continue
            ftype = safe_text(rec.get(f_ftype)).lower() if f_ftype else ""
            group = FACILITY_GROUP.get(ftype)
            if group is None:
                if "emergency" in ftype or "civil_protection" in ftype or "ambulance" in ftype:
                    group = "coordination"
                else:
                    continue
            nid, snap_d, low_conf = snap_point_to_node(geom, graph)
            if nid is None:
                continue
            services.append(
                {
                    "FacilityID": safe_int(rec.get(f_fid)) if f_fid else safe_int(rec.get(svc_oid)),
                    "FacilityName": safe_text(rec.get(f_fname)) if f_fname else "",
                    "FacilityType": ftype,
                    "ServiceGroup": group,
                    "node": nid,
                    "snap_dist": snap_d,
                    "low_conf_snap": low_conf,
                }
            )
    print(f"  Emergency service centers used: {len(services)}")

    groups_present = {s["ServiceGroup"] for s in services}

    # Load targets.
    tgt_oid = get_oid_field(TARGETS_FC)
    f_tid = pick_field(TARGETS_FC, ["TargetID"])
    f_tname = pick_field(TARGETS_FC, ["TargetName"])
    tgt_fields = [tgt_oid, "SHAPE@"]
    for f in (f_tid, f_tname):
        if f and f not in tgt_fields:
            tgt_fields.append(f)

    targets: List[Dict[str, Any]] = []
    with arcpy.da.SearchCursor(TARGETS_FC, tgt_fields) as cur:
        for row in cur:
            rec = {tgt_fields[i]: row[i] for i in range(len(tgt_fields))}
            geom = project_geom_to_working(rec.get("SHAPE@"))
            if geom is None:
                continue
            nid, snap_d, low_conf = snap_point_to_node(geom, graph)
            targets.append(
                {
                    "TargetID": safe_int(rec.get(f_tid)) if f_tid else safe_int(rec.get(tgt_oid)),
                    "TargetName": safe_text(rec.get(f_tname)) if f_tname else "",
                    "geom": geom,
                    "node": nid,
                    "snap_dist": snap_d,
                    "low_conf_snap": low_conf,
                }
            )
    print(f"  Targets loaded: {len(targets)}")

    # --- Target-based routing ---
    route_rows: List[Dict[str, Any]] = []
    qa_rows: List[Dict[str, Any]] = []
    target_status_rows: List[Dict[str, Any]] = []
    route_id = 0
    no_route_pairs = 0

    # QA counters.
    selected_candidate_count = 0
    skipped_outside_count = 0
    skipped_farther_count = 0
    fallback_used_count = 0
    routes_by_target_group: Counter = Counter()
    target_redundancy_counter: Counter = Counter()

    # Group services by ServiceGroup for screening.
    services_by_group: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for svc in services:
        services_by_group[svc["ServiceGroup"]].append(svc)

    # Maps for the deferred road-priority pass.
    target_overall: Dict[int, str] = {}

    for tgt in targets:
        t_node = tgt["node"]
        if t_node is None:
            continue
        t_xy = graph.node_coord[t_node]

        # --- 1-2. Candidate screening per service group (straight-line node distance). ---
        selected_by_group: Dict[str, List[Dict[str, Any]]] = {}
        for grp in ESSENTIAL_GROUPS:
            grp_services = services_by_group.get(grp, [])
            if not grp_services:
                selected_by_group[grp] = []
                continue
            radius_km = SCREENING_RADIUS_KM.get(grp, 35.0)
            scored = []
            for svc in grp_services:
                sx, sy = graph.node_coord[svc["node"]]
                dist_km = math.hypot(t_xy[0] - sx, t_xy[1] - sy) / 1000.0
                scored.append((dist_km, svc))
            scored.sort(key=lambda x: x[0])
            within = [(d, s) for d, s in scored if d <= radius_km]
            chosen: List[Dict[str, Any]] = []
            if within:
                for d, s in within[:MAX_CANDIDATE_SERVICES_PER_GROUP]:
                    chosen.append({"svc": s, "dist_km": d, "within": True,
                                   "reason": "selected_within_radius"})
                # within-radius but beyond the cap are skipped as farther facilities.
                skipped_farther_count += max(0, len(within) - MAX_CANDIDATE_SERVICES_PER_GROUP)
                skipped_outside_count += len(scored) - len(within)
            else:
                for d, s in scored[:FALLBACK_NEAREST_OUTSIDE_RADIUS]:
                    chosen.append({"svc": s, "dist_km": d, "within": False,
                                   "reason": "outside_radius_fallback"})
                    fallback_used_count += 1
                skipped_outside_count += max(0, len(scored) - FALLBACK_NEAREST_OUTSIDE_RADIUS)
            selected_by_group[grp] = chosen
            selected_candidate_count += len(chosen)

        # --- 3. Route only selected facilities (single-source trees from target). ---
        runA = dijkstra(graph, t_node, allow_eu0=False, allow_class3=False, degraded=False)
        runB = dijkstra(graph, t_node, allow_eu0=True, allow_class3=False, degraded=False)
        runC = dijkstra(graph, t_node, allow_eu0=True, allow_class3=True, degraded=True)
        runs = (
            ("conservative", runA, False),
            ("conservative_low_confidence", runB, False),
            ("degraded_critical", runC, True),
        )

        group_routes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for grp, candidates in selected_by_group.items():
            for cand in candidates:
                svc = cand["svc"]
                s_node = svc["node"]
                chosen_run = None
                scenario = None
                for tag, run, degraded in runs:
                    dist, pred_node, pred_edge = run
                    if s_node in dist and dist[s_node] < float("inf"):
                        scenario = tag
                        chosen_run = (run, degraded)
                        break
                if chosen_run is None:
                    continue
                (dist, pred_node, pred_edge), degraded = chosen_run
                edges = reconstruct_edges(t_node, s_node, pred_node, pred_edge)
                if edges is None:
                    continue
                exposure = route_exposure(edges, graph, confirmed)
                status = classify_access_status(exposure, degraded)
                group_routes[grp].append(
                    {
                        "svc": svc,
                        "cost": dist[s_node],
                        "edges": edges,
                        "exposure": exposure,
                        "status": status,
                        "scenario": scenario,
                        "degraded": degraded,
                        "s_node": s_node,
                        "pred_node": pred_node,
                        "cand_dist": cand["dist_km"],
                        "within": cand["within"],
                        "reason": cand["reason"],
                    }
                )

        # --- 4. Keep best primary + backup route per group (by cost). ---
        group_best: Dict[str, List[Dict[str, Any]]] = {}
        for grp in ESSENTIAL_GROUPS:
            routes = group_routes.get(grp, [])
            routes.sort(key=lambda r: r["cost"])
            group_best[grp] = routes[:ROUTES_PER_GROUP]

        # Per-group redundancy (with overlap proxy) and primary facility names.
        best_status_by_group: Dict[str, str] = {}
        redundancy_by_group: Dict[str, str] = {}
        primary_facility: Dict[str, str] = {}
        for grp in ESSENTIAL_GROUPS:
            if grp not in groups_present:
                best_status_by_group[grp] = "no_facility_available"
                redundancy_by_group[grp] = "critical"
                primary_facility[grp] = ""
                continue
            routes = group_best.get(grp, [])
            if routes:
                statuses = [r["status"] for r in routes]
                best_status_by_group[grp] = min(statuses, key=lambda s: STATUS_RANK.get(s, 99))
                primary_facility[grp] = routes[0]["svc"]["FacilityName"]
                overlap = 0.0
                if len(routes) >= 2:
                    overlap = route_overlap_ratio(
                        routes[0]["exposure"]["edge_set"], routes[1]["exposure"]["edge_set"]
                    )
                redundancy_by_group[grp] = redundancy_level(statuses, overlap)
            else:
                best_status_by_group[grp] = "no_route"
                redundancy_by_group[grp] = "critical"
                primary_facility[grp] = ""
                no_route_pairs += 1

        # --- Emit route rows. ---
        for grp in ESSENTIAL_GROUPS:
            routes = group_best.get(grp, [])
            primary_edges: Set[int] = routes[0]["exposure"]["edge_set"] if routes else set()
            for rank, r in enumerate(routes, start=1):
                route_id += 1
                svc = r["svc"]
                exposure = r["exposure"]
                nodes = node_path(t_node, r["s_node"], r["pred_node"])
                geom = build_polyline(nodes, graph, sr)

                if rank == 1:
                    overlap_primary = 0.0
                else:
                    overlap_primary = route_overlap_ratio(exposure["edge_set"], primary_edges)

                notes: List[str] = []
                if (r["scenario"] == "conservative_low_confidence"
                        or svc["low_conf_snap"] or tgt["low_conf_snap"]):
                    notes.append("low_confidence: non-emergency road or far snap used.")
                if not r["within"]:
                    notes.append("origin facility outside screening radius (fallback).")
                if r["degraded"]:
                    notes.append("degraded scenario: Class 3 traversed (critical bottleneck).")
                if exposure["Validation_Count"] > 0:
                    notes.append(
                        f"{exposure['Validation_Count']} validation-needed section(s) "
                        "crossed (uncertainty)."
                    )
                route_note = " ".join(notes)
                rdc, rdc_label = route_damage_class(exposure)

                row = {
                    "geometry": geom,
                    "RouteID": route_id,
                    "OriginFacilityID": svc["FacilityID"],
                    "OriginName": svc["FacilityName"],
                    "OriginType": svc["FacilityType"],
                    "ServiceGroup": grp,
                    "TargetID": tgt["TargetID"],
                    "TargetName": tgt["TargetName"],
                    "RouteRank": rank,
                    "RouteLength_km": exposure["length_m"] / 1000.0,
                    "RouteCost": r["cost"],
                    "MaxDamageClass": exposure["MaxDamageClass"],
                    "Class1_Count": exposure["Class1_Count"],
                    "Class2_Count": exposure["Class2_Count"],
                    "Class3_Count": exposure["Class3_Count"],
                    "Validation_Count": exposure["Validation_Count"],
                    "MinAvailableWidth_m": exposure["MinAvailableWidth_m"],
                    "RouteDamageClass": rdc,
                    "RouteDamageLabel": rdc_label,
                    "Class1_Length_km": exposure["Class1_Length_m"] / 1000.0,
                    "Class2_Length_km": exposure["Class2_Length_m"] / 1000.0,
                    "Class3_Length_km": exposure["Class3_Length_m"] / 1000.0,
                    "DamageExposureRatio": exposure["DamageExposureRatio"],
                    "CandidateDistance_km": r["cand_dist"],
                    "WithinScreeningRadius": 1 if r["within"] else 0,
                    "SelectionReason": r["reason"],
                    "RouteOverlapWithPrimary": overlap_primary,
                    "AccessStatus": r["status"],
                    "RedundancyLevel": redundancy_by_group.get(grp, "low"),
                    "ScenarioUsed": r["scenario"],
                    "RouteNote": route_note,
                    # internal fields for the deferred road-priority pass
                    "_grp": grp,
                    "_tid": tgt["TargetID"],
                    "_rank": rank,
                    "_status": r["status"],
                    "_degraded": r["degraded"],
                    "_conf_idx": exposure["conf_idx"],
                    "_edge_indices": list(r["edges"]),
                    "TargetAccessStrategy": "",  # for QA, filled below
                }
                route_rows.append(row)
                routes_by_target_group[(tgt["TargetName"], grp)] += 1

        # --- 5. Overall target status. ---
        essential_statuses = [best_status_by_group[g] for g in ESSENTIAL_GROUPS]
        note_parts: List[str] = []
        missing_groups = [g for g in ESSENTIAL_GROUPS
                          if best_status_by_group[g] == "no_facility_available"]
        if missing_groups:
            note_parts.append("No facilities for: " + ", ".join(missing_groups) + ".")

        considered = [s for s in essential_statuses if s != "no_facility_available"]
        any_critical = any(s in ("critical", "no_route") for s in considered)
        any_restricted = any(s == "restricted" for s in considered)
        any_uncertain = any(s == "uncertain" for s in considered)

        if any_critical:
            overall = "critical"
        elif any_restricted:
            overall = "restricted"
        elif any_uncertain:
            overall = "uncertain"
        elif considered and all(
            s in ("accessible", "accessible_with_caution", "partially_restricted")
            for s in considered
        ):
            overall = "accessible" if all(
                s in ("accessible", "accessible_with_caution") for s in considered
            ) else "restricted"
        else:
            overall = "critical" if not considered else "uncertain"

        red_order = {"critical": 0, "low": 1, "medium": 2, "high": 3}
        present_reds = [redundancy_by_group[g] for g in ESSENTIAL_GROUPS if g in groups_present]
        overall_red = min(present_reds, key=lambda x: red_order.get(x, 1)) if present_reds else "critical"

        if overall == "critical":
            priority = 1
        elif overall == "restricted" or overall_red == "low":
            priority = 2
        elif overall == "uncertain" or overall_red == "medium":
            priority = 3
        else:
            priority = 4

        if any_uncertain:
            note_parts.append("Validation-needed damage affects some routes (uncertainty).")

        strategy = build_target_strategy(tgt["TargetName"], overall)
        target_overall[tgt["TargetID"]] = overall
        target_redundancy_counter[overall_red] += 1

        # Backfill TargetAccessStrategy into this target's QA route rows.
        for row in route_rows:
            if row.get("_tid") == tgt["TargetID"]:
                row["TargetAccessStrategy"] = strategy

        target_status_rows.append(
            {
                "geometry": tgt["geom"],
                "TargetID": tgt["TargetID"],
                "TargetName": tgt["TargetName"],
                "BestHealthAccess": best_status_by_group["health_emergency"],
                "BestFireAccess": best_status_by_group["fire_response"],
                "BestSecurityAccess": best_status_by_group["security"],
                "BestCoordinationAccess": best_status_by_group["coordination"],
                "OverallAccessStatus": overall,
                "OverallRedundancy": overall_red,
                "PriorityForIntervention": priority,
                "StatusNote": " ".join(note_parts),
                "TargetAccessStrategy": strategy,
                "PrimaryHealthFacility": primary_facility["health_emergency"],
                "PrimaryFireFacility": primary_facility["fire_response"],
                "PrimarySecurityFacility": primary_facility["security"],
                "PrimaryCoordinationFacility": primary_facility["coordination"],
            }
        )

    # --- Aggregate confirmed-section usage from SELECTED routes only (road priority). ---
    sec_usage: Dict[int, Dict[str, Any]] = {}
    corridor_usage: Dict[int, Dict[str, Any]] = {}
    for row in route_rows:
        is_primary = row["_rank"] == 1
        is_critical_route = row["_status"] == "critical" or row["_degraded"]
        is_restricted_route = row["_status"] == "restricted"
        low_red = row["RedundancyLevel"] in ("low", "critical")
        tgt_crit = target_overall.get(row["_tid"]) == "critical"
        for eidx in row.get("_edge_indices", []):
            c = corridor_usage.setdefault(
                eidx,
                {
                    "targets": set(),
                    "groups": set(),
                    "route_use": 0,
                    "primary_use": 0,
                    "critical_use": 0,
                    "restricted_use": 0,
                    "has_primary": False,
                    "has_critical": False,
                    "has_restricted": False,
                },
            )
            c["targets"].add(row["TargetName"])
            c["groups"].add(row["ServiceGroup"])
            c["route_use"] += 1
            if is_primary:
                c["primary_use"] += 1
                c["has_primary"] = True
            if is_critical_route:
                c["critical_use"] += 1
                c["has_critical"] = True
            if is_restricted_route:
                c["restricted_use"] += 1
                c["has_restricted"] = True
        for ci in row["_conf_idx"]:
            u = sec_usage.setdefault(
                ci,
                {
                    "used": 0, "critical": 0, "primary": False, "restricted": False,
                    "low_red": False, "tgt_crit": False,
                },
            )
            u["used"] += 1
            if is_critical_route:
                u["critical"] += 1
            if is_primary:
                u["primary"] = True
            if is_restricted_route:
                u["restricted"] = True
            if low_red:
                u["low_red"] = True
            if tgt_crit:
                u["tgt_crit"] = True

    # --- Build outputs ---
    create_fc(ROUTES_OUTPUT_FC, "POLYLINE", sr, ROUTE_FIELD_SPECS)
    create_fc(TARGET_STATUS_FC, "POINT", sr, TARGET_FIELD_SPECS)
    create_fc(ROAD_PRIORITY_FC, "POLYLINE", sr, PRIORITY_FIELD_SPECS)
    create_fc(CORRIDOR_OUTPUT_FC, "POLYLINE", sr, CORRIDOR_FIELD_SPECS)

    route_field_names = [n for n, _, _ in ROUTE_FIELD_SPECS]
    route_text_len = {n: l for n, t, l in ROUTE_FIELD_SPECS if t == "TEXT"}
    status_counter: Counter = Counter()
    damage_class_counter: Counter = Counter()
    with arcpy.da.InsertCursor(ROUTES_OUTPUT_FC, ["SHAPE@"] + route_field_names) as ic:
        for row in route_rows:
            if row["geometry"] is None:
                continue
            vals = [row["geometry"]]
            for fn in route_field_names:
                v = row.get(fn)
                if fn in route_text_len and isinstance(v, str):
                    v = truncate_text(v, route_text_len[fn])
                vals.append(v)
            ic.insertRow(vals)
            status_counter[row["AccessStatus"]] += 1
            damage_class_counter[row["RouteDamageClass"]] += 1
            qa_rows.append(
                {
                    "RouteID": row["RouteID"],
                    "OriginName": row["OriginName"],
                    "OriginType": row["OriginType"],
                    "ServiceGroup": row["ServiceGroup"],
                    "TargetName": row["TargetName"],
                    "RouteRank": row["RouteRank"],
                    "RouteLength_km": row["RouteLength_km"],
                    "RouteCost": row["RouteCost"],
                    "MaxDamageClass": row["MaxDamageClass"],
                    "Class1_Count": row["Class1_Count"],
                    "Class2_Count": row["Class2_Count"],
                    "Class3_Count": row["Class3_Count"],
                    "Validation_Count": row["Validation_Count"],
                    "MinAvailableWidth_m": row["MinAvailableWidth_m"],
                    "RouteDamageClass": row["RouteDamageClass"],
                    "RouteDamageLabel": row["RouteDamageLabel"],
                    "CandidateDistance_km": row["CandidateDistance_km"],
                    "WithinScreeningRadius": row["WithinScreeningRadius"],
                    "SelectionReason": row["SelectionReason"],
                    "Class2_Length_km": row["Class2_Length_km"],
                    "Class3_Length_km": row["Class3_Length_km"],
                    "DamageExposureRatio": row["DamageExposureRatio"],
                    "RouteOverlapWithPrimary": row["RouteOverlapWithPrimary"],
                    "AccessStatus": row["AccessStatus"],
                    "RedundancyLevel": row["RedundancyLevel"],
                    "ScenarioUsed": row["ScenarioUsed"],
                    "TargetAccessStrategy": row["TargetAccessStrategy"],
                    "QA_Note": row["RouteNote"],
                }
            )

    target_field_names = [n for n, _, _ in TARGET_FIELD_SPECS]
    target_text_len = {n: l for n, t, l in TARGET_FIELD_SPECS if t == "TEXT"}
    overall_counter: Counter = Counter()
    with arcpy.da.InsertCursor(TARGET_STATUS_FC, ["SHAPE@"] + target_field_names) as ic:
        for row in target_status_rows:
            if row["geometry"] is None:
                continue
            vals = [row["geometry"]]
            for fn in target_field_names:
                v = row.get(fn)
                if fn in target_text_len and isinstance(v, str):
                    v = truncate_text(v, target_text_len[fn])
                vals.append(v)
            ic.insertRow(vals)
            overall_counter[row["OverallAccessStatus"]] += 1

    # Road reopening priority (confirmed sections used by routes only).
    priority_field_names = [n for n, _, _ in PRIORITY_FIELD_SPECS]
    priority_text_len = {n: l for n, t, l in PRIORITY_FIELD_SPECS if t == "TEXT"}
    priority_counter: Counter = Counter()
    priority_id = 0
    with arcpy.da.InsertCursor(ROAD_PRIORITY_FC, ["SHAPE@"] + priority_field_names) as ic:
        for ci, usage in sec_usage.items():
            sec = confirmed[ci]
            if sec["is_validation"]:
                continue
            cls = sec["DamageClass"] or 0
            crit = usage["critical"] > 0
            if cls == 3 or crit or usage["tgt_crit"]:
                plevel = 1
                reason = ("Class 3 / critical-route damage or on a route to a target "
                          "with critical overall access.")
            elif cls == 2 and (usage["primary"] or usage["restricted"] or usage["low_red"]):
                plevel = 2
                reason = "Class 2 damage on primary/restricted/low-redundancy emergency route."
            elif cls == 1 or not usage["primary"]:
                plevel = 3
                reason = "Class 1 damage, or damage affecting only an alternative/backup route."
            else:
                plevel = 3
                reason = "Damage used by an emergency route."
            priority_id += 1
            vals_map = {
                "PriorityID": priority_id,
                "SourceDamageLayer": sec["SourceDamageLayer"],
                "DamageClass": cls,
                "RoadName": sec["RoadName"],
                "RoadType": sec["RoadType"],
                "AvailableWidth_m": sec["AvailableWidth_m"],
                "UsedByRouteCount": usage["used"],
                "CriticalRouteCount": usage["critical"],
                "PriorityLevel": plevel,
                "PriorityReason": reason,
            }
            vals = [sec["geom"]]
            for fn in priority_field_names:
                v = vals_map.get(fn)
                if fn in priority_text_len and isinstance(v, str):
                    v = truncate_text(v, priority_text_len[fn])
                vals.append(v)
            ic.insertRow(vals)
            priority_counter[plevel] += 1

    # Corridor network output from route-used graph edges.
    corridor_field_names = [n for n, _, _ in CORRIDOR_FIELD_SPECS]
    corridor_text_len = {n: l for n, t, l in CORRIDOR_FIELD_SPECS if t == "TEXT"}
    corridor_access_counter: Counter = Counter()
    corridor_damage_counter: Counter = Counter()
    corridor_priority_counter: Counter = Counter()
    no_damage_segments = 0
    confirmed_damage_segments = 0
    validation_segments = 0
    critical_due_to_width = 0
    restricted_due_to_width = 0
    restricted_validation_narrow = 0
    corridor_id = 0
    with arcpy.da.InsertCursor(CORRIDOR_OUTPUT_FC, ["SHAPE@"] + corridor_field_names) as ic:
        for eidx, agg in corridor_usage.items():
            edge = graph.edges[eidx]
            p1 = edge["p1"]
            p2 = edge["p2"]
            arr = arcpy.Array([arcpy.Point(p1[0], p1[1]), arcpy.Point(p2[0], p2[1])])
            geom = arcpy.Polyline(arr, sr)

            rdc, rdl = edge_damage_class(edge)
            val_flag = 1 if edge["touched_validation"] else 0
            road_width = derive_corridor_road_width(edge)
            if rdc == 3:
                min_avail = 0.0
            else:
                avails = [
                    confirmed[i]["AvailableWidth_m"]
                    for i in edge["touched_confirmed"]
                    if confirmed[i].get("AvailableWidth_m") is not None
                ]
                if avails:
                    min_avail = min(avails)
                else:
                    min_avail = road_width

            eu = safe_int(edge.get("eu"), 1) or 1
            eac = classify_corridor_access(eu, rdc, val_flag, min_avail, road_width)
            cost = corridor_cost_factor(eac)
            if eu != 0 and eac == "critical_or_blocked" and min_avail is not None and min_avail < MIN_WIDTH_CRITICAL_M:
                critical_due_to_width += 1
            if eu != 0 and eac == "restricted" and min_avail is not None and min_avail < MIN_WIDTH_RESTRICTED_M:
                restricted_due_to_width += 1
            if eu != 0 and eac == "restricted" and val_flag == 1 and road_width < NARROW_ROAD_M:
                restricted_validation_narrow += 1

            if rdc == 3 or agg["has_critical"]:
                rpl = 1
            elif rdc == 2 or agg["has_restricted"]:
                rpl = 2
            elif rdc == 1:
                rpl = 3
            else:
                rpl = 0

            if eac == "critical_or_blocked":
                note = "Critical corridor segment: severe damage or usable width below emergency threshold."
            elif eac == "restricted":
                note = "Restricted corridor segment: medium damage, narrow road, or reduced available width."
            elif eac == "uncertain_validation_needed":
                note = "Validation-needed damage intersects corridor; field verification required."
            elif eac == "open_with_caution":
                note = "Low-impact damage intersects corridor; access possible with caution."
            elif eac == "not_suitable_for_emergency_vehicle_access":
                note = "Road segment not suitable for emergency vehicle access based on OSM road/access attributes."
            else:
                note = "Undamaged corridor segment used by selected emergency route."

            corridor_id += 1
            vals_map = {
                "CorridorID": corridor_id,
                "SourceRoadOID": edge.get("RoadOID"),
                "RoadName": edge.get("RoadName", ""),
                "RoadType": edge.get("RoadType", ""),
                "RoadGroup": edge.get("RoadGroup", ""),
                "NetworkRole": edge.get("NetworkRole", ""),
                "EmergencyUsable": eu,
                "RoadWidth_m": road_width,
                "TargetsServed": ", ".join(sorted(agg["targets"])),
                "ServiceGroupsServed": ", ".join(sorted(agg["groups"])),
                "RouteUseCount": agg["route_use"],
                "PrimaryRouteUseCount": agg["primary_use"],
                "CriticalRouteUseCount": agg["critical_use"],
                "RouteDamageClass": rdc,
                "RouteDamageLabel": rdl,
                "ValidationFlag": val_flag,
                "MinAvailableWidth_m": min_avail,
                "EmergencyAccessClass": eac,
                "AccessCostFactor": cost,
                "ReopeningPriorityLevel": rpl,
                "CorridorNote": note,
            }
            vals = [geom]
            for fn in corridor_field_names:
                v = vals_map.get(fn)
                if fn in corridor_text_len and isinstance(v, str):
                    v = truncate_text(v, corridor_text_len[fn])
                vals.append(v)
            ic.insertRow(vals)

            corridor_access_counter[eac] += 1
            corridor_damage_counter[rdc] += 1
            corridor_priority_counter[rpl] += 1
            if rdc == 0:
                no_damage_segments += 1
            else:
                confirmed_damage_segments += 1
            if val_flag == 1:
                validation_segments += 1

    write_qa_csv(qa_rows)
    try:
        update_map()
    except Exception as ex:
        print(f"WARNING: map update failed: {ex}")

    # --- QA summary ---
    print("\n" + "=" * 72)
    print("QA SUMMARY — Emergency Service Accessibility")
    print("=" * 72)
    print(f"  Road network used:            {ROAD_FC}")
    print(f"  Roads loaded (edges):         {len(graph.edges)}")
    print(f"  Graph nodes:                  {len(graph.node_coord)}")
    print(f"  Graph edges:                  {len(graph.edges)}")
    print(f"  Emergency service centers:    {len(services)}")
    print(f"  Targets:                      {len(targets)}")
    n_ml = sum(1 for s in confirmed if s['SourceDamageLayer'] == 'Confirmed_ML')
    n_prof = sum(1 for s in confirmed if s['SourceDamageLayer'] == 'Confirmed_Professor')
    print(f"  Confirmed ML sections:        {n_ml}")
    print(f"  Professor damage sections:    {n_prof}")
    print(f"  Validation sections:          {len(validation)}")
    print(f"  Selected candidate facilities (target/group): {selected_candidate_count}")
    print(f"  Skipped facilities (farther within radius):    {skipped_farther_count}")
    print(f"  Skipped facilities (outside radius):           {skipped_outside_count}")
    print(f"  Outside-radius fallback facilities used:       {fallback_used_count}")
    print(f"  Routes created:               {len(route_rows)}")
    print(f"  Corridor segments created:    {len(corridor_usage)}")
    print("  Routes by AccessStatus:")
    for k, v in sorted(status_counter.items(), key=lambda kv: -kv[1]):
        print(f"      - {k}: {v}")
    print("  Routes by RouteDamageClass:")
    for k in (0, 1, 2, 3):
        print(f"      - class {k}: {damage_class_counter.get(k, 0)}")
    print("  Routes by TargetName and ServiceGroup:")
    for (tname, grp), v in sorted(routes_by_target_group.items()):
        print(f"      - {tname} / {grp}: {v}")
    print("  Target status by OverallAccessStatus:")
    for k, v in sorted(overall_counter.items(), key=lambda kv: -kv[1]):
        print(f"      - {k}: {v}")
    print("  Target redundancy counts (OverallRedundancy):")
    for k, v in sorted(target_redundancy_counter.items(), key=lambda kv: -kv[1]):
        print(f"      - {k}: {v}")
    print("  Road reopening priority by PriorityLevel:")
    for k in sorted(priority_counter.keys()):
        print(f"      - PriorityLevel {k}: {priority_counter[k]}")
    print("  Corridor count by EmergencyAccessClass:")
    for k, v in sorted(corridor_access_counter.items(), key=lambda kv: -kv[1]):
        print(f"      - {k}: {v}")
    print("  Corridor count by RouteDamageClass:")
    for k in (0, 1, 2, 3):
        print(f"      - class {k}: {corridor_damage_counter.get(k, 0)}")
    print("  Corridor count by ReopeningPriorityLevel:")
    for k in sorted(corridor_priority_counter.keys()):
        print(f"      - level {k}: {corridor_priority_counter[k]}")
    print(f"  Segments critical due to AvailableWidth_m < {MIN_WIDTH_CRITICAL_M}: {critical_due_to_width}")
    print(f"  Segments restricted due to AvailableWidth_m < {MIN_WIDTH_RESTRICTED_M}: {restricted_due_to_width}")
    print("  Validation-needed narrow-road segments upgraded to restricted: "
          f"{restricted_validation_narrow}")
    print(f"  Route-used segments with no damage:        {no_damage_segments}")
    print(f"  Route-used segments with confirmed damage: {confirmed_damage_segments}")
    print(f"  Route-used segments with validation uncertainty: {validation_segments}")
    print(f"  No-route essential pairs:     {no_route_pairs}")
    print(f"  Routes output:                {ROUTES_OUTPUT_FC}")
    print(f"  Target status output:         {TARGET_STATUS_FC}")
    print(f"  Road priority output:         {ROAD_PRIORITY_FC}")
    print(f"  Corridor output:              {CORRIDOR_OUTPUT_FC}")
    print(f"  QA CSV:                       {QA_CSV}")
    print()
    print("  Methodological note:")
    print("    First-emergency accessibility from emergency service centers to affected")
    print("    targets using the updated road network and BOTH confirmed damage sources.")
    print("    Class 3 is blocked in the conservative scenario; a degraded path is mapped")
    print("    when no conservative path exists. Validation-needed damage is uncertainty,")
    print("    not confirmed blockage.")
    print("    The Emergency Response Corridor Network is a stricter first-emergency")
    print("    scenario. It classifies only the road segments used by selected")
    print("    origin-to-target emergency routes. Confirmed damage, validation")
    print("    uncertainty, available width, road width proxy, and emergency vehicle")
    print("    suitability are combined to identify open, cautious, restricted, and")
    print("    critical corridor segments.")
    print("=" * 72 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())