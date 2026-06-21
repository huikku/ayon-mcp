#!/usr/bin/env python3
"""
ayon-mcp — a lean, standardized MCP server for AYON (Ynput).

Fourth in the tracker-MCP set (shotgrid-mcp · ftrack-mcp · kitsu-mcp · ayon-mcp):
same shape — one generic CRUD family + schema/discovery + a few typed helpers,
a two-level `dry_run` on every write, and a normalized `project_summary` so the
same agent/migration code works across all four.

AYON specifics handled here:
- the **polymorphic folder hierarchy** (folders are Episode/Sequence/Shot/Asset…)
- the **product → version → representation** publish model
- statuses mapped to the cross-tracker canonical set (todo/wip/done/review/approved)

Auth (env only, no secrets in source):
  AYON_SERVER_URL   e.g. http://10.0.0.72:5000
  AYON_API_KEY      a service/api key (or access token)
"""
import os, json, datetime
from fastmcp import FastMCP
import ayon_api

mcp = FastMCP("ayon-mcp")
PLAN_LOG = os.environ.get("MCP_PLAN_LOG")

# ----------------------------- connection -----------------------------
_ready = {"v": False}
def _con():
    if not _ready["v"]:
        url = os.environ.get("AYON_SERVER_URL")
        key = os.environ.get("AYON_API_KEY")
        if not url or not key:
            raise RuntimeError("set AYON_SERVER_URL and AYON_API_KEY")
        os.environ["AYON_SERVER_URL"] = url
        os.environ["AYON_API_KEY"] = key
        ayon_api.get_server_version()      # forces the global connection + validates
        _ready["v"] = True
    return ayon_api

def _clean(o):
    if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if isinstance(o, (datetime.datetime, datetime.date)): return o.isoformat()
    return o

# ----------------------------- entity dispatch -----------------------------
ENTS = ("folder", "task", "product", "version", "representation")
def _find_fn(et): return {
    "folder": ayon_api.get_folders, "task": ayon_api.get_tasks,
    "product": ayon_api.get_products, "version": ayon_api.get_versions,
    "representation": ayon_api.get_representations}[et]
def _get_fn(et): return {
    "folder": ayon_api.get_folder_by_id, "task": ayon_api.get_task_by_id,
    "product": ayon_api.get_product_by_id, "version": ayon_api.get_version_by_id,
    "representation": ayon_api.get_representation_by_id}[et]
def _create_fn(et): return getattr(ayon_api, "create_" + et)
def _update_fn(et): return getattr(ayon_api, "update_" + et)
def _delete_fn(et): return getattr(ayon_api, "delete_" + et)

# ----------------------------- canonical statuses -----------------------------
_CANON_STATE = {"not_started": "todo", "blocked": "todo", "in_progress": "wip", "done": "done"}
def _canon_status(name, state=None):
    n = (name or "").lower()
    if "approv" in n: return "approved"
    if "review" in n or "wfa" in n or "pending" in n: return "review"
    if "done" in n or "complete" in n or "final" in n: return "done"
    if "progress" in n or "wip" in n: return "wip"
    if state in _CANON_STATE: return _CANON_STATE[state]
    return "todo"

# ----------------------------- dry-run -----------------------------
def _mode(dry_run):
    if dry_run in (None, False, "", "live"): return "live"
    if dry_run is True or dry_run == "plan": return "plan"
    if dry_run == "preflight": return "preflight"
    raise ValueError("dry_run must be False/'plan'/'preflight'")

def _planlog(rec):
    if PLAN_LOG:
        with open(PLAN_LOG, "a") as f: f.write(json.dumps(_clean(rec)) + "\n")

def _plan(op, **detail):
    rec = {"op": op, "mode": "plan", "would": detail}; _planlog(rec); return rec

def _preflight(op, project, checks, before=None, **detail):
    """real reads, validate, before→after diff, verdict — writes nothing."""
    issues = [c for c in checks if c.get("bad")]
    rec = {"op": op, "mode": "preflight", "project": project, "detail": detail,
           "before": before, "checks": checks,
           "verdict": "would_fail" if issues else "ok",
           "issues": [c["msg"] for c in issues]}
    _planlog(rec); return rec

