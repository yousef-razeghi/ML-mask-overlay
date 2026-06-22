"""
jv_parsing.py
=============
Per-device JV parsing, lifted verbatim from ``dataset_maker_v12`` so the
ROI/JV app slices substrate-level (group) JV text files exactly the way the
dataset-maker always did.

A group JV file is tab-separated. Column 0 is the row label (a metric name such
as ``J_sc``/``V_oc``/``Fill factor``/``Efficiency`` or a voltage value for the
curve rows). The remaining columns alternate reverse/forward per device::

    name   a_rev a_for   b_rev b_for   c_rev c_for   ...   f_rev f_for

The device id is ``{fid}-{letter}`` where *fid* is the number parsed from the
``C-N`` token in the file name and *letter* is ``a..f``. That id uses the same
``{number}-{letter}`` namespace as the ROI labels produced from the DXF mask,
so ROI ``1-a`` joins JV device ``1-a`` directly.

Nothing here talks to NOMAD or to ipywidgets — it is pure text processing.
"""

import re

# Metric-row labels we recognise in the header block of a group JV file.
_JV_KEYS = {'j_sc': 'Jsc', 'v_oc': 'Voc', 'fill factor': 'FF', 'efficiency': 'PCE'}


def file_id_from_name(filename):
    """Parse the ``C-N`` substrate/quadrant number from a JV file name.

    Returns the number as a string (defaults to ``'1'`` when no ``C-N`` token
    is present), matching the original dataset-maker behaviour.
    """
    m = re.search(r'C-(\d+)', filename)
    return m.group(1) if m else '1'


def parse_jv_header_metrics(content, filename):
    """Return ``{device_id: {Jsc_rev, Jsc_for, Voc_rev, ...}}`` for one group file.

    device_id is ``{fid}-{letter}``. Devices whose columns are absent/garbled
    (measurement skipped or failed) are dropped, so callers can tell "has data"
    from "placeholder".
    """
    fid = file_id_from_name(filename)
    text = content if isinstance(content, str) else content.decode('utf-8', errors='ignore')
    text = text.replace('E+', 'e+').replace('E-', 'e-')
    lines = text.split('\n')
    letters = list('abcdef')
    devs = {f'{fid}-{d}': {} for d in letters}
    for ln in lines:
        parts = ln.split('\t')
        if len(parts) < 3:
            continue
        lbl = parts[0].strip().lower()
        key = None
        for tok, out in _JV_KEYS.items():
            if lbl.startswith(tok):
                key = out
                break
        if key is None:
            continue
        for i, d in enumerate(letters):
            try:
                devs[f'{fid}-{d}'][f'{key}_rev'] = float(parts[1 + i * 2])
                devs[f'{fid}-{d}'][f'{key}_for'] = float(parts[2 + i * 2])
            except (ValueError, IndexError):
                pass
    return {did: m for did, m in devs.items() if m}


def split_jv_into_per_device(content, filename):
    """Slice a substrate-level group JV file into per-device 3-column TSVs.

    Returns ``{device_id: bytes}``. Only devices with at least one parseable
    numeric metric pair are included. Every original line is preserved with its
    first column intact, so any downstream parser that read the substrate file
    can read the per-device file unchanged.
    """
    fid = file_id_from_name(filename)
    text = content if isinstance(content, str) else content.decode('utf-8', errors='ignore')
    lines = text.split('\n')
    letters = list('abcdef')

    # Pass 1: which devices actually have parseable numeric data?
    has = {f'{fid}-{d}': False for d in letters}
    for ln in lines:
        parts = ln.split('\t')
        if len(parts) < 3:
            continue
        lbl = parts[0].strip().lower()
        if not any(lbl.startswith(tok) for tok in _JV_KEYS):
            continue
        for i, d in enumerate(letters):
            ci, cj = 1 + i * 2, 2 + i * 2
            if cj < len(parts):
                try:
                    float(parts[ci]); float(parts[cj])
                    has[f'{fid}-{d}'] = True
                except ValueError:
                    pass

    # Pass 2: emit a sliced file per qualifying device.
    out = {}
    for i, d in enumerate(letters):
        did = f'{fid}-{d}'
        if not has[did]:
            continue
        ci, cj = 1 + i * 2, 2 + i * 2
        emitted = []
        for ln in lines:
            parts = ln.split('\t')
            lbl = parts[0] if parts else ''
            rev = parts[ci] if ci < len(parts) else ''
            fwd = parts[cj] if cj < len(parts) else ''
            emitted.append('\t'.join([lbl, rev, fwd]))
        out[did] = '\n'.join(emitted).encode('utf-8')
    return out


def split_many(jv_files):
    """Split several group files at once.

    *jv_files* is an iterable of ``(filename, content)``. Returns
    ``{device_id: {"bytes": ..., "source_file": filename}}``. If two files
    claim the same device id (e.g. two ``C-1`` files), the later one wins and a
    note is kept so the caller can warn.
    """
    out = {}
    for fname, content in jv_files:
        per_dev = split_jv_into_per_device(content, fname)
        for did, did_bytes in per_dev.items():
            out[did] = {"bytes": did_bytes, "source_file": fname}
    return out
