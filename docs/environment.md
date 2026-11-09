# Environment and execution notes

The original selected scripts use **ArcGIS Pro with ArcPy** on Windows, together with project-specific feature classes and spatial data. The precise ArcGIS Pro, Python and package versions were not recorded in the supplied script archive, so this repository does not invent a reproducible lockfile.

## Before running an original script

1. Work from a disposable copy of the original geodatabase and ArcGIS project.
2. Confirm each input feature class exists and inspect the schema, coordinate reference system, and field names.
3. Review hardcoded local paths (including `APRX_PATH`, `MAIN_GDB` and CSV output paths) and hosted service addresses.
4. Review `CLEAR_OUTPUT = True` and `arcpy.env.overwriteOutput = True`: scripts may delete/recreate outputs.
5. Use the Python environment bundled with an appropriate ArcGIS Pro installation.
6. Verify generated routes, topological connectivity and QA exports against original GIS layers before drawing conclusions.

## Not a one-command reproducible pipeline

This curated code selection depends on original, unpublished input datasets. It cannot be executed end-to-end as a standalone package; it documents the implemented engineering strategies.

No `requirements.txt` is asserted as a complete installation specification because `arcpy` belongs to the ArcGIS Pro environment and the other GIS dependencies depend on that installation.
