# Public repository review checklist

**Current state:** The GitHub repository is public and contains five **configuration-safe adaptations** of original project scripts. The user chose to keep it public during preparation.

## Completed

- [x] Select five strong GIS automation/routing/priority scripts; exclude exploratory ML-training scripts.
- [x] Remove hardcoded personal Windows paths from the selected Python scripts.
- [x] Replace the project-specific ArcGIS FeatureServer fallback with a configurable URL.
- [x] Make deletion/recreation of existing **final** outputs opt-in via `GPEM_CLEAR_OUTPUT` (not a full dry-run).
- [x] Document actual Dijkstra damage-cost multipliers and the separate role of road width.
- [x] Compile all five scripts and add unit/static tests for the actual routing core.
- [x] Verify each GitHub source file matches the prepared publication-safe version.
- [x] Record SHA-256 checksums and describe all configuration changes.
- [x] Explain ArcGIS Pro and data prerequisites without claiming full reproducibility.

## Remaining before promoting widely

- [ ] Confirm all contributors' permission to release the collaborative code and settle individual attribution.
- [ ] Choose a source-code license only after confirming who holds the rights.
- [ ] Check rights for maps, OSM-derived data, imagery, and any future data samples.
- [ ] Confirm whether the 42-page academic report may be published in full.
- [ ] Receive and verify the intended public WebGIS URL and anonymous layer access.
- [ ] Add approved high-resolution project maps and a verified public WebGIS link.
- [ ] Review final technical claims against the original GIS outputs, not only source-code tests.
- [ ] Keep current repository public only with awareness that code is immediately visible to other users.

**Warning:** Source scripts may still modify map state or fixed-name temporary layers even with `GPEM_CLEAR_OUTPUT=false`. Always use disposable GIS workspaces.
