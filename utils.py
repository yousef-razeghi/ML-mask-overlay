"""
utils.py
========
Shared constants and helpers: measurement-type handling, file-name plumbing,
chunked reads from the browser FileInput, and the NOMAD upload routine.

Public names (constants and functions) are unchanged so the rest of the toolkit
keeps importing them as before.
"""

import os
import time
from io import BytesIO
from zipfile import ZipFile

import requests


# =============================== configuration ============================== #
# Measurement type tags. "hy" stays first (it is the catch-all default); the
# rest are kept alphabetically sorted.
_OTHER_TYPES = ["jv", "eqe", "mppt", "sem", "xrd", "xps", "nups", "he-ups",
                "cfsys", "abspl", "pes", "nmr", "trpl", "trspv", "pli"]
MEASUREMENT_TYPES = ["hy"] + sorted(_OTHER_TYPES)

# Anything in this set is reported as a single "pes" type.
PES_ALIASES = ["nups", "he-ups", "cfsys", "xps"]

URL_BASE = "https://nomad-hzb-se.de"
URL_API = f"{URL_BASE}/nomad-oasis/api/v1"
TOKEN = os.environ.get("NOMAD_CLIENT_ACCESS_TOKEN", "")

# Default type when nothing matches.
_DEFAULT_TYPE = "hy"


def _auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


# ============================ file-name handling ============================ #
def get_normalized_type(file_name):
    """Guess the measurement type from a file name (PES aliases collapse to pes)."""
    lowered = file_name.lower()
    for mtype in MEASUREMENT_TYPES:
        if mtype in lowered:
            return "pes" if mtype in PES_ALIASES else mtype
    return _DEFAULT_TYPE


def get_file_extension(filename):
    """Trailing extension of a file name (without the dot)."""
    return filename.split(".")[-1]


def create_nomad_filename(sample_id, original_filename, measurement_type, file_extension):
    """Build a NOMAD-compliant name, e.g. ``HZB_SeNa_1_1_C-1.JV_7.jv.txt``."""
    return f"{sample_id}.{original_filename}.{measurement_type}.{file_extension}"


def extract_filenames_from_vuetify(file_data_list):
    """Pull the ``name`` field out of ipyvuetify FileInput entries."""
    return [item["name"] for item in file_data_list
            if isinstance(item, dict) and "name" in item]


def categorize_files(filenames, measurement_types):
    """Split file names into (recognized, unrecognized, has-extra-dots) lists.

    A name is "recognized" if any measurement-type keyword appears in it; a name
    is flagged for dots if its stem still contains a period.
    """
    recognized, unrecognized, with_dots = [], [], []

    for filename in filenames:
        stem = os.path.splitext(filename)[0]
        if "." in stem:
            with_dots.append(filename)

        lowered = filename.lower()
        if any(keyword in lowered for keyword in measurement_types):
            recognized.append(filename)
        else:
            unrecognized.append(filename)

    return recognized, unrecognized, with_dots


# ===================== chunked read from the FileInput ====================== #
def read_file_from_widget(file_input_widget, file_index, on_complete, on_error=None,
                          chunk_size=512 * 1024, out_widget=None):
    """Read a file from an ipyvuetify FileInput without blocking the kernel.

    The widget streams the bytes back in chunks over its comm; we reassemble
    them and call ``on_complete(bytes)`` at the end (or ``on_error(str)``).
    """
    def _log(text):
        if out_widget:
            with out_widget:
                print(text)

    try:
        info = file_input_widget.file_info[file_index]
        file_size = info["size"]
        file_name = info["name"]
        buffer = bytearray(file_size)
        position = 0

        _log(f"[DEBUG] Starting read: {file_name} ({file_size} bytes)")

        def request_next():
            nonlocal position
            if position >= file_size:
                _log(f"[DEBUG] Read complete: {file_name}")
                on_complete(bytes(buffer))
                return

            length = min(chunk_size, file_size - position)

            class ChunkListener:
                def __init__(self):
                    self.version = file_input_widget.version

                def handle_chunk(self, content, raw):
                    nonlocal position
                    chunk = bytes(raw)
                    start = content["offset"]
                    buffer[start:start + len(chunk)] = chunk
                    position += len(chunk)
                    if out_widget:
                        with out_widget:
                            print(f"[DEBUG] {file_name}: {int(position / file_size * 100)}%")
                    request_next()

            file_input_widget.chunk_listeners[file_index] = ChunkListener()
            file_input_widget.send({
                "method": "read",
                "args": [{"file_index": file_index, "offset": position,
                          "length": length, "id": file_index}],
            })

        request_next()

    except Exception as exc:
        _log(f"[ERROR] read_file_from_widget: {exc}")
        if on_error:
            on_error(str(exc))


