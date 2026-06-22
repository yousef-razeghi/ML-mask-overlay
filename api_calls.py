"""
api_calls.py
============
Thin client around the NOMAD Oasis REST API.

Rather than repeating the ``requests`` boilerplate in every function, the calls
go through two small helpers (:func:`_query_entries` / :func:`_query_archives`)
that take a query body and hand back the ``data`` list. The public functions
then just shape that data into whatever the caller needs.

Every public function keeps the signature and return value it had before, so
the rest of the toolkit can use this module as a drop-in.
"""

import getpass

import requests

# Default NOMAD entry types used around the lab.
BATCH_TYPE = "HySprint_Batch"
JV_TYPE = "HySprint_JVmeasurement"
EQE_TYPE = "HySprint_EQEmeasurement"
MPPT_TYPE = "HySprint_SimpleMPPTracking"


# --------------------------------------------------------------------------- #
#  Low-level request helpers
# --------------------------------------------------------------------------- #
def _bearer(token):
    """Authorization header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


def _query(url, token, route, body):
    """POST a NOMAD query *body* to *route* and return its ``data`` list."""
    resp = requests.post(f"{url}/{route}", headers=_bearer(token), json=body)
    resp.raise_for_status()
    return resp.json()["data"]


def _query_entries(url, token, body):
    """Run a query against the entry-metadata endpoint."""
    return _query(url, token, "entries/query", body)


def _query_archives(url, token, body):
    """Run a query against the archive endpoint (gives the parsed ``data``)."""
    return _query(url, token, "entries/archive/query", body)


def _make_body(query, required=None, page_size=10000, owner="visible"):
    """Assemble a standard NOMAD query body."""
    return {
        "required": required or {"data": "*"},
        "owner": owner,
        "query": query,
        "pagination": {"page_size": page_size},
    }


def _entry_ids_for_samples(url, token, sample_ids, page_size=10000):
    """Return the entry ids of every entry carrying one of *sample_ids*."""
    body = _make_body(
        {"results.eln.lab_ids:any": sample_ids},
        required={"metadata": "*"},
        page_size=page_size,
    )
    return [entry["entry_id"] for entry in _query_entries(url, token, body)]


def _group_linked_by_sample(linked_data, keep=None):
    """Group archive rows by their first sample's lab id.

    *keep* is an optional ``row -> bool`` predicate. Returns
    ``{lab_id: [(data, metadata), ...]}``.
    """
    grouped = {}
    for row in linked_data:
        if keep is not None and not keep(row):
            continue
        archive = row["archive"]
        lab_id = archive["data"]["samples"][0]["lab_id"]
        grouped.setdefault(lab_id, []).append((archive["data"], archive["metadata"]))
    return grouped


# --------------------------------------------------------------------------- #
#  Caching / auth
# --------------------------------------------------------------------------- #
def init_cache():
    """Cache GET/POST responses locally (ignores the Authorization header)."""
    import requests_cache
    requests_cache.install_cache(
        "my_local_cache",
        allowable_methods=("GET", "POST"),
        ignored_parameters=["Authorization"],
    )


def get_token(url, name=None):
    """Interactively obtain an access token from username + password."""
    user = name if name is not None else input("Username")
    print("Password:\n")
    password = getpass.getpass()
    resp = requests.get(f"{url}/auth/token",
                        params=dict(username=user, password=password))
    resp.raise_for_status()
    return resp.json()["access_token"]


# --------------------------------------------------------------------------- #
#  Uploads / templates
# --------------------------------------------------------------------------- #
def get_all_uploads(url, token, number_of_uploads=20):
    """Most recent uploads of the current user (newest first)."""
    resp = requests.get(
        f"{url}/uploads",
        headers=_bearer(token),
        params=dict(page_size=number_of_uploads,
                    order_by="upload_create_time", order="desc"),
    )
    resp.raise_for_status()
    return resp.json()["data"]


def get_template(url, token, upload_name, method):
    """Archive entries of a given *method* inside a named upload."""
    body = _make_body(
        {"upload_name": upload_name, "entry_type": method},
        page_size=100,
    )
    return _query_archives(url, token, body)


# --------------------------------------------------------------------------- #
#  Batches & samples
# --------------------------------------------------------------------------- #
def get_batch_ids(url, token, batch_type=BATCH_TYPE):
    """Lab ids of every visible batch of *batch_type*."""
    body = _make_body({"entry_type": batch_type})
    data = _query_archives(url, token, body)
    return [d["archive"]["data"]["lab_id"]
            for d in data if "lab_id" in d["archive"]["data"]]


def get_ids_in_batch(url, token, batch_ids, batch_type=BATCH_TYPE):
    """Sample lab ids contained in the given *batch_ids*."""
    body = _make_body(
        {"results.eln.lab_ids:any": batch_ids, "entry_type": batch_type},
        page_size=100,
    )
    data = _query_archives(url, token, body)
    assert len(data) == len(batch_ids)

    sample_ids = []
    for d in data:
        batch_data = d["archive"]["data"]
        for sample in batch_data.get("entities", []):
            sample_ids.append(sample["lab_id"])
    return sample_ids


def get_sample_description(url, token, sample_ids):
    """Map ``lab_id -> description`` for samples that carry a description."""
    body = _make_body({"results.eln.lab_ids:any": sample_ids})
    out = {}
    for entry in _query_entries(url, token, body):
        data = entry["data"]
        desc = data.get("description")
        if desc and desc.strip():
            out[data["lab_id"]] = desc
    return out


def get_sample_entry_links(url, token, sample_ids):
    """Map ``lab_id -> NOMAD GUI url`` for every requested sample (one call)."""
    gui_base = url.split("/api/")[0]  # e.g. https://nomad-hzb-se.de/nomad-oasis
    body = _make_body(
        {"results.eln.lab_ids:any": sample_ids},
        required={"metadata": "*"},
    )

    links = {}
    for entry in _query_entries(url, token, body):
        entry_id = entry.get("entry_id")
        upload_id = entry.get("upload_id")
        if not entry_id or not upload_id:
            continue
        gui_url = (f"{gui_base}/gui/user/uploads/"
                   f"upload/id/{upload_id}/entry/id/{entry_id}")
        lab_ids = (entry.get("results") or {}).get("eln", {}).get("lab_ids", [])
        for lab_id in lab_ids:
            if lab_id in sample_ids:
                links[lab_id] = gui_url
    return links


# --------------------------------------------------------------------------- #
#  Single-entry lookups
# --------------------------------------------------------------------------- #
def get_entry_data(url, token, entry_id):
    """Parsed ``data`` section of one entry."""
    body = _make_body({"entry_id": entry_id},
                      required={"metadata": "*", "data": "*"})
    data = _query_archives(url, token, body)
    assert len(data) == 1, "Entry not found"
    return data[0]["archive"]["data"]


def get_entry_meta_data(url, token, entry_id):
    """Metadata record of one entry."""
    body = _make_body({"entry_id": entry_id},
                      required={"metadata": "*"}, page_size=100)
    data = _query_entries(url, token, body)
    assert len(data) == 1, "Entry not found"
    return data[0]


def get_entryid(url, token, sample_id):
    """Entry id of the (unique) entry for a sample lab id."""
    body = _make_body({"results.eln.lab_ids": sample_id},
                      required={"metadata": "*"}, page_size=100)
    data = _query_entries(url, token, body)
    assert len(data) == 1
    return data[0]["entry_id"]


def get_nomad_ids_of_entry(url, token, sample_id):
    """``(entry_id, upload_id)`` of the (unique) entry for a sample lab id."""
    body = _make_body({"results.eln.lab_ids": sample_id},
                      required={"metadata": "*"}, page_size=100)
    data = _query_entries(url, token, body)
    assert len(data) == 1
    return data[0]["entry_id"], data[0]["upload_id"]


# --------------------------------------------------------------------------- #
#  Reference walking
# --------------------------------------------------------------------------- #
def get_information(url, token, entry_id, path):
    """Follow this entry's references at *path* and return their data."""
    meta = get_entry_meta_data(url, token, entry_id)
    return [
        get_entry_data(url, token, ref.get("target_entry_id"))
        for ref in meta.get("entry_references", [])
        if ref.get("source_path") == path
    ]


