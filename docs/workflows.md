# Workflows

## Generate and review clusters

1. Add and enable one or more photo sources.
2. Set the capture period and ordinary include/exclude tag filters.
3. Configure Street Art Cities and visual matching, or leave both disabled for
   an offline run.
4. Select **Preview selection**.
5. Optionally preview and apply missing-GPS repairs.
6. Add an optional run label and select **Refresh & run**.
7. Open the completed run from Recent runs.

Changing any source or filter invalidates the preview, GPS plan, and report
action. Disabled actions are grey.

Generate displays the persisted stage, percentage, item count, warnings, and a
bounded live log tail. Progress survives a page refresh because each run writes
`progress.json`. On completion, the new report is inserted into **Recent runs**
without requiring a page reload.

The adjacent **Cancel** button is enabled only while the current Generate run
is queued or running. Cancellation terminates that run and preserves its
cancelled status in **Recent runs**.

Editing the optional run label after selection preview does not invalidate the
preview or disable **Refresh & run**.

The report opens on the cluster dashboard. Selecting a cluster opens a
resizable two-pane workspace: local photos and tag controls are on the left;
GPS positioning and optional Street Art Cities evidence are on the right.
Dashboard headings sort by index, tag, capture time, photo count, or SAC
status. Previous/Next and **Ctrl+Left/Right** follow that dashboard order.

## Compare with Street Art Cities

Enable **Compare with Street Art Cities**, choose or enter a lowercase city
slug, and run the report. The run refreshes the city's complete public marker
set, then considers only markers within `matching.candidate_radius_m` of each
cluster. Same-artist candidates rank before other nearby markers.

Enable visual matching to download and locally compare a bounded number of
candidate reference images. A failed or invalid image is shown on that
candidate and does not discard the rest of the report. See
[Street Art Cities integration](sac-integration.md).

## Repair missing GPS

Target roles identify sources whose missing coordinates may be changed.
Reference roles identify trusted GPS-bearing photos. A source can have both
roles. Preview lists every target, reference, status, and capture-time
difference. Apply replays only that persisted fingerprinted plan and logs every
completed write.

## Edit a cluster

The detail page reloads current tags and coordinates from disk. Drag the
vertical divider to resize the two columns and a horizontal photo divider to
resize previews. Every image shows its filename, current tags, proposals,
artist-assisted free-form input, Explorer/default-app actions, and a full-size
link.

Primary photos are selected by default; context photos are not. Tags can be
previewed for one image, the selected images, or every cluster image.
`_unknown` and `_wall` remain available as workflow proposals. The GPS map
shows primary, context, and Street Art Cities positions; drag its target and
preview the move for the selected images. Tag and GPS actions always show exact
files and before/after values before a separate apply confirmation.

Tags found on every cluster image appear once in **On all photos**, where they
can be previewed for removal from the complete cluster. Autocomplete lists
`_unknown` and `_wall` before artist entries for underscore queries. Tab and
Shift+Tab move directly between cluster/per-image tag editors.

To fix one image independently, click its blue/grey map point to select it,
view its thumbnail, and drag it. The map shows the number of pending markers
and an **Apply** action. Moving the red target enables a green **Apply to all**
action. Both actions build the exact plan internally, show the file/coordinate
confirmation, and only then write. Multiple independently moved points retain
distinct destination coordinates.

The bundled Leaflet map starts with an offline coordinate grid when Street Art
Cities matching is disabled. OpenStreetMap, Esri satellite, OpenTopoMap, and
CARTO base maps can be selected as network display context; their tiles are
never used as proposal or matching evidence.

## Runs

Each run owns a directory containing its config snapshot, manifest, command,
log, progress, preview, JSON report, and Markdown report. Active runs can be
cancelled. Inactive runs can be deleted from the generator after confirmation.
