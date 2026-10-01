---
name: street-art-cities-tagging
description: Preview and submit Street Art Cities marker attribute tags through the official OAuth Edits API. Use for adding festival, project, or other attribute tags to one or more existing SAC artworks.
---

# Street Art Cities tagging

Use `sac_attribute_edits.py` from this skill directory. It implements a
preview/apply workflow for array-valued marker attributes such as
`attributes.festival`.

## Safety and API constraints

- Use the official PKCE OAuth and Edits APIs. Never request, print, copy, or
  persist the user's SAC credentials or OAuth tokens.
- Open OAuth in the normal default browser. Do not create a temporary browser
  profile; it may not contain the user's SAC login.
- OAuth edits from third-party applications are always submitted for review;
  they are never directly applied or auto-approved.
- Do not request the `edits:review` scope and never accept the app's own edits
  through the API. SAC requires a person to inspect and accept each app-made
  change manually from its review link.
- SAC has no documented multi-marker edit or bulk-approval endpoint. One marker
  produces one edit and one manual review.
- During preview, pass known pending edit IDs from prior receipts with
  `--known-edit-id`. The script verifies each edit and marks matching targets
  as already pending. Do not submit duplicate edits while review is
  outstanding.
- Never hardcode event names, marker IDs, or user-specific policy in the
  script. Pass them as command arguments.

## Workflow

1. Determine the exact attribute path and values from a trusted reference
   marker. Preserve capitalization, punctuation, apostrophes, and edition
   numbers exactly.
2. Resolve and report every target marker ID. Do not expand "recent" or other
   ambiguous selection criteria without showing the exact resulting targets.
3. Create a durable preview plan:

   ```powershell
   python .github\skills\street-art-cities-tagging\sac_attribute_edits.py preview `
     --path attributes.festival `
     --value "Festival name" `
     --value "Festival name #11" `
     --marker "https://streetartcities.com/markers/MARKER_ID" `
     --known-edit-id "PRIOR_EDIT_ID" `
     --output ".tmp\sac-festival-plan.json"
   ```

4. Show the user the plan's target count, exact values, no-op targets, and
   proposed edits. Obtain explicit approval for the exact batch unless their
   current request already authorizes those exact targets and values.
5. Apply the approved plan:

   ```powershell
   python .github\skills\street-art-cities-tagging\sac_attribute_edits.py apply `
     --plan ".tmp\sac-festival-plan.json"
   ```

   After submission, have the user, or another approver with the appropriate
   SAC rights, inspect and approve the changes manually from the review links.

6. Report each edit ID, `submitted` status, and review URL. Never describe a
   submitted edit as applied.

The apply command preflights every target before the first submission, skips
matching edits already pending, and rejects a stale plan if the marker changed.
It writes a receipt after every successful request. Use `--resume` only with
that same receipt after a partial failure.

## Artist link enrichment

For audits or edits involving artist links:

- SAC stores **Press, media, blog link** at
  `attributes.press,_media,_blog_link`.
- Treat it as a scalar URL attribute. Set a literal value; do not use the
  array `$add` operation used for festival tags.
- Preserve every non-empty SAC value. Only propose a replacement when the
  current attribute is empty.
- Match a SAC artist's stable `id`/slug to the configured artist CSV's
  `streetartcities_slug`. Never join on display name.
- Read the Instagram value from the matched CSV row. Preserve a complete
  `http://` or `https://` URL; otherwise convert the handle to
  `https://www.instagram.com/<handle>/`.
- Propose an Instagram link only when exactly one non-empty candidate remains.
  Leave unknown artists, missing CSV rows, and ambiguous multi-artist matches
  for manual review.

## Date enrichment

For audits or edits involving creation dates:

- SAC stores **Date created** at `attributes.date_created`.
- Treat it as a scalar date attribute and preserve every non-empty value.
- Display dates in the user's requested calendar format during validation.
  Before submission, encode the approved date in the provider's expected date
  representation without changing its calendar day.
- Never infer a missing date from upload time, marker creation time, EXIF time,
  or nearby artworks. Use only the date explicitly approved by the user.

## Description enrichment

For audits or edits involving artwork descriptions:

- SAC stores the description in the core `description` field, not under
  `attributes`.
- Treat `null`, an empty string, and empty localized public-snapshot shapes such
  as `{"en": ""}` as equivalent empty descriptions during stale-plan
  preflight. Prefer `htmlDescription` when copying a formatted reference
  description into the Edits API's HTML-string field.
- Preserve every non-empty description. Never replace artist-specific text
  with a generic event description.
- Copy the approved reference HTML exactly, including paragraph boundaries,
  punctuation, accents, measurements, dates, and named places.
- Filter explicitly to artwork markers. Do not apply artwork descriptions or
  missing-artist checks to festival, venue, or other place markers.

## Known UploadAssistant fields

The legacy UploadAssistant already provides these SAC fields. Reuse the same
sources and invariants when extending this skill:

| SAC field | Source | Shape and rule |
|---|---|---|
| `artists` | `streetartcities_slug` and display name from the artist CSV | Use the stable slug as identity; never join by display name. |
| `images` | Selected original photo | Preserve original bytes and EXIF when uploading. |
| `description` | Curated artist description | Preserve reviewed text and paragraph normalization. |
| `lat`, `lng` | Photo GPS or approved map location | Never infer a location from an unrelated marker. |
| `attributes.artist_nationality` | Artist `default_attributes` | Tag list; add only reviewed configured values. |
| `attributes.artwork_style` | Artist `default_attributes` | Tag list; add only reviewed configured values. |
| `attributes.artwork_type` | Artist `default_attributes` | Scalar tag; preserve a non-empty marker value. |
| `attributes.artwork_subject` | Artist `default_attributes` | Tag list; add only reviewed configured values. |
| `attributes.source` | Artist `default_attributes` | Scalar URL; preserve a non-empty marker value. |
| `attributes.press,_media,_blog_link` | Artist CSV Instagram | Scalar URL; follow the artist-link rules above. |
| `attributes.date_created` | Explicitly approved artwork date | Scalar date; follow the date rules above. |

Live SAC data may also contain provider- or EXIF-derived attributes such as
`camera_used`, `exif_read`, `last_seen`, and `keywords`. UploadAssistant does
not curate those as artist defaults. Treat them as read-only context unless the
user explicitly requests a separately validated workflow.

## Multi-field enrichment

For audits that combine multiple approved fields:

- When one marker needs multiple approved scalar changes, combine them into one
  edit action map so the reviewer sees and approves one coherent edit.
- Always produce the complete read-only validation list before creating the
  edit plan. Include current values, proposed values, and explicit no-action
  reasons.
