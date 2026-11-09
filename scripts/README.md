# Selected GIS automation and routing scripts

This folder contains five **publication-safe adaptations** of the original GPEM scripts. The algorithms are preserved; only local configuration, the hosted-road fallback and final-output deletion default were changed. These are **not** raw, byte-identical archive copies.

| Script | Stage | Main role |
| --- | --- | --- |
| [26_clean_emergency_service_centers.py](26_clean_emergency_service_centers.py) | Origins | Classify and QA emergency service facilities |
| [27_clean_roads_ideal_osm_v2.py](27_clean_roads_ideal_osm_v2.py) | Network | Preserve local OSM links; assign usability and width proxies |
| [28_create_emergency_response_targets.py](28_create_emergency_response_targets.py) | Targets | Prepare Amatrice, Accumoli and Illica response targets |
| [29_emergency_service_accessibility_analysis.py](29_emergency_service_accessibility_analysis.py) | Routing | Build the graph, run Dijkstra, derive routes, corridors and accessibility |
| [31_update_road_reopening_priority_from_corridors.py](31_update_road_reopening_priority_from_corridors.py) | Priorities | Recalculate reopening priorities from confirmed corridor damage |

The scripts depend on the original ArcGIS project, geodatabase fields and earlier prepared damage-section layers. **The five scripts alone do not form a reproducible end-to-end pipeline.**

### Before running

1. Install ArcGIS Pro and use its compatible ArcPy environment.
2. Configure the required environment variables in [Configuration](../docs/configuration.md).
3. Make a **disposable** copy of input geodatabases and the map project.
4. Check all expected layer names and field schemas, and consider the effects of temporary imports and map-layer changes.
5. Review `GPEM_CLEAR_OUTPUT`: it defaults to false for final outputs, but this is not a dry-run mode.

### What is and is not verified

The uploaded files were checked against their prepared publication-safe sources. Standard Python syntax and eight lightweight Dijkstra/static tests passed locally. The full ArcPy pipeline was not executed independently here; it requires original data and licensed software.

- [Published file SHA-256 checksums](PUBLIC_SHA256.txt)
- [Source change log](../docs/source-changes.md)
- [Routing model details](../docs/routing-method.md)
- [Input/output layer names](../docs/data-contract.md)

The experimental ML-training code is intentionally outside this repository's scope. The academic report describes the broader damage-evidence workflow.
