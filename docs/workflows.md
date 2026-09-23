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

The detail page reloads current tags and coordinates from disk. Primary photos
are selected by default for manual positioning; context photos are not. Tag and
GPS actions first show exact files and before/after values, then require a
separate confirmation.

## Runs

Each run owns a directory containing its config snapshot, manifest, command,
log, preview, JSON report, and Markdown report. Active runs can be cancelled.
Inactive runs can be deleted from the generator after confirmation.
