# Environment and execution notes

The original GPEM analyses were built with **ArcGIS Pro / ArcPy**, Python and project-specific GIS datasets on Windows.

The public scripts now use configurable environment variables for project paths; **algorithmic logic is not rewritten**. The versions of ArcGIS Pro and other original libraries were not established from the supplied source archive, so this repository does not claim a fully reproducible package or pin invented versions.

## Environment configuration

See [Configuration](configuration.md). The important variables are:

- `GPEM_APRX_PATH` (ArcGIS Pro project; defaults to `CURRENT` inside ArcGIS Pro)
- `GPEM_MAIN_GDB` (required input/output geodatabase; default is a nonfunctional placeholder)
- `GPEM_QA_DIR` (QA CSV output folder)
- `GPEM_ROADS_SERVICE_URL` (optional authorized hosted raw OSM roads source)
- `GPEM_CLEAR_OUTPUT` (final-output deletion opt-in; defaults to false)

## Before running an ArcPy script

1. Work in a disposable copy of the project and the geodatabase.
2. Ensure all expected layer names, fields, geometry types and spatial references exist; refer to [Data contract](data-contract.md).
3. Verify the correct map/project is open, or supply a valid `.aprx` path.
4. Review potential temporary-layer deletion, final output recreation and `arcpy.env.overwriteOutput`.
5. Run scripts in a compatible ArcPy Python environment.
6. Inspect QA CSVs and resulting GIS layers before drawing technical conclusions.

## Static checks without ArcPy

```bash
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
```

The tests extract and exercise the actual Dijkstra/Graph definitions from Script 29 through the Python AST. **Passing these tests does not confirm geospatial matching, snapping, real-world passability or an end-to-end ArcPy execution.**
