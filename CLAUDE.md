# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A [Girder](https://girder.readthedocs.io/) plugin (`girder_jsonforms`) that adds JSON-Schema-driven forms
(built on [json-editor](https://github.com/json-editor/json-editor)) for data entry, plus a domain layer on
top for IGSN (sample identifier) minting/registration via DataCite, "Projects" (grant/proposal-style
records with members, samples, instruments), and AIMD (materials data) integration. It ships both a Python
server plugin and a Girder web_client (Backbone + some Vue) frontend bundled with Vite.

## Girder core architecture (upstream)

This is a **Girder 5** plugin. For how Girder core works — the models layer
(`Model`/`AccessControlledModel`, `exposeFields`, metadata), the REST layer
(`Resource`, `autoDescribeRoute`, `@access.*`, `boundHandler`), the plugin/events/settings
systems, and file:line anchors into the upstream source — see the core architecture map in
the sibling `girder` checkout, imported here:

@../girder/CLAUDE.md

Everything below this section is specific to the `girder_jsonforms` plugin; use the imported
map above whenever a question is about core Girder mechanics rather than this plugin.

## How this runs in the stack

This plugin is deployed as `/girder-plugins/05-girder-jsonforms` in the Whole Tale dev stack,
live-mounted into the `girder` service. For the full stack architecture (services, networks,
Traefik routing, sibling-repo plugin composition, gwvolman/instance lifecycle), see the
deployment orchestrator:

@../deploy-dev/CLAUDE.md

## Commands

Server-side (Python), via `tox`:

```bash
tox -e lint          # ruff check .
tox -e pytest        # full test suite with coverage (needs MongoDB + Redis running)
```

Run tests directly with `pytest` (inside the tox/venv environment) once services are up:

```bash
pytest girder_jsonforms/tests/test_entry.py                    # single file
pytest girder_jsonforms/tests/test_entry.py -k test_name       # single test
```

Tests use `pytest-girder`, which requires a running MongoDB (the CI uses `mongo:4.2`) and Redis
(`redis:7`) instance, and provides fixtures such as `server`, `admin`, `user`, `db` — all
girder-specific fixtures come from the `pytest-girder` plugin. `girder_jsonforms/tests/conftest.py`
adds only IGSN-registry fixtures (`local_mode`, `remote_mode`, `igsn_service`, `igsn_metadata`,
`igsn_settings`), all prefixed or named to avoid shadowing the per-module fixtures older test files
define. Set `GIRDER_MAX_CURSOR_TIMEOUT_MS` if cursors time out during tests (CI sets this to `60000`).

Two testing gotchas, both learned the hard way:

- Any test that creates a deposition needs the `eagerWorkerTasks` fixture *if the plugin is loaded
  anywhere in the run*, because `deposition.created` dispatches a girder-worker task and there is no
  broker under test. A module can pass alone and fail in a full run without it.
- Don't mix `server`-backed tests and plain model-level tests in one module; pytest-girder's plugin
  loading is process-global and the plain tests trip over the state it leaves behind. See
  `test_igsn_service.py` (model level) vs `test_igsn_service_rest.py` (server level).

Web client (Backbone/Vue, built with Vite), from `girder_jsonforms/web_client/`:

```bash
npm ci
npm run build     # vite build -> dist/, required before the Python plugin can serve static assets
npm run dev       # vite build --watch
```

The compiled `web_client/dist` assets (UMD JS + CSS) are what `registerPluginStaticContent` in
`girder_jsonforms/__init__.py` serves — after changing web_client source, rebuild before testing
end-to-end in a running Girder instance.

## Architecture

### Plugin entry point

`girder_jsonforms/__init__.py` (`JSONFormsPlugin.load`) is the composition root: it registers all Girder
models (`form`, `entry`, `deposition`, `project`, `prefixcounter`), mounts REST resources on `info["apiRoot"]`,
binds Girder events (uploads, folder deletion, item search, project lifecycle), registers three custom
search modes (`igsn`, `igsnText`, `byCreator`), and serves the built web_client static assets. Most
cross-cutting behavior (e.g., what happens when a file is uploaded, or a project's status changes) is wired
here via `girder.events.bind`, not discoverable from the model/REST files alone.

### Core domain model chain: Form -> FormEntry -> Deposition (IGSN)

- **`models/form.py`** (`Form`): stores a JSON schema (inline or a remote URL) plus metadata like
  `uniqueField`, `pathTemplate`, `serialize`, `postEntryTask`. `materialize()` is the key method — it resolves
  two custom schema extensions before a form can actually be rendered/validated:
  - `enumSource: "girder.formId:<formId>:<valueField>:<titleField>"` — populates a dropdown's enum values by
    pulling entries from another form (see `doc/preload.md` for related `preload` field semantics used for
    dependency pre-population).
  - Schemas reference `$ref`/`definitions` (resolved via `resolve_ref`) for column type inference used by
    CSV/XLSX import/export (`import_entries`, `export_form`).
- **`models/entry.py`** (`FormEntry`): the actual submitted data (`data` dict), validated against the parent
  form's *materialized* schema with `jsonschema`. Every save diffs against the previous version and records a
  `Changeset` (via `jsondiff`). `create_entry`/`update_entry` can also move files/folders from a temporary
  upload location into a `pathTemplate`-derived destination (`handle_source`) and, if `form.serialize` is
  set, dump the entry as a JSON file into the destination folder and optionally push it to Google Drive
  (`handle_serialization`, `events.trigger("gdrive.upload", ...)`).
- **`models/deposition.py`** (`Deposition`): represents a minted IGSN (an identifier for a physical sample),
  with DataCite-schema-shaped `metadata` (validated against `schemas/datacite-v4.5.json`). Depositions are
  created automatically from a `FormEntry` save via the `model.entry.save` event (`register_deposition`) when
  the entry's data requests one (`data["igsn"]["request"]`), using a prefix/suffix scheme managed by
  `PrefixCounter` (prefix format: 2-letter institution + 1-letter sub-institution/lab + 2-letter material +
  1-letter sub-material, validated against the `IGSN_INSTITUTIONS`/`IGSN_MATERIALS` settings). Batches of
  child depositions (e.g. one IGSN per sub-sample) are generated via pluggable `batch_indices_*` strategies in
  `lib/project_helpers.py`, selected by `form_data["igsn"]["batch"]["method"]` (`from_array`, `weihs`,
  `imqcam`, `croom` — these are lab-specific naming conventions, not generic logic).

### Projects

`models/project.py` (`Project`) models a grant/proposal-like entity: members (with ORCID), samples
(IGSNs), instruments, files, and a lifecycle `status` (`draft` -> `under review` -> `accepted`/`rejected`).
Validation uses a hand-rolled JSON schema (`project_schema`) with a custom `objectId` type checker rather
than the model's own `validate()` logic being the source of truth. Project IDs are minted via
`ProjectCounter` (format: 3-letter code + 2-digit year, e.g. `JHU25`). When a project transitions to
`accepted` (`lib/events.py:ensure_group`, bound to `model.project.save`), a Girder Group + Collection are
created for it and the project is registered with ORCID asynchronously
(`worker_plugin/orcid.py:register_project_with_orcid`). Adding/removing `samples` on a project fires
`project.samples_added`/`project.samples_removed` events, handled asynchronously in
`worker_plugin/projects.py` to sync AIMD-visible item metadata under the project's collection.
`Project.igsn_query` builds a regex query matching an IGSN and all of its batch-derived children
(`PREFIX-001`, `PREFIX-001-001`, ...) — used whenever "does this sample belong to this project" needs
answering.

### ORCID (`lib/orcid.py`)

`girder-wholetale` registers production ORCID and the ORCID sandbox as two separate OAuth providers
(`orcid` and `orcid_sandbox`) with separate credentials and callback URLs, and both can be enabled
for login at once. So `providers.idMap["orcid"]` is no longer "the" ORCID — this plugin names the one
it wants via the `jsonforms.orcid_provider` setting, resolved through `lib/orcid.py:get_orcid_provider`.
Both the creator autocomplete (`rest/deposition.py`) and the project research-resource registration
(`worker_plugin/orcid.py`) go through it, and `get_orcid_headers` mints client-credentials tokens from
that provider's own client id/secret. **The default is `orcid`** (production); sandbox instances set it
to `orcid_sandbox`.

The two halves do not move together. Reads work against production as-is, but writing a research
resource needs the `/activities/update` scope, which only `SandboxORCID` requests, so that half is
gated by `jsonforms.orcid_research_resources`, **off by default**.
`worker_plugin/orcid.py:research_resources_enabled` refuses when the setting is off **or** when the
resolved provider does not request the write scope, so accepting a project skips the registration
cleanly rather than 403-ing per project. Turning it on is therefore only meaningful on an instance
pointed at `orcid_sandbox` — with the production default the scope check refuses anyway. That second
check lifts by itself once `/activities/update` is added to `ORCID._AUTH_SCOPES` in girder-wholetale,
at which point the setting alone governs.

### AIMD integration (`rest/aimdl.py`, `worker_plugin/amdee.py`)

`AIMDL` is a REST resource for querying/annotating items as materials-data records for the AIMD platform
(vega chart specs on items, propagating IGSN-tagged items into their owning project's collection via
`propagate_to_projects`/`item_save`). This is enabled/exposed conditionally via the
`jsonforms.aimdl_counts` setting (`PluginSettings.AIMDL_COUNTS`), checked in `add_public_settings`.
`worker_plugin/amdee.py` registers depositions with the external AIMD service asynchronously
(`register_deposition_with_aimd`, triggered off `deposition.created`).

### Settings

All plugin settings live in `settings.py` (`PluginSettings`), each with a Girder
`setting_utilities.validator`/`default`. Notable ones: `IGSN_PREFIX`/`IGSN_CLIENT_ID`/`IGSN_PROVIDER_ID`
(DataCite registration identity), `IGSN_INSTITUTIONS`/`IGSN_MATERIALS` (the controlled vocabularies IGSN
prefixes are validated against), `PROJECTS_COLLECTION_NAME` (the Girder Collection all project submission
folders live under), `GOOGLE_DRIVE_ENABLED`.

### Web client

Backbone views/models/collections under `web_client/` follow Girder's plugin frontend conventions
(`routes.js` wires client-side routes to views for depositions/forms; models extend Girder's base
`Model`/`Collection`). `web_client/vue/` holds newer Vue components, integrated alongside the Backbone code
rather than replacing it. Build output goes to `web_client/dist/` and is what gets registered as static
plugin content by the Python side — there's no dev server proxy; you rebuild and reload Girder to see
changes.

## Notes

- `doc/preload.md` documents the `preload` schema field format (`girder.formId:<formId>:<field1>:<field2>`)
  used by `Form.materialize()` to populate a form's `dependencies`.
- The `IGSN_REGEX` in `settings.py` (`^[A-Z]{6}[0-9]{5}[A-Z0-9\-]*$`) is the canonical shape of a full IGSN
  (6-char prefix + 5-digit sequence, optionally with `-NNN` batch suffixes) — assume other IGSN-parsing code
  should agree with it.
