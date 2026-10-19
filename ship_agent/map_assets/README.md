# Leaflet map viewer

The viewer template, JavaScript helpers, marker, and boundary data were copied
from `ShipClassification/demo` for the VesselWatch recording demo. The viewer
retains the original layout and uses saved predictions from immutable map
snapshots. It does not contact a classifier or query the original dataset.

`vendor/` contains Leaflet 1.9.4, its image assets, and its license. Boundary
provenance is recorded in `data/vietnam_maritime_boundaries.sources.json`.
OpenStreetMap base tiles still require internet access and retain attribution.

Local changes to the template automatically open the filtered results and hide
live inference and human review controls for the read-only demo. The backend
embeds the selected observations and verified original crops when creating a map.
Only a small iframe wrapper is attached to chat, never this full viewer.
