# Curated original source selection

The five original Python scripts listed below will be committed **only after public-sharing permissions and repository visibility have been checked**. Their algorithms will not be silently modified for publication.

| Script | Stage | Main purpose |
| --- | --- | --- |
| `26_clean_emergency_service_centers.py` | Facilities | Clean and classify emergency response origins |
| `27_clean_roads_ideal_osm_v2.py` | Network | Preserve OSM road coverage and standardize emergency usability |
| `28_create_emergency_response_targets.py` | Targets | Prepare destinations for Amatrice, Accumoli and Illica |
| `29_emergency_service_accessibility_analysis.py` | Routing | Build graph, run Dijkstra and prepare corridor/accessibility outputs |
| `31_update_road_reopening_priority_from_corridors.py` | Priority | Recalculate reopening priorities from response corridors |

The original scripts assume Windows/ArcGIS Pro, hardcoded local project paths and prerequisite layers that are **not included** here.

Do not run against an important working geodatabase without first inspecting overwrite/delete behavior and using a safe copy.

The repository is intentionally not a complete code dump: earlier experimental image/model code is excluded; prerequisite damage layers remain documented in the [architecture](../docs/architecture.md).
