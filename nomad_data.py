"""
nomad_data.py
=============
Integration layer that gives the ROI/JV app exactly the NOMAD operations it
needs, built on top of the lab's existing ``api_calls`` and ``utils`` modules.

It adds the few things those modules don't already cover:

* listing the raw image files (PL TIFFs) that live inside a batch's uploads,
* listing the raw group-JV ``.txt`` files in the same uploads,
* downloading a single raw file,
* pushing the finished products (overlay PNG, ROI TIFFs, per-device JV txt,
  manifest.json) back into the batch's upload folder.

Everything that talks to the live NOMAD Oasis REST API is collected here and
marked with ``# LIVE:`` so it is easy to adjust to your instance. The raw
file-tree endpoints (``rawdir`` / ``raw``) follow the standard NOMAD Oasis API;
if your Oasis differs, only this file needs to change — the notebook calls
these wrappers and nothing else.

The batch / sample / JV-entry helpers simply delegate to ``api_calls`` so they
behave identically to the rest of the toolkit.
"""

import io
import time
import posixpath
from zipfile import ZipFile

import requests

import api_calls
import utils

URL_API = utils.URL_API
URL_BASE = utils.URL_BASE

# File extensions we treat as selectable mother images / as JV group files.
IMAGE_EXTS = (".tif", ".tiff", ".png")
JV_EXTS = (".txt",)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
#  Batches & samples  (thin delegates to api_calls)
# --------------------------------------------------------------------------- #
def list_batches(url, token):
    """All visible batch lab-ids (newest-relevant ordering left to NOMAD)."""
    return api_calls.get_batch_ids(url, token)


def list_samples_in_batch(url, token, batch_id):
    """Sample lab-ids contained in a single batch."""
    return api_calls.get_ids_in_batch(url, token, [batch_id])


# Diagnostics from the most recent listing call — the app prints these so a
# "0 images" result is never silent. Read after list_image_files / list_jv_files.
LAST_DIAGNOSTICS = []


def _entries_metadata(url, token, sample_ids):
    """Raw entry-metadata records for every entry carrying one of *sample_ids*.

    One query; returns the list of entry dicts (each has ``upload_id``,
    ``entry_id``, ``mainfile``, ``results`` …). No strict 1-per-sample assert,
    so samples with several entries are handled.
    """
    body = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": list(sample_ids)},
        "pagination": {"page_size": 10000},
    }
    resp = requests.post(f"{url}/entries/query", headers=_auth(token), json=body)
    resp.raise_for_status()
    return resp.json()["data"]


def uploads_for_batch(url, token, sample_ids):
    """Return ``[(upload_id, sample_lab_id), ...]`` distinct uploads for a batch.

    Resolved from a single entry-metadata query (robust to multiple entries per
    sample), so it does not rely on a unique-entry assumption.
    """
    pairs = []
    seen = set()
    for e in _entries_metadata(url, token, sample_ids):
        uid = e.get("upload_id")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        lab_ids = ((e.get("results") or {}).get("eln", {}) or {}).get("lab_ids", []) or []
        owner = next((l for l in lab_ids if l in set(sample_ids)),
                     (lab_ids[0] if lab_ids else (sample_ids[0] if sample_ids else None)))
        pairs.append((uid, owner))
    return pairs


# --------------------------------------------------------------------------- #
#  Raw file tree  (LIVE NOMAD Oasis endpoint — shape-tolerant)
# --------------------------------------------------------------------------- #
def _rawdir_node(url, token, upload_id, path=""):
    """GET one rawdir level and return its directory node, tolerating the
    different JSON shapes NOMAD builds return (``directory_metadata`` at the
    top level, or nested under ``data``)."""
    resp = requests.get(
        f"{url}/uploads/{upload_id}/rawdir/{path}",
        headers=_auth(token),
        params={"page_size": 1000, "include_entry_info": "false"},
    )
    resp.raise_for_status()
    j = resp.json()
    return (j.get("directory_metadata")
            or (j.get("data") or {}).get("directory_metadata")
            or j.get("data")
            or j)


