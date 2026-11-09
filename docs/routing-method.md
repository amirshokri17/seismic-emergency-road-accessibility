# Custom Dijkstra routing — implemented method

**Published implementation:** [Script 29](../scripts/29_emergency_service_accessibility_analysis.py). Its numerical routing logic is retained from the original team project; publication-specific path configuration and the final-output deletion default are the only changes.

## 1. Graph construction

- Road line features become edges between successive vertices, with rounded metric node keys.
- A bidirectional adjacency list connects nodes. Full one-way rules, turn restrictions, speed and live traffic are not modeled.
- Emergency service origins and destination targets are connected/snapped to modeled road nodes.
- Invalid or non-noded road crossings may appear disconnected even if geometries seem to intersect on a map.

## 2. Numerical routing cost

For each traversable edge:

```text
edge_cost = edge_length × damage_multiplier
```

| Condition | Multiplier / treatment |
| --- | --- |
| No confirmed damage and no validation warning | ×1 |
| Confirmed Class 1 | ×1.5 |
| Confirmed Class 2 | ×5 |
| Confirmed Class 3, conservative scenario | Edge excluded |
| Confirmed Class 3, degraded scenario | ×100 |
| Validation-needed only (no confirmed class) | ×2 |

Confirmed class takes precedence over validation-only warning. Emergency-use flags can render an edge ineligible for standard emergency routing.

The implementation uses **Dijkstra's shortest-path algorithm** on non-negative edge weights. It is a least-cost routing model, not shortest estimated travel time.

**Important discrepancy with the report's generalized equation:** Road-type and road-width terms do **not** appear as separate numerical factors in `edge_cost()`. Road width is used later to interpret and classify route and corridor usability.

## 3. Scenarios

- **Conservative:** High-impact Class 3 edges are excluded; accessibility may fail if no alternative exists.
- **Degraded:** These edges may be traversed with ×100 penalty to expose possible bottlenecks. This is **not** evidence that blocked roads are safe or physically passable.
- **Uncertain:** Non-verified damage candidates are handled as uncertain evidence, not confirmed closures.

## 4. Corridor interpretation

Outputs include selected service-to-target routes, target accessibility assessments and an emergency corridor network. Damage exposure, available-width assumptions and uncertainty affect subsequent classifications. [Script 31](../scripts/31_update_road_reopening_priority_from_corridors.py) links confirmed damaged road sections to these corridors for reopening priorities.

## 5. Tests and limits

The tests in [tests/test_routing_core.py](../tests/test_routing_core.py) extract the *actual* Graph/Dijkstra definitions without ArcPy and check penalties, blocked-edge avoidance, degraded routing and emergency-use flags. They do **not** validate the geodatabase, ArcGIS operations, geographic accuracy or road safety.

See [Architecture](architecture.md), [Data contract](data-contract.md), and [Limitations](limitations.md).
