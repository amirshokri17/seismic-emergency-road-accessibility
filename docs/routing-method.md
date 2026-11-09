# Custom Dijkstra routing — documented implementation

**Source examined:** `29_emergency_service_accessibility_analysis.py` from the original GPEM scripts archive. This file has not yet been uploaded to the public repository; the description below reflects the source previously reviewed.

## Edge-weight model

For a traversable edge, the original implementation uses

```text
edge_cost = edge_length × damage_multiplier
```

| Edge condition | Multiplier or routing rule |
| --- | --- |
| No confirmed damage / validation flag | ×1.0 |
| Confirmed Class 1 | ×1.5 |
| Confirmed Class 2 | ×5.0 |
| Confirmed Class 3 (conservative scenario) | Exclude edge |
| Confirmed Class 3 (degraded scenario) | ×100.0 |
| Unverified candidate without confirmed damage | ×2.0 |

Confirmed classes take precedence over the uncertainty flag. Road emergency-use attributes can affect whether an edge is eligible for traversal.

**Important:** The script does *not* include separate numerical multipliers for road type and available width inside its `edge_cost` function. Width contributes later to access classification. This is narrower than the generalized cost formula described in the academic report.

## Graph creation

- Road linework is represented as graph links between successive polyline vertices / rounded node positions.
- Connections are built as bidirectional edges; direction and turn restrictions are not fully modeled.
- Crossing geometries that are not noded may remain disconnected.
- Facility and target locations must be connected/snap to the modeled graph to produce valid paths.

## How to interpret scenarios

- **Conservative:** Routes avoiding Class 3 blocked roads wherever the graph permits.
- **Degraded:** Highly penalized Class 3 links may appear to identify a possible bottleneck. Their presence is *not proof of passability*.
- **Uncertainty:** Unverified damage candidates affect interpretation and may receive a separate penalty, but are not equivalent to confirmed closures.

The route/corridor post-processing considers damage exposure, usable-width assumptions, uncertain sections and selected emergency origin–destination relationships.

## Limitations

This is an academically developed **emergency accessibility approximation**, not a road-safety certification or realistic travel-time simulation. It omits complete one-way, intersection-turn, vehicle-specific restrictions, live closures and traffic speeds. The current publication does not include the geodatabase needed to reproduce the geographic results.

See [Architecture](architecture.md) and [Publication checklist](../PUBLICATION_CHECKLIST.md).