def list_raw_files(url, token, upload_id, path="", diag=None, _depth=0):
    """Recursively list raw files under *path*. Returns ``[{name, path, size}]``.

    Records any per-directory error into *diag* instead of failing silently.
    """
    out = []
    try:
        node = _rawdir_node(url, token, upload_id, path)
    except Exception as e:
        if diag is not None:
            diag.append(f"  rawdir error on {upload_id}/{path or '.'}: {e}")
        return out
    for item in node.get("content", []) or []:
        name = item.get("name", "")
        child = posixpath.join(path, name) if path else name
        is_file = item.get("is_file")
        if is_file is None:                       # infer when the flag is absent
            is_file = ("content" not in item)
        if is_file:
            out.append({"name": name, "path": child, "size": item.get("size", 0)})
        elif _depth < 4:
            out.extend(list_raw_files(url, token, upload_id, child, diag, _depth + 1))
    return out


def list_image_files(url, token, sample_ids, exts=IMAGE_EXTS):
    """Selectable mother-image files across a batch's uploads.

    Tries raw files first; if none match, falls back to entry *mainfiles* with
    an image extension (covers images stored as parsed entries). Returns
    ``[{"label", "name", "path", "upload_id", "sample_id", "size"}]``.
    Diagnostics for the run are left in :data:`LAST_DIAGNOSTICS`.
    """
    diag = [f"{len(sample_ids)} sample(s) in batch"]
    uploads = uploads_for_batch(url, token, sample_ids)
    diag.append(f"{len(uploads)} upload(s) resolved")
    out = []
    seen = set()
    for uid, owner in uploads:
        files = list_raw_files(url, token, uid, diag=diag)
        diag.append(f"  upload {uid}: {len(files)} raw file(s)")
        for f in files:
            if (not exts) or f["name"].lower().endswith(tuple(exts)):
                key = (uid, f["path"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"label": f"{f['name']}  ({owner})", "name": f["name"],
                            "path": f["path"], "upload_id": uid,
                            "sample_id": owner, "size": f["size"]})

    if not out:                                   # fallback: image entries' mainfiles
        diag.append("no matching raw files; trying entry mainfiles")
        for e in _entries_metadata(url, token, sample_ids):
            mf = e.get("mainfile") or ""
            uid = e.get("upload_id")
            if not mf or not uid:
                continue
            if exts and not mf.lower().endswith(tuple(exts)):
                continue
            key = (uid, mf)
            if key in seen:
                continue
            seen.add(key)
            lab_ids = ((e.get("results") or {}).get("eln", {}) or {}).get("lab_ids", []) or []
            owner = lab_ids[0] if lab_ids else (sample_ids[0] if sample_ids else None)
            out.append({"label": f"{mf.rsplit('/', 1)[-1]}  ({owner})",
                        "name": mf.rsplit("/", 1)[-1], "path": mf,
                        "upload_id": uid, "sample_id": owner, "size": 0})
        diag.append(f"mainfile fallback found {len(out)} image(s)")

    diag.append(f"=> {len(out)} image(s) shown")
    LAST_DIAGNOSTICS[:] = diag
    out.sort(key=lambda d: d["name"])
    return out


def list_jv_files(url, token, sample_ids, exts=JV_EXTS):
    """Group-JV ``.txt`` files across a batch's uploads.

    Filters to names that look like JV files (contain ``jv`` or a ``C-N``
    token). Diagnostics are left in :data:`LAST_DIAGNOSTICS`.
    """
    import re
    diag = [f"{len(sample_ids)} sample(s) in batch"]
    uploads = uploads_for_batch(url, token, sample_ids)
    diag.append(f"{len(uploads)} upload(s) resolved")
    out = []
    seen = set()
    for uid, owner in uploads:
        files = list_raw_files(url, token, uid, diag=diag)
        for f in files:
            low = f["name"].lower()
            if low.endswith(tuple(exts)) and ("jv" in low or re.search(r"c-\d+", low)):
                key = (uid, f["path"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"name": f["name"], "path": f["path"], "upload_id": uid,
                            "sample_id": owner, "size": f["size"]})
    diag.append(f"=> {len(out)} JV file(s)")
    LAST_DIAGNOSTICS[:] = diag
    out.sort(key=lambda d: d["name"])
    return out


