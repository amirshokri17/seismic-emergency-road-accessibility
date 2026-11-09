# Changes from the original project scripts

The five published scripts retain the original GIS processing and routing algorithms; they are **not** byte-for-byte identical to the course-project archive.

| Change | Before (original) | Now (public version) | Reason |
| --- | --- | --- | --- |
| ArcGIS Pro project | Hardcoded Windows path in a user profile | `GPEM_APRX_PATH`, default `CURRENT` | Avoid exposing personal paths and improve portability |
| Main geodatabase | Hardcoded project `.gdb` path | `GPEM_MAIN_GDB`, with nonfunctional placeholder | Explicit required configuration |
| QA CSV location | Hardcoded course-directory path | `GPEM_QA_DIR`, default `qa` | Avoid personal local folders |
| Output recreation | `CLEAR_OUTPUT = True` | `GPEM_CLEAR_OUTPUT`, default false | Avoid accidental deletion of final outputs |
| Script 27 hosted roads | Fixed hosted FeatureServer URL fallback | `GPEM_ROADS_SERVICE_URL`, default empty, with clear missing-source error | Do not expose or depend on a project-specific service |

## Unchanged technical behavior

- OSM road classification and width-proxy strategy.
- Point/feature preparation and QA methodologies.
- Graph construction and Dijkstra's algorithm in Script 29.
- Numerical damage multipliers, conservative/degraded routing scenarios, snapping and corridor interpretation.
- Reopening-priority logic in Script 31.

## Verification

- All five published scripts passed Python parsing/compilation checks.
- Each GitHub file was compared character-by-character with its prepared publication-safe source.
- SHA-256 checksums are in [scripts/PUBLIC_SHA256.txt](../scripts/PUBLIC_SHA256.txt).
- No end-to-end ArcGIS Pro execution is asserted because the private project geodatabase is not included.

The experimental image/ML scripts are omitted from the public technical code selection. The academic report describes the larger project.
