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

Packaging is **uv**-driven: PEP 621 metadata in `pyproject.toml` (no `setup.py`), dev
dependencies in a PEP 735 `[dependency-groups] dev` (no `requirements-dev.txt`), and `uv.lock`
committed. `tox.ini` declares `requires = tox-uv`, so every tox env is built by `uv venv` /
`uv pip install` and hardlinks out of the shared `~/.cache/uv` instead of copying a few hundred
MB per env. The lock governs `uv sync` only — tox resolves fresh, so CI still catches upstream
girder breakage.

```bash
uv sync              # create/refresh .venv with the project (editable) + dev group
tox -e lint          # ruff check .
tox -e pytest        # full test suite with coverage (needs MongoDB + Redis running)
uv build             # sdist + wheel
```

### Releasing

The version is recorded in four tracked files — `pyproject.toml` (`[project] version`, the
only one the wheel actually carries), `uv.lock`'s editable self-entry, and the web client's
`package.json` + `package-lock.json` (root *and* `packages[""]`) — plus the git tag. Nothing
derives any of them from the others, which is how `package.json` came to sit two patch
releases behind. `scripts/bump_version.py` writes all four at once and verifies them by
re-reading the files afterwards:

```bash
scripts/bump_version.py --check            # report all five records, exit 1 if they disagree
scripts/bump_version.py patch              # or minor / major / an explicit X.Y.Z
scripts/bump_version.py patch -n           # dry run
scripts/bump_version.py patch --commit --tag
```

It never pushes; it prints the remaining commands. **Pushing the `vX.Y.Z` tag is the release**
— `.github/workflows/release.yml` publishes to PyPI on any `refs/tags/` push, so the tag has to
agree with `pyproject.toml`. The script lives in the root `scripts/`, which `MANIFEST.in`
prunes, so `check-manifest` in that workflow stays green. Versions are plain `X.Y.Z` only:
anything with a prerelease segment would have to be spelled differently for PEP 440 and for
npm's semver.

Run tests directly with `pytest` once services are up:

```bash
uv run pytest girder_jsonforms/tests/test_entry.py                 # single file
uv run pytest girder_jsonforms/tests/test_entry.py -k test_name    # single test
```

Tests use `pytest-girder`, which requires a running MongoDB (the CI uses `mongo:4.2`) and Redis
(`redis:7`) instance, and provides fixtures such as `admin`, `user`, `fsAssetstore`.
`girder_jsonforms/tests/conftest.py` overrides two of them, `db` and `server` (see the first gotcha
below), and adds the IGSN-registry fixtures (`local_mode`, `remote_mode`, `igsn_service`,
`igsn_metadata`, `igsn_settings`), all prefixed or named to avoid shadowing the per-module fixtures
older test files define. Set `GIRDER_MAX_CURSOR_TIMEOUT_MS` if cursors time out during tests (CI sets this to `60000`).

Testing gotchas, learned the hard way:

- **One server and one database per test module, per xdist worker** — not per test.
  `conftest.py:_module_girder` loads the module's plugins once; `_fresh_db` puts the database back
  before each test by emptying every collection (indexes kept) and re-inserting what plugin
  loading wrote (the projects collection, same `_id`). So isolation between tests in a module is
  *the database contents only*: a module-level variable, a thread outliving its test, or an
  attribute cached on a model singleton carries over. `Project._project_collection` is reset by
  hand in `_fresh_db`; any new singleton cache needs the same. Every test in a module must carry
  the same `plugin(...)` set (order aside), or the module errors with a `UsageError`; that is why
  `test_deposition.py`'s `TestPrefixCounter` names all three plugins. Before 2026-11-14 it was per
  test, and fixtures were 98% of the suite's worker-time (`-n 4`: ~131s, now ~16s).
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
  set, dump the entry as a JSON file into the destination folder (`handle_serialization`).
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

### Proposal reviewers group (`lib/events.py`)