def browse_files(url, token, sample_ids, exts=None):
    """Every file in the batch's uploads (optionally filtered by *exts*), with
    full relative path — for manual browsing when auto-detection misses files
    nested in subfolders. Returns ``[{label, name, path, upload_id, sample_id, size}]``
    where *label* is the full path so the folder structure is visible."""
    diag = [f"{len(sample_ids)} sample(s) in batch"]
    uploads = uploads_for_batch(url, token, sample_ids)
    diag.append(f"{len(uploads)} upload(s) resolved")
    out = []
    seen = set()
    for uid, owner in uploads:
        for f in list_raw_files(url, token, uid, diag=diag):
            if exts and not f["name"].lower().endswith(tuple(exts)):
                continue
            key = (uid, f["path"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"label": f"{f['path']}  ({owner})", "name": f["name"],
                        "path": f["path"], "upload_id": uid,
                        "sample_id": owner, "size": f["size"]})
    diag.append(f"=> {len(out)} file(s)")
    LAST_DIAGNOSTICS[:] = diag
    out.sort(key=lambda d: d["path"])
    return out


def download_raw_file(url, token, upload_id, raw_path):
    """Download one raw file's bytes. Uses ``GET /uploads/{id}/raw/{path}``."""
    # LIVE: NOMAD Oasis raw-file download.
    resp = requests.get(
        f"{url}/uploads/{upload_id}/raw/{raw_path}",
        headers=_auth(token),
    )
    resp.raise_for_status()
    return resp.content


# --------------------------------------------------------------------------- #
#  JV via measurement entries (alternative source, if files aren't raw)
# --------------------------------------------------------------------------- #
def jv_entries_for_batch(url, token, sample_ids):
    """``{sample_id: [(data, metadata), ...]}`` of JV measurement entries.

    A fallback / cross-check for :func:`list_jv_files` when the group JV text
    is attached as a parsed measurement rather than a raw file. Delegates to
    ``api_calls.get_all_JV``.
    """
    return api_calls.get_all_JV(url, token, sample_ids)


# --------------------------------------------------------------------------- #
#  Push products back into the batch folder
# --------------------------------------------------------------------------- #
def upload_products(url, token, upload_id, files, subfolder, process=True,
                    out_widget=None):
    """Zip *files* and PUT them into *upload_id* under *subfolder*, then process.

    *files* is ``{relative_path: bytes}``. The relative paths are placed under
    ``subfolder`` (e.g. ``roi_jv_export_2026-06-11_1530/``) so a re-run never
    overwrites an earlier one — that is where the date/time stamp lives.

    Mirrors the upload routine in ``utils.upload_files_for_samples`` (PUT the
    zip to ``/uploads/{id}/raw/`` then POST the process action) so it behaves
    like the rest of the toolkit.
    """
    def _log(msg):
        if out_widget is not None:
            with out_widget:
                print(msg)
        else:
            print(msg)

    buf = io.BytesIO()
    with ZipFile(buf, "w") as zf:
        for rel, data in files.items():
            zf.writestr(posixpath.join(subfolder, rel), data)

    # LIVE: PUT the zip into the upload's raw tree.
    resp = requests.put(
        f"{url}/uploads/{upload_id}/raw/",
        data={"wait_for_processing": False},
        headers=_auth(token),
        files={"file": ("products.zip", buf.getvalue(), "application/zip")},
    )
    resp.raise_for_status()
    _log(f"Uploaded {len(files)} files to upload {upload_id} under {subfolder}/")

    if process:
        # LIVE: trigger processing and wait for it to finish.
        requests.post(f"{url}/uploads/{upload_id}/action/process", headers=_auth(token))
        for _ in range(60):
            time.sleep(2)
            st = requests.get(f"{url}/uploads/{upload_id}", headers=_auth(token))
            if not st.json()["data"]["process_running"]:
                break
        _log("NOMAD finished processing the upload.")
    return subfolder
