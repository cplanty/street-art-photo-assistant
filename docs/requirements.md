# Requirements

## Functional requirements

1. Configure one or more named local JPEG photo sources.
2. Preview selection by inclusive dates, times, tags, tagged state, and
   missing-GPS state.
3. Group selected photos by normalized tag and geographic proximity.
4. Use `_unknown` for untagged artwork and `_Wall_` for wall-level grouping.
5. Optionally split nearby groups using local OpenCV visual matching.
6. Review clusters in a local browser interface.
7. Apply tag edits directly through exact atomic plans; preview GPS writes and
   log every metadata change.
8. Repair missing GPS using exact same-camera or cross-camera plans.
9. Reject a repair plan when a target or reference file changed.
10. Work fully offline when Street Art Cities matching is disabled.
11. Refresh and compare a selected city only when matching is enabled.
12. Persist configuration, run manifests, progress, reports, and change logs.
13. Expose the replaceable semicolon-separated artist mapping.
14. Open new-artwork proposals in a separate editable local review form.
15. Upload images and submit to the SAC Edits API only after form confirmation,
    retaining a durable receipt and manual-review URL.

## Safety and privacy

- No telemetry, application account, or hosted worker; provider access is
  optional and explicit.
- No personal paths, credentials, photos, or private reference collections.
- Existing GPS is never replaced by the missing-GPS workflow.
- File writes remain inside configured source or run roots.
- Synthetic test images only.
- Network requests have explicit timeouts and errors.

## Out of scope

- Direct publishing, automatic review approval, or bypassing Street Art Cities
  community review.
- Camera import, clock correction, or personal daily automation.
- Private photo archives, catalogues, map collections, and embedding indexes.
- Account management, email, hosted queues, and deployment infrastructure.
- Global visual search and heavyweight model runtimes.

## Acceptance criteria

- A clean environment can install and start the app from the README.
- Local selection and cluster review work with matching disabled.
- Every metadata write has a preview, exact targets, confirmation, and log.
- Same-camera and cross-camera missing-GPS repair are tested.
- Matching-disabled runs make no Street Art Cities requests.
- The repository contains only synthetic fixtures and curated public mapping
  data.