Girder access flags are **per-document** (`AccessControlledModel.hasAccessFlags`), so there is no
way to hold `jsonforms.review_projects` globally — every proposal has to be granted individually.
The standing group named by `jsonforms.reviewers_group_name` (default **`AIMDL Proposal
Reviewers`**; set it per flavor, the default is the AIMD-L name) is how that is kept manageable:
`lib/events.py:grant_reviewers_access`, bound to `model.project.save` as `jsonforms.reviewers`,
grants the *group* `WRITE` plus the flag on each proposal as it transitions into `under review`.
Membership is then the only thing an admin manages, and because the ACL entry names the group,
adding someone to it immediately gives them every proposal granted so far.

`lib/events.py:reviewers_group` finds-or-creates the group under a `distributed_lock`, called both
at plugin load (so admins can populate it before the first submission) and lazily at grant time
(which covers a fresh instance that has no admin user yet at load, and an admin who deletes the
group later). An empty setting means no standing group — proposals stay visible to site admins and
whoever is granted the flag by hand.

Three details that are load-bearing:

- **Bind order.** `grant_reviewers_access` is bound *before* `jsonforms.mail`, because
  `lib/mail.py:reviewer_emails` reads the group out of the in-flight document's ACL to decide who
  to notify. Reverse them and submissions stop emailing the group.
- **`save=False`, `force=True`.** The handler runs inside the pending save, and
  `setGroupAccess(save=True)` would re-trigger `model.project.save` from `_saveAcl`. `force=True`
  because a model event has no acting user and this is a system grant.
- **Only the transition grants.** Later saves of an already-submitted proposal do not re-apply it,
  so an admin who deliberately revokes the group on one proposal is not overruled.

`WRITE` is what `rest/project.py:update_project` demands (write access *plus* the flag once a
proposal has left draft), so a group member can edit a submitted proposal's other fields too, not
only its status — the endpoint draws no finer line than that.

The same transition also grants the group **`READ`** on the project's `submissionFolderId`
folder and every subfolder (`lib/events.py:share_submission_folder`). The proposal's documents
are uploaded there, and that folder is otherwise private to its creator, so without it a
reviewer sees the document list on the project but gets a 403 on download. Only the standing
group gets this: someone granted the flag by hand on one proposal needs folder access by hand
too, and proposals submitted before this grant existed need it applied once.

### Proposal workflow email (`lib/mail.py`, `mail_templates/`)

Status transitions on a `Project` send Mako-rendered mail through core's
`girder.utility.mail_utils`. `lib/mail.py:notify_project_status` is bound to `model.project.save`
under the handler name **`jsonforms.mail`** — bindings are keyed by `(event, handlerName)`, so
reusing `"jsonforms"` there would silently *replace* `ensure_group`. It diffs the incoming document
against the persisted one and mails on `-> under review` (`projectSubmitted.mako`, **one copy per
reviewer**) and `-> accepted`/`rejected` (`projectDecision.mako`, one template for both outcomes,
a single message to the creator plus every PI member). Delivery is synchronous inside the save, so
failures are logged, never raised.

`build_message` takes no `bcc` and never writes that header: a Bcc header is serialized into the
transmitted message like any other, so core's `sendMail(bcc=...)` discloses the whole list to every
recipient — and a message with a Bcc and no To reads as bulk mail besides. That is why reviewers
each get their own copy addressed to them; they span site admins and per-project flag holders with
no business seeing each other's addresses. The decision mail keeps everyone in one To on purpose:
those recipients are the proposal's own creator and PIs.

Messages are assembled by `lib/mail.py:build_message` with
`email.message.EmailMessage(policy=SMTP)`, following `girder-sivacor`'s `notifications.py`, instead
of core's `sendMail` — which can only produce a lone `MIMEText` HTML part. An HTML-only body is a
spam signal, so every message is a `multipart/alternative` carrying a `text/plain` alternative
rendered from a sibling `<stem>.txt.mako` (text first: RFC 2046 orders alternatives least- to
most-preferred). It also sets the headers filters expect and core's `_createMessage` omits —
`Date`, `Message-ID` (domain taken from the From address so it aligns with SPF/DKIM), and
`Auto-Submitted: auto-generated` to keep vacation responders quiet. Keep the two representations of
a template in step; `tests/test_mail_preview.py` asserts every variant has a rendering text sibling
but cannot check that the wording agrees.

