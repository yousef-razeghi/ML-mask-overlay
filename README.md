# PL ROI → JV Assignment (NOMAD NORTH)

Drop this whole folder into a NOMAD NORTH workspace and open
`ROI_JV_NOMAD_app.ipynb` (works in Jupyter and under Voila). Run the two cells.

## Authentication (multi-user)
Per-user, no shared credentials. On NOMAD NORTH each user's session carries their own
`NOMAD_CLIENT_ACCESS_TOKEN`; the app reads it at startup and **auto-connects as that user**,
so anyone who is signed in just opens the app and sees only the data their account allows.
No username/password is ever entered or stored. The Token field is an optional override only.

## What's in the folder
- `ROI_JV_NOMAD_app.ipynb` — the app (setup cell + engine/integration cell).
- `cell_layout_5x5.dxf` — the bundled 5×5 cell mask (no upload needed).
- `nomad_data.py` — NOMAD integration layer (batches, image files, JV files, download, product upload).
- `jv_parsing.py` — per-device JV splitting, lifted verbatim from `dataset_maker_v12`.
- `helmholtz_theme.py`, `api_calls.py`, `utils.py`, `bootstrap.py` — your existing modules, unchanged.

## Workflow in the app
1. Pick a **Batch** (type to auto-filter the list), tick/untick **only tiff images**, then press **Load batch** → the batch's images appear in the **Image** dropdown.
2. Pick an **Image** → **Load image** → Preview 1. Magnifier, corner-snap, SAM/top-view, undo/redo, ROI tweaking — all unchanged.
3. **Overlay mask** → Preview 3 shows the ROIs; tweak as needed.
4. **Export ROI** → cropped-ROI **thumbnails** appear under the previews (plus the original zip download).
5. **Load JV files** → splits the batch's group JV files into per-device JVs (`{number}-{letter}`).
6. **Assign ROIs ↔ JVs** → joins ROI `1-a` ↔ device `1-a`, builds `manifest.json`.
7. **Export products → NOMAD** → pushes overlay PNG + ROI TIFFs + per-device JV txt + `manifest.json`
   to the image's upload, under `roi_jv_export_<YYYY-MM-DD_HHMMSS>/` (date/time stamp avoids duplicates).
   A local `.zip` of the same products is always offered as a backup.

## The few things to verify on NORTH (can't be tested off-instance)
Everything offline-computable (DXF→ROI→TIFF, JV split, label join, manifest, naming) is tested and works.
These touch the live Oasis API and are isolated in `nomad_data.py` (marked `# LIVE:`):

1. **Raw-file listing/download** — uses the standard `GET /uploads/{id}/rawdir/{path}` and
   `GET /uploads/{id}/raw/{path}`. If your Oasis returns a different JSON shape, adjust
   `list_raw_files` / `download_raw_file` only.
2. **Where PL images live** — assumed to be raw image files (`.tif/.tiff/.png`) inside the
   samples' uploads. If they're attached as a measurement entry instead, point `list_image_files`
   at that entry type (helpers in `api_calls` are ready for it).
3. **Quadrant ↔ `C-N` convention** — the mask quadrants are `1..4` and JV device IDs come from the
   `C-N` token in each group-JV filename. The app joins by exact label, so any mismatch shows up as
   *unassigned* ROIs/devices in the Assign table (never a silent wrong pairing). Confirm your lab's
   quadrant numbering matches `C-1..C-4`.
4. **Product upload target** — products go to the loaded image's `upload_id`. Change the target in
   `export_to_nomad` if you want them elsewhere.

No existing feature was removed or changed; only the TIFF/DXF file-upload inputs were replaced by the
NOMAD batch/image selectors, and the DXF is now bundled.