# ----------------------------- generic CRUD -----------------------------
def find(entity_type: str, project: str, filters: dict = None, fields: list = None, limit: int = 200):
    """Find AYON entities. entity_type in folder|task|product|version|representation.
    filters are passed to the ayon-api getter (e.g. {'folder_types':['Shot']}, {'task_ids':[...]})."""
    _con()
    if entity_type not in ENTS: raise ValueError("entity_type in " + str(ENTS))
    kw = dict(filters or {})
    if fields: kw["fields"] = fields
    out = list(_find_fn(entity_type)(project, **kw))
    return _clean(out[:limit])

def get(entity_type: str, project: str, entity_id: str):
    """Get one AYON entity by id. Arg order matches update/delete: (type, project, id)."""
    _con()
    return _clean(_get_fn(entity_type)(project, entity_id))

def create(entity_type: str, project: str, fields: dict, dry_run=False):
    """Create an AYON entity. fields are the create_<type> kwargs
    (folder: name, folder_type, parent_id; task: name, task_type, folder_id; etc.)."""
    _con(); m = _mode(dry_run); fields = fields or {}
    if m == "plan": return _plan("create", entity=entity_type, project=project, fields=fields)
    if m == "preflight":
        checks = []
        # validate parent / folder reference exists
        for ref_key, ref_et in (("parent_id", "folder"), ("folder_id", "folder"), ("product_id", "product")):
            if fields.get(ref_key):
                try: _get_fn(ref_et)(project, fields[ref_key]); ok = True
                except Exception: ok = False
                checks.append({"check": ref_key, "value": fields[ref_key], "bad": not ok,
                               "msg": f"{ref_key} {fields[ref_key]} not found"})
        return _preflight("create", project, checks, entity=entity_type, fields=fields)
    res = _create_fn(entity_type)(project, **fields)
    return _clean({"created": entity_type, "result": res})

def update(entity_type: str, project: str, entity_id: str, changes: dict, dry_run=False):
    """Update an AYON entity. changes are update_<type> kwargs (e.g. {'status':'In progress'})."""
    _con(); m = _mode(dry_run); changes = changes or {}
    if m == "plan": return _plan("update", entity=entity_type, id=entity_id, changes=changes)
    if m == "preflight":
        try: before = _get_fn(entity_type)(project, entity_id); ok = True
        except Exception: before, ok = None, False
        checks = [{"check": "exists", "bad": not ok, "msg": f"{entity_type} {entity_id} not found"}]
        if ok and "status" in changes:
            valid = [s["name"] for s in _statuses(project)]
            bad = changes["status"] not in valid
            checks.append({"check": "status", "value": changes["status"], "bad": bad,
                           "msg": f"status not in {valid}"})
        return _preflight("update", project, checks, entity=entity_type, id=entity_id, changes=changes,
                          before={"status": (before or {}).get("status")} if before else None)
    _update_fn(entity_type)(project, entity_id, **changes)
    return _clean({"updated": entity_type, "id": entity_id, "changes": changes})

def delete(entity_type: str, project: str, entity_id: str, dry_run=False):
    """Delete an AYON entity (folders cascade their children)."""
    _con(); m = _mode(dry_run)
    if m == "plan": return _plan("delete", entity=entity_type, id=entity_id)
    if m == "preflight":
        try: _get_fn(entity_type)(project, entity_id); ok = True
        except Exception: ok = False
        return _preflight("delete", project,
                          [{"check": "exists", "bad": not ok, "msg": f"{entity_type} {entity_id} not found"}],
                          entity=entity_type, id=entity_id)
    _delete_fn(entity_type)(project, entity_id)
    return {"deleted": entity_type, "id": entity_id}

# ----------------------------- schema / discovery -----------------------------
def whoami():
    """The connected AYON user + server version."""
    _con()
    try: u = ayon_api.get_user()
    except Exception: u = {}
    return _clean({"user": u.get("name"), "is_admin": u.get("isAdmin"),
                   "server": os.environ.get("AYON_SERVER_URL"),
                   "version": ayon_api.get_server_version()})

def list_projects():
    """All projects (name + code + active)."""
    _con()
    return _clean([{ "name": p["name"], "code": p.get("code"), "active": p.get("active")}
                   for p in ayon_api.get_projects(fields={"name", "code", "active"})])

def get_project(name: str):
    """A project + its anatomy summary (folder/task/status types)."""
    _con()
    p = ayon_api.get_project(name)
    return _clean(p)

def _project(name): _con(); return ayon_api.get_project(name) or {}
def list_folder_types(project: str):
    """The project's folder types (Episode/Sequence/Shot/Asset/… — the polymorphic hierarchy)."""
    return _clean(_project(project).get("folderTypes", []))
