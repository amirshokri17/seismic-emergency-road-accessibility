# Scope and limitations

This repository is an academic geospatial decision-support portfolio, **not** an operational emergency navigation application.

- **Input completeness:** Original geodatabases, validated damage sections and ArcGIS projects are not included.
- **Road topology:** Geometry endpoints/vertices and rounded node keys approximate graph connectivity; crossing edges may be disconnected if they do not share a modeled node.
- **Bidirectional assumption:** The graph does not fully represent turn restrictions, vehicle constraints and one-way traffic regulations.
- **Damage matching:** Spatial matching/proximity between road-damage observations and road links can introduce uncertainty.
- **Measured width:** Where measured widths were absent, lane-based estimates or road-type proxies were used.
- **Routing costs:** The implemented Dijkstra edge cost uses length multiplied by damage/uncertainty penalties; width is not a separate numerical edge-cost multiplier.
- **Degraded-route interpretation:** A route that includes Class 3 links is not proof of emergency vehicle passage.
- **Validation:** The complete ArcPy analysis has not been rerun independently from the curated script package.
- **Reopening priorities:** Relative intervention attention is not equivalent to engineering safety approval, repair design, cost estimation or verified road status.
- **Selective publication:** Exploratory ML candidate screening is not presented as a successful automatic damage detection system.

See the [routing method](routing-method.md), [architecture](architecture.md) and [publication checklist](../PUBLICATION_CHECKLIST.md).
