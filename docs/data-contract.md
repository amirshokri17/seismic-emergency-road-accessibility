# Input/output data contract

The following feature class names are taken from the **published ArcPy scripts**. They are original study-specific names, not a universal geospatial schema. Paths are resolved under the `GPEM_MAIN_GDB` geodatabase unless a source is supplied as an ArcGIS Pro map layer or via `GPEM_ROADS_SERVICE_URL`.

## Stage-by-stage dependencies

| Script | Important input datasets / layers | Main output |
| --- | --- | --- |
| 26 — Emergency facility cleaning | Raw Overpass/OSM emergency-services point layer in the ArcGIS Pro map; `Roads_Ideal_OSM` or `Roads_In_AerialCoverage_Clipped` | `Emergency_Service_Centers` |
| 27 — OSM road preparation | `eRoads_Ideal_OSM_v2_raw` in the map, or an authorized FeatureServer raw road layer | `Roads_Ideal_OSM_v2_full_clean` |
| 28 — Response targets | `Community`, `Unified_Damage_Points_Final`, confirmed/uncertain road sections, `Roads_Ideal_OSM_v2_full_clean`, and optional manually digitized targets | `Emergency_Response_Targets` and `Emergency_Response_Targets_ManualDigitizing` where applicable |
| 29 — Emergency accessibility | `Roads_Ideal_OSM_v2_full_clean`, `Emergency_Service_Centers`, `Emergency_Response_Targets`, `Unified_Damage_RoadSections_Confirmed_Assessed`, `Roads_Damage_FromTableOnly`, `Unified_Damage_RoadSections_NeedsValidation_Assessed` | `Emergency_Accessibility_Routes`, `Emergency_Target_Accessibility_Status`, `Emergency_Road_Reopening_Priority`, `Emergency_Response_Corridor_Network` |
| 31 — Reopening priority refresh | `Emergency_Response_Corridor_Network`, `Unified_Damage_RoadSections_Confirmed_Assessed`, `Roads_Damage_FromTableOnly`, `Unified_Damage_RoadSections_NeedsValidation_Assessed` | Rebuilds `Emergency_Road_Reopening_Priority` |

## Interpretation and provenance

- Script 29 builds a graph from the **cleaned road network** and attaches confirmed and validation-needed road-damage evidence.
- The `Unified_Damage_...` and `Roads_Damage_FromTableOnly` feature classes were created or prepared in earlier project stages **not republished here**.
- The scripts use the field names and fallback candidates coded in each file. They do not auto-create missing source layers or resolve every schema discrepancy.
- Raw OSM road and emergency-facility geometry require appropriate coordinate systems; routing internally works in the metric **EPSG:3065** coordinate system.
- The report contains scenario-based building damage results for Norcia and 25 municipalities, but those calculations are outside these five Part II scripts.

## QA exports

The scripts write QA CSV files under `GPEM_QA_DIR` (default `qa` in the current working directory). These files describe processing outcomes; the repository does **not** bundle original case-study QA CSVs or quantitative route-count tables.

## Public data availability

The original project geodatabase, satellite imagery, road-damage evidence, high-resolution maps, and target coordinates are not included. No synthetic layer is represented as a measured project result.

If a standalone reusable demo is developed later, it should be labeled distinctly from the original study results and not substituted for the actual analysis.