def list_task_types(project: str):
    """The project's task types."""
    return _clean(_project(project).get("taskTypes", []))
def _statuses(project): return _project(project).get("statuses", [])
def list_statuses(project: str):
    """The project's statuses (+ the canonical mapping each maps to)."""
    return _clean([{**s, "canonical": _canon_status(s.get("name"), s.get("state"))}
                   for s in _statuses(project)])
def list_tags(project: str):
    """The project's tag pool."""
    return _clean(_project(project).get("tags", []))
def get_attributes(entity_type: str):
    """The attribute (custom-field) schema for an entity type (folder|task|version|…)."""
    _con()
    return _clean(ayon_api.get_attributes_for_type(entity_type))
def list_addons():
    """Installed server addons (ftrack/kitsu sync etc. live here)."""
    _con()
    info = ayon_api.get_addons_info()
    return _clean(info)

# ----------------------------- typed helpers (dry_run) -----------------------------
def new_folder(project: str, name: str, folder_type: str = "Folder", parent_id: str = None,
               label: str = None, dry_run=False):
    """Create a folder of a given type (Sequence/Shot/Asset/…)."""
    return create("folder", project, {"name": name, "folder_type": folder_type,
                                      "parent_id": parent_id, "label": label}, dry_run=dry_run)

def new_task(project: str, name: str, task_type: str, folder_id: str,
             assignees: list = None, dry_run=False):
    """Create a task under a folder."""
    return create("task", project, {"name": name, "task_type": task_type,
                                    "folder_id": folder_id, "assignees": assignees or []}, dry_run=dry_run)

def new_product(project: str, name: str, product_type: str, folder_id: str, dry_run=False):
    """Create a product (publish subset: model/rig/anim/render…) under a folder."""
    return create("product", project, {"name": name, "product_type": product_type,
                                       "folder_id": folder_id}, dry_run=dry_run)

def new_version(project: str, product_id: str, version: int, task_id: str = None, dry_run=False):
    """Create a version of a product."""
    return create("version", project, {"version": version, "product_id": product_id,
                                       "task_id": task_id}, dry_run=dry_run)

def set_status(entity_type: str, entity_id: str, project: str, status: str, dry_run=False):
    """Set an entity's status (validated against the project's statuses in preflight)."""
    return update(entity_type, project, entity_id, {"status": status}, dry_run=dry_run)

# ----------------------------- normalized project_summary -----------------------------
_SEQ_TYPES = {"sequence", "episode", "scene"}
_SHOT_TYPES = {"shot"}
_ASSET_TYPES = {"asset", "assetbuild", "library", "character", "prop", "environment"}

def project_summary(project: str):
    """Normalized cross-tracker snapshot — same shape as the other three MCPs.
    Maps AYON's polymorphic folders onto sequences/assets/shots by folder_type."""
    _con()
    folders = list(ayon_api.get_folders(project, fields={"id", "name", "label", "folderType", "path"}))
    tasks = list(ayon_api.get_tasks(project, fields={"id", "name", "taskType", "folderId", "status"}))
    by_folder = {}
    for t in tasks:
        by_folder.setdefault(t["folderId"], []).append(t)
    seqs, assets, shots = {}, {}, {}
    for f in folders:
        ft = (f.get("folderType") or "").lower()
        nm = f.get("name")
        ftasks = {t.get("taskType") or t.get("name"): _canon_status(t.get("status"))
                  for t in by_folder.get(f["id"], [])}
        if ft in _SHOT_TYPES:
            shots[nm] = {"path": f.get("path"), "tasks": ftasks}
        elif ft in _ASSET_TYPES:
            assets[nm] = {"path": f.get("path"), "tasks": ftasks}
        elif ft in _SEQ_TYPES:
            seqs[nm] = {"path": f.get("path")}
    return _clean({
        "tracker": "ayon",
        "project": {"name": project, "code": (ayon_api.get_project(project) or {}).get("code")},
        "counts": {"folders": len(folders), "sequences": len(seqs),
                   "assets": len(assets), "shots": len(shots), "tasks": len(tasks)},
        "sequences": list(seqs.keys()),
        "shots": shots, "assets": assets,
    })

# ----------------------------- register -----------------------------
for _fn in (find, get, create, update, delete,
            whoami, list_projects, get_project, list_folder_types, list_task_types,
            list_statuses, list_tags, get_attributes, list_addons,
            new_folder, new_task, new_product, new_version, set_status, project_summary):
    mcp.tool(_fn)

if __name__ == "__main__":
    mcp.run()