Unlike sivacor, this does **not** `events.unbind("_sendmail", "core.email")`. Sivacor replaces
core's submitter to send `as_bytes()`; that is a site-wide change to every Girder email, and it is
unnecessary here because under the `SMTP` policy `as_string()` — what core's submitter calls — is
7-bit clean (headers RFC 2047-encoded, bodies transfer-encoded), which a test pins. The flip side
is that core's own account emails stay HTML-only; fixing those would mean the unbind.

SPF, DKIM and DMARC are DNS- and MTA-side, and nothing here implements them, but two things this
code controls feed them. The From address (`core.email_from_address`) is the domain DMARC evaluates
and must be one the configured `core.smtp_host` is authorized to send for; and core's submitter
passes `msg['From']` as the SMTP envelope sender, so the header-from doubles as the Return-Path,
which is what keeps SPF aligned for DMARC. `Message-ID` is minted in the From domain for the same
reason. Nothing in the plugin needs to know more than that.

The header logo travels as a **CID attachment**, never an `<img src="https://...">`: displaying the
message must not make the recipient's client fetch anything from us, which would both trip
remote-image blocking (on by default in most clients, leaving a broken image until the reader opts
in) and hand us read tracking we do not want. `data:` URIs avoid the fetch too but Gmail and
Outlook strip them, so the image would break unconditionally instead. `jsonforms.mail_logo` names
the image, empty by default meaning the typographic header. A **bare filename** names one bundled
in `mail_assets/` (`caimee-shield-80.png` ships there, 75x80 for the header's 32-40px box) and is
validated at set time, since a typo would otherwise be a permanent silent fallback; anything with a
separator is a filesystem path, left unchecked because the setting is routinely configured before
the file is mounted. `lib/mail.py:resolve_logo` draws that line and `logo_attachment` degrades to
no logo (logged) when the file is missing. Both `MANIFEST.in` and `setup.py`'s `package_data` list
`mail_assets/*.png` — the former covers the sdist, the latter the wheel, which is how the plugin is
actually installed. Attaching one forces the message to be assembled here -- core's `sendMail`
only builds a bare `MIMEText` -- so `lib/mail.py:_send` constructs the `multipart/related` and
triggers the same `_sendmail` event core does. The setting's validator rejects SVG: no major mail
client renders it by any transport, so it has to be rasterized first.

"Reviewers" resolves to site admins plus whoever holds the `jsonforms.review_projects` access flag
**on that project**, whether directly or through a group — in practice the members of the standing
reviewers group above, which is granted the flag as each proposal is submitted. The reviewers'
mail links to Girder's own project page (`<girder>/#project/<_id>`, `lib/mail.py:girder_project_url`),
because that is where the approve/reject buttons are; it uses an explicitly stored `core.email_host`,
else `https://girder.$DOMAIN`, and only as a last resort the setting's request-derived default,
which behind Traefik is the container's address. The decision mail goes to the creator and PIs, who use the proposals UI
(`https://projects.$DOMAIN/proposal/<_id>`), derived from the same `DOMAIN` env var
`worker_plugin/orcid.py` uses so an emailed link and an ORCID record agree;
`lib/mail.py:projects_url` is the single place to change if that ever becomes a setting.

`scripts/preview_mail.py` renders the templates with sample data straight through Mako -- no
Girder, database, or SMTP involved -- for eyeballing them locally:
`girder-jsonforms-preview-mail --open` (or `python girder_jsonforms/scripts/preview_mail.py`, which
skips the package import). `--raw` emits the exact fragment `sendMail` delivers; `--variant`,
`--brand`, `--domain` and `--logo` cover the other flavor/branding combinations, and
`--text` renders the plain-text alternative (the part a text-only reader and a spam filter see),
and `--logo-file <path-or-bundled-name> [--logo-height 40]` inlines an image as a base64 `data:` URI --
resolving a bare name against `mail_assets/` exactly as the setting does -- the
browser-preview stand-in for the CID attachment (`logoUrl` takes a `cid:`, `https:` or `data:` URI
interchangeably). `--eml` writes real `multipart/related` messages instead of HTML, with the
`--logo-file` image as an inline CID part exactly as `lib/mail.py` sends it, so a mail client can
be pointed at one offline to confirm both that it renders and that nothing is fetched. The script
rebuilds the message rather than importing `build_message`, so that it still runs with no Girder
installed; `tests/test_mail_preview.py` asserts the two produce the same MIME tree and headers,
that `LOGO_CID` agrees, and that every variant renders in both representations — all without
fixtures.

`mail_templates/` is registered with `mail_utils.addTemplateDirectory` **appended, not prepended**:
the Mako lookup is process-global, so a prepended directory would shadow core templates of the same
name for every Girder email. For the same reason the shared partials are `_projectsHeader.mako` /
`_projectsFooter.mako` rather than `_header`/`_footer`. They reproduce the proposals UI app bar
(`aimdl-projects` `src/components/AppBar.vue` + the `base.css` tokens) with inlined styles, and
title the mail with Girder's `brandName` rather than a hardcoded lab name so both `MAIN_PROJECT`
flavors work. All interpolated user input goes through Mako's `| h` filter.

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
folders live under).

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