# ============================== NOMAD uploads =============================== #
def _target_filename(sample_id, file_name, file_data, file_type_dict):
    """Work out the destination file name inside the upload archive."""
    if file_data.get("is_json"):
        return f"{sample_id}.{file_data['name']}"

    sample_types = file_type_dict.get(sample_id, {})
    measurement_type = sample_types.get(file_name, "hy")

    extension = get_file_extension(file_name)
    base = ".".join(file_name.split(".")[:-1])
    if measurement_type == "jv" and file_data.get("epoch_time"):
        base = f"{file_data['epoch_time']}_{base}"

    return create_nomad_filename(sample_id, base, measurement_type, extension)


def upload_files_for_samples(sample_files_dict, file_type_dict, uploaded_files_data,
                             get_nomad_ids_of_entry, out_widget):
    """Zip each sample's files into the right NOMAD upload, then process them."""
    import ipywidgets as widgets
    from IPython.display import display

    # One progress step per sample that actually has files.
    total = sum(1 for files in sample_files_dict.values() if files)
    progress = widgets.IntProgress(
        value=0, min=0, max=total, description="Processing:",
        bar_style="info", orientation="horizontal",
        layout=widgets.Layout(width="500px"),
    )
    with out_widget:
        display(progress)

    # --- assemble one in-memory zip per target upload --------------------- #
    archives = {}  # upload_id -> BytesIO
    for sample_id, file_names in sample_files_dict.items():
        if not file_names:
            continue

        entry_id, upload_id = get_nomad_ids_of_entry(URL_API, TOKEN, sample_id)
        time.sleep(0.2)
        archives.setdefault(upload_id, BytesIO())

        for file_name in file_names:
            file_data = uploaded_files_data.get(file_name)
            if file_data is None:
                with out_widget:
                    print(f"Could not find data for file: {file_name}")
                continue

            content = file_data.get("file_content")
            if not content:
                with out_widget:
                    print(f"No content for file: {file_name}")
                continue

            target = _target_filename(sample_id, file_name, file_data, file_type_dict)
            with ZipFile(archives[upload_id], "a") as zf:
                zf.writestr(target, content)

    # --- push and process each upload ------------------------------------- #
    done = 0
    for upload_id, zip_buffer in archives.items():
        try:
            resp = requests.put(
                f"{URL_API}/uploads/{upload_id}/raw/",
                data={"wait_for_processing": False},
                headers=_auth(),
                files={"file": ("data.zip", zip_buffer.getvalue(), "application/json")},
            )
            resp.raise_for_status()
        except Exception as exc:
            with out_widget:
                print(f"Error uploading to {upload_id}: {exc}")
                print("Check access and restart voila!")

        time.sleep(1)
        _process_upload(upload_id, out_widget, progress, done, done + 0.8)
        time.sleep(1)
        _process_upload(upload_id, out_widget, progress, done + 0.8, done + 1)

        done += 1
        progress.value = done

    progress.bar_style = "success"
    with out_widget:
        print("Done!")


def _process_upload(upload_id, out_widget, progress_bar=None, current_value=0, total_value=1):
    """Trigger processing of an upload and wait until NOMAD finishes."""
    requests.post(f"{URL_API}/uploads/{upload_id}/action/process", headers=_auth())

    while True:
        time.sleep(2)
        resp = requests.get(f"{URL_API}/uploads/{upload_id}", headers=_auth())
        if not resp.json()["data"]["process_running"]:
            break
        if progress_bar is not None:
            progress_bar.value = min(current_value + 0.3, total_value)