def get_setup(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.setup")
    assert data and len(data) == 1, "No Setup found"
    return data[0]


def get_environment(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.environment")
    assert data and len(data) == 1, "No Environment found"
    return data[0]


def get_samples(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.samples.reference")
    assert data and len(data) > 0, "No Samples found"
    return data


# --------------------------------------------------------------------------- #
#  Measurements linked to samples
# --------------------------------------------------------------------------- #
def get_specific_data_of_sample(url, token, sample_id, entry_type, with_meta=False):
    """Archive data of entries (of *entry_type*) that reference one sample."""
    entry_id = get_entryid(url, token, sample_id)
    body = _make_body(
        {"entry_references.target_entry_id": entry_id},
        required={"metadata": "*", "data": "*"}, page_size=100,
    )
    linked = _query_archives(url, token, body)

    out = []
    for row in linked:
        meta = row["archive"]["metadata"]
        if "entry_type" not in meta or entry_type not in meta["entry_type"]:
            continue
        if with_meta:
            out.append((row["archive"]["data"], meta))
        else:
            out.append(row["archive"]["data"])
    return out


def _linked_measurements(url, token, sample_ids, *, entry_type=None,
                         section=None, page_size=10000, keep=None):
    """Shared path: sample ids -> their entries -> linked measurement archives.

    Either *entry_type* or *section* selects the measurement kind.
    """
    entry_ids = _entry_ids_for_samples(url, token, sample_ids, page_size=page_size)

    query = {"entry_references.target_entry_id:any": entry_ids}
    if entry_type is not None:
        query["entry_type"] = entry_type
    if section is not None:
        query["section_defs.definition_qualified_name"] = section

    body = _make_body(query, required={"data": "*", "metadata": "*"},
                      page_size=page_size)
    linked = _query_archives(url, token, body)
    return _group_linked_by_sample(linked, keep=keep)


def get_all_JV(url, token, sample_ids, jv_type=JV_TYPE):
    """``{lab_id: [(data, metadata), ...]}`` of JV measurements per sample."""
    return _linked_measurements(url, token, sample_ids, entry_type=jv_type)


def get_all_eqe(url, token, sample_ids, eqe_type=EQE_TYPE):
    """EQE measurements grouped by sample."""
    return _linked_measurements(url, token, sample_ids, entry_type=eqe_type)


def get_all_mppt(url, token, sample_ids, mppt_type=MPPT_TYPE):
    """MPP-tracking measurements grouped by sample."""
    return _linked_measurements(url, token, sample_ids,
                                entry_type=mppt_type, page_size=100)


def get_all_measurements_except_JV(url, token, sample_ids):
    """Every BaseMeasurement except JV, grouped by sample."""
    def not_jv(row):
        meta = row["archive"]["metadata"]
        return "entry_type" in meta and "JV" not in meta["entry_type"]

    return _linked_measurements(url, token, sample_ids,
                                section="baseclasses.BaseMeasurement",
                                keep=not_jv)


def get_processing_steps(url, token, sample_ids, process_type="baseclasses.BaseProcess"):
    """Processing steps of the samples, ordered by experimental-plan position."""
    entry_ids = _entry_ids_for_samples(url, token, sample_ids)
    body = _make_body(
        {"entry_references.target_entry_id:any": entry_ids,
         "section_defs.definition_qualified_name": process_type},
    )
    steps = [row["archive"]["data"] for row in _query_archives(url, token, body)]
    steps = [s for s in steps if "positon_in_experimental_plan" in s]
    steps.sort(key=lambda s: s["positon_in_experimental_plan"])
    return steps


def get_efficiencies(url, token, sample_ids):
    """``{lab_id: efficiency}`` for samples with a positive solar-cell efficiency."""
    body = {
        "required": {
            "results": {"properties": {"optoelectronic": {"solar_cell": {"efficiency": "*"}}},
                        "eln": {"lab_ids": "*"}},
        },
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids,
                  "results.properties.optoelectronic.solar_cell.efficiency:gt": "0"},
    }
    out = {}
    for row in _query_archives(url, token, body):
        results = row["archive"]["results"]
        lab_id = results["eln"]["lab_ids"][0]
        out[lab_id] = results["properties"]["optoelectronic"]["solar_cell"]["efficiency"]
    return out
