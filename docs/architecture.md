# Technical architecture

This repository documents a selected part of the original GPEM group project. It deliberately distinguishes **the documented historical workflow** from the **source scripts selected for publication**.

## Data and processing layers

| Stage | Source or selected script | Role | Key dependency |
| --- | --- | --- | --- |
| OSM road-network preparation | `27_clean_roads_ideal_osm_v2.py` | Preserve minor-road continuity; standardize road classes and usability | Original OSM-derived roads / ArcGIS feature layer |
| Emergency centers | `26_clean_emergency_service_centers.py` | Clean, categorize, and QA emergency service origins | Original point layers |
| Response targets | `28_create_emergency_response_targets.py` | Establish Amatrice, Accumoli, Illica destination points | Local GIS features |
| Damage integration | Earlier work, not republished | Associate provided and visually reviewed damage records with network sections | Confirmed and validation-needed road sections |
| Graph and routing | `29_emergency_service_accessibility_analysis.py` | Build graph; route with custom Dijkstra; derive target status and response corridors | Prepared roads, facilities, targets, damaged road sections |
| Reopening priorities | `31_update_road_reopening_priority_from_corridors.py` | Link confirmed damage to selected corridors and classify reopening attention | Corridor layer and confirmed road damage |
| Publication | GIS maps / WebGIS | Communicate spatial results and uncertain areas | Actual GIS outputs; public link pending |

## Engineering strategy

### 1. Preserve relevant local roads

The first network-cleaning approach removed minor roads too aggressively. The revised approach retains roads such as residential, service, track and other local access categories, while marking their operational suitability in fields. This avoids confusing visual simplification with network completeness.

### 2. Separate evidence from uncertainty

Provided reference damage and visually verified candidate damage were treated as confirmed within the project workflow. Unverified candidates were retained as *validation-needed* observations, not automatically treated as closures.

This public code selection does not include the experimental imagery/ML prototype. The report documents that broader stage; the repository does not claim its automatic reliability.

### 3. Optimize response routes

The custom graph implementation selects least-cost paths, using distance modified by damage and uncertainty penalties. Conservative scenarios reject confirmed Class 3 links; degraded scenarios may traverse them at very high cost to expose potential access bottlenecks.

### 4. Translate routes into operational priorities

Road links on selected response corridors were analyzed for damage, width-based usability and corridor importance. The resulting Priority 1–3 classes communicate relative reopening attention rather than certified safe access or construction schedules.

## Reproducibility boundary

The five original scripts alone are **not** an end-to-end reproducible pipeline. They assume the ArcGIS Pro environment, original geodatabase schemas, coordinate systems and prerequisite input layers. The report and published documentation describe the steps without inventing missing data or results.
