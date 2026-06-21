# ayon-mcp

A lean, standardized **MCP server for [AYON](https://ayon.app/)** (Ynput) — drive an AYON production server
from any AI agent through one clean interface.

Fourth in a set of single-purpose tracker MCPs, all the **same shape** so an agent (or a migration) can speak
to any of them interchangeably:

> **shotgrid-mcp · ftrack-mcp · kitsu-mcp · ayon-mcp**

## What it gives you (20 tools)

- **One generic CRUD family** over AYON's entities — `find` / `get` / `create` / `update` / `delete`
  (entity types: `folder`, `task`, `product`, `version`, `representation`).
- **Schema / discovery** — `list_projects`, `get_project`, `list_folder_types`, `list_task_types`,
  `list_statuses` (with the canonical mapping), `list_tags`, `get_attributes`, `list_addons`, `whoami`.
- **Typed helpers** — `new_folder` (any folder type), `new_task`, `new_product`, `new_version`, `set_status`.
- **`project_summary`** — a **normalized, cross-tracker snapshot** (counts + per-shot tasks with canonical
  statuses) in the *exact same shape* the other three MCPs emit, so hub tools (verify / migrate / audit) work
  on AYON for free. AYON's **polymorphic folders** are mapped onto sequences/assets/shots by `folder_type`.

## What's standardized here (vs a raw AYON client)

1. **One CRUD family** instead of dozens of typed endpoints — `find("folder", project, {...})` etc.
2. **A two-level `dry_run` on every write** — `"plan"` (client-side echo, contacts nothing) and `"preflight"`
   (resolves references + validates statuses against live data, returns a before→after diff and an
   `ok`/`would_fail` verdict — **writes nothing**). Optional `MCP_PLAN_LOG=/path.jsonl` records every plan.
3. **Canonical statuses** — AYON's per-project statuses (Not ready / In progress / Pending review / Approved…)
   are mapped to the shared `todo/wip/done/review/approved` set, so cross-tracker logic is uniform.
4. **The normalized `project_summary` contract** — identical to shotgrid/ftrack/kitsu-mcp.

## Install

```bash
pip install ayon-python-api fastmcp
```

## Configure (env only — no secrets in source)

```bash
export AYON_SERVER_URL="http://your-ayon:5000"
export AYON_API_KEY="<a service / API key>"      # create one in AYON ▸ user ▸ API keys
```

Add to Claude Code / any MCP client:

```bash
claude mcp add ayon \
  -e AYON_SERVER_URL=$AYON_SERVER_URL \
  -e AYON_API_KEY=$AYON_API_KEY \
  -- python /path/to/ayon-mcp/server.py
```

## Part of a tracker-MCP set — migrate between platforms

Because all four MCPs emit the **same `project_summary`** and accept a uniform tool surface, an agent with two
loaded can **copy a project across trackers** (read source → write target) with no bespoke script — the
clone-as-hub thesis as four shippable MCPs. AYON's own `ayon-ftrack` addon does exactly this kind of sync
internally; this MCP exposes AYON to the same agent-driven workflow.

## AYON specifics handled

- **Polymorphic folder hierarchy** — folders *are* Episode/Sequence/Shot/Asset (any nesting); `new_folder`
  takes a `folder_type`, and `project_summary` flattens them onto the cross-tracker shape.
- **Product → Version → Representation** publish model — first-class in the CRUD family.
- **Anatomy / attributes** — `get_attributes(entity_type)` + `get_project` expose the schema-as-data.

Built on the official **`ayon-python-api`** (`ayon_api`) + `fastmcp`. MIT. Credits **Ynput** for AYON
(AGPL server, open source).

---

Built by **John Huikku** · [alienrobot.com](https://alienrobot.com)
