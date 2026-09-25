# Workflows

## Typical daily workflow

1. Preview and repair missing GPS coordinates using trusted photos captured
   around the same time.
2. Run a first pass on untagged photos. Review nearby Street Art Cities markers
   and use their evidence to identify and tag known artwork.
3. Review every cluster with **Ctrl+Left/Right** for previous/next and **Tab**
   to move between tag fields. Search by tag substring and use autocomplete
   from `data/artists.csv` to apply recurring artist tags quickly.
4. Run a second pass on the now-tagged photos to check whether the same artist
   or artwork already exists on Street Art Cities. Correct obvious GPS drift by
   comparing positions with context photos or Street View, then copy the images
   selected for publication to the temporary folder.

## Generate and review clusters

1. Add and enable one or more photo sources.
2. Set the capture period and ordinary include/exclude tag filters. **Last 24h**
   fills both date and time boundaries using the local clock.
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
`progress.json`. After a page refresh, the generator restores and resumes
polling the newest queued or running run. On completion, the new report is
inserted into **Recent runs** without requiring a page reload.

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
applied directly to one image, the selected images, or every cluster image.
`_unknown` and `_wall` remain available as workflow proposals. The GPS map
shows primary, context, and Street Art Cities positions; drag its target and
preview the move for the selected images. GPS actions show exact files and
before/after values before a separate apply confirmation.

Tags found on every cluster image appear once in **On all photos**, where they
can be removed directly from the complete cluster. Autocomplete lists
`_unknown` and `_wall` before artist entries for underscore queries. Tab and
Shift+Tab move directly between cluster/per-image tag editors, and the first
tag editor receives focus whenever a cluster page opens.

The × button removes an existing tag immediately. **Add**, **Add to all**, and
**Add to selected** also write immediately; pressing Enter in a tag editor is
equivalent to its default Add action. Internal exact plans still provide
fingerprint validation, atomic writes, and change logs. The cluster reloads so
new labels are immediately visible.
When a newly added non-internal tag is absent from `data/artists.csv`, a helper
asks the user to confirm its Street Art Cities slug and Instagram handle before
atomically appending it. Tags beginning with `_` never trigger this helper.

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
The current red target also provides direct **Google Maps** and **Street View**
links that update whenever the target moves.

Street Art Cities candidate status is green for active markers and red for
removed markers. Each candidate links to its marker, its SAC artist page when
an artist slug exists, and the artist's Instagram profile when that handle is
available in `data/artists.csv`.

## Runs

Each run owns a directory containing its config snapshot, manifest, command,
log, progress, preview, JSON report, and Markdown report. Active runs can be
cancelled. Inactive runs can be deleted from the generator after confirmation.