## Local testing

The suite needs a MongoDB on `localhost:27017` and a Redis on `localhost:6379`. The dev
stack's `mongo`/`redis` sit on swarm overlay networks with no published ports, so they
neither satisfy the tests nor collide with these containers.

```sh
# First time: create the services (no auth needed)
docker run -d --name test-mongo -p 27017:27017 --ulimit nofile=64000:64000 mongo:4.4
docker run -d --name test-redis -p 6379:6379 redis:7-alpine

# Afterwards they are usually just stopped: reuse them instead of recreating
docker start test-mongo test-redis
docker inspect test-mongo --format '{{json .HostConfig.Ulimits}}'   # confirm the ulimit stuck

export DOCKER_HOST="unix:///var/run/docker.sock"
export GIRDER_NOTIFICATION_REDIS_URL="redis://localhost:6379/"

tox -e pytest                                   # the env is `pytest`; there is no `test`
tox -e pytest -- --cov-report=term-missing      # posargs reach pytest: per-file missing lines
tox -e pytest -- girder_jsonforms/tests/test_project_email.py -k girder_project_url

docker stop test-mongo test-redis               # `docker rm` too only if you want them gone
```

`tox -e pytest` always measures coverage (`--cov=girder_jsonforms`) and writes
`coverage.xml`; `--cov-report=term-missing` adds the per-file table to the terminal.
Parallelism is `-n {env:PYTEST_XDIST_N:4}`. At the default `-n 4`, the full suite (500
tests) takes about 16s on a 32-core box, with 74% total coverage (measured 2026-11-14, after
moving to one server per module; it was ~2m10s before). **Wider is slower now**: `-n 16` took
~29s, because each worker handed part of a module pays that module's server and plugin setup
again. Serial (`-n 0`) is ~17s.

**The `--ulimit` on mongo is load-bearing above `-n 8`, and its absence fails
confusingly** — at least it was while `pytest-girder` gave every test its own database, so a
wide run held hundreds of WiredTiger files open at once. (Now one per module per worker: far
fewer, but not re-measured without the flag, so keep starting mongo with it.) Against a default-limit mongo (1024 fds),
`-n 16` makes mongod **abort mid-run** — `Too many open files` → `WT_PANIC` →
`fassert()` → exit 14 — and every remaining test then errors against a dead database,
which reads like a mass code regression rather than a resource limit. 64000 is
MongoDB's own documented recommendation. Measured 2026-08-21.

The `Too many index builds running simultaneously` line that shows up in the same log
is **INFO and benign**: mongo throttling itself back to 3 concurrent builds, which
resolves on its own. It is not the failure, and raising
`maxNumActiveUserIndexBuilds` does not help.

Even the tests documented as "no fixtures" (`test_mail_preview.py`) need Mongo up:
importing the `girder_jsonforms` package loads `girder_worker`, whose task discovery
instantiates `Deposition()` and connects to the database. Without services the failure
is a 20-second `ServerSelectionTimeoutError` at collection, not a test failure. To check
mail rendering with nothing running, run the preview script by path rather than as
the installed console script; that way it never imports the package:

```sh
uv run python girder_jsonforms/scripts/preview_mail.py --text --variant submitted --stdout
```
