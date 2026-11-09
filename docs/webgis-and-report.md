# Published ArcGIS FeatureServer and report context

## Current evidence

The updated academic report is **46 pages** and includes **Section 14, WebGIS Framework and Implementation Plan (pp. 44–46)**. Its Section 14.3 identifies a published ArcGIS FeatureServer named **GPEM_ROAD_MANAGEMENT**:

**[Open the GPEM ArcGIS FeatureServer REST directory](https://services7.arcgis.com/XOvkSqDDbi6QLE5s/arcgis/rest/services/GPEM_ROAD_MANAGEMENT/FeatureServer)**

This address was provided by the project contributor and is printed in the report. The external endpoint could not be independently queried from the review environment. Confirm current anonymous access, layer visibility and permissions before describing it as publicly usable.

## Grouped published layers (reported in Section 14.3)

| Group | Reported layer names | Intended purpose |
| --- | --- | --- |
| Base network and context | OSM Road Network; Emergency Response Targets; Emergency Service Centers | Network and response reference |
| Damage evidence and uncertainty | Ground Truth; Damaged Segments GT; Damage Points Landslide/Debris; Confirmed Damage Sections ML/Manual; Validation Needed Damage Sections | Distinguish provided, acquired and uncertain observations |
| Emergency accessibility | Emergency Target Accessibility Status; Emergency Response Corridor Network | Target access and corridor interpretation |
| Early recovery priority | Emergency Road Reopening Priority | Identify important confirmed damaged corridor sections |
| Additional support | Acc_Agricultural; Acc_Residential; Bet_Agricultural; Bet_Residential | Broader zonal context |

## What has — and has not — been implemented

The report confirms **publication of spatial layers as a FeatureServer** and describes the intended web-service architecture (Figure 14.1, p. 44). It **does not demonstrate a completed dashboard, mobile field app, configured pop-ups or operational web map**. These appear as proposed stages in Section 14.4 and future development in Section 14.6.

A FeatureServer is not a route-planning site. The available-width assumptions, damage classifications and corridor results are **academic scenario-based outputs**, not current travel advice or certified emergency-accessibility information.

## Relationship to the technical repository

The repository highlights the selected ArcPy automation scripts, the custom Dijkstra route-cost implementation and road reopening priority logic, rather than publishing the full report or unsuccessful experimental ML model-training code.

The project report credits **Amirhossein Shokri, Nima Khamsehzadeh, Sildev Kumar Ray and MohammadReza Abolhasani**. A separate, focused PDF portfolio presentation has been prepared for review; it should be added to this public repository only after final figure/attribution approval.
