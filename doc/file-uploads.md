# Technical Documentation: File Uploads in JSON-Schema Forms

---

## 1. Introduction

This document describes how files attached to a form entry are uploaded, staged,
annotated, and finally moved into their permanent location. File handling in
`girder_jsonforms` spans the web client (json-editor + Girder's `UploadWidget`),
a Girder upload event handler, and the `FormEntry` model. The most important
property of the design — and the one most easily gotten wrong — is *when* a
file's destination path is decided: it is **evaluated from the submitted form
data at submission time**, not frozen when the bytes are uploaded.

The relevant source files are:

* `girder_jsonforms/web_client/views/EditFormView.js` — the upload UI and submit.
* `girder_jsonforms/__init__.py` (`annotate_upload`) — the `data.process` handler.
* `girder_jsonforms/rest/entry.py` — the `POST /entry` / `PUT /entry/:id` routes.
* `girder_jsonforms/models/entry.py` (`handle_source`, `_get_meta`,
  `_collect_target_paths`) — the move into the destination.

## 2. The `files` schema definition

A form declares a file-upload control as an object, conventionally a reusable
`#/definitions/files`, with three properties:

```json
{
  "targetPath": {
    "type": "string",
    "title": "Target Path",
    "watch": { "hid": "root.heat_treatment_id" },
    "options": { "hidden": true },
    "template": "{{hid}}"
  },
  "file": {
    "type": "string",
    "title": "Upload files"
  },
  "button": {
    "title": "Browse",
    "format": "button",
    "options": { "button": { "action": "button1CB", "uploadFor": "file" } }
  }
}
```

### 2.1. `targetPath`

A hidden, template-driven string that names the **sub-folder (relative to the
entry's destination folder) into which the uploaded files should ultimately be
placed**. It is normally computed by a json-editor `watch` + `template` chain
from other fields — e.g. `{{hid}}` bound to `root.heat_treatment_id`, which is
itself a template over the rest of the form. Because it is template-driven,
`this.form.getValue()` always reflects the *current* value: if the field it
depends on changes (a new heat-treatment stage is added, say), `targetPath`
updates with it.

### 2.2. `file`

A string holding a **comma-separated list of Girder *file* ids** that have been
uploaded for this control. The client appends ids to it as uploads complete (see
§3.3). This is the field that links a submitted form to the physical files that
were staged for it.

### 2.3. `button`

A json-editor `format: button` control whose `action` names a callback
registered in `JSONEditor.defaults.callbacks.button` (see §3.1). Clicking it
opens the upload dialog for the sibling `file` field.

## 3. The client upload flow

### 3.1. Button callbacks

`EditFormView.initialize` registers the button callbacks
(`EditFormView.js:189`). Each derives the sibling `file` field path from the
button's own path and opens the upload dialog:

```js
'button1CB': function (jseditor) {
    const field = jseditor.options.path.replace(/\.button(?!.*\.button)/, '.file');
    this.uploadDialog(jseditor, field, false, true);   // files, multi-file
}
```

`button2CB` is the same but for directory uploads; `buttonSample` is the
single-file variant.

### 3.2. The staging (temp) folder

At `initialize` time the view creates a **temporary folder** under the current
user (`EditFormView.js:175`), named `_temp_<formId>_<random>`, and immediately
schedules it for deletion in one hour:

```js
this.tempFolder.save().done(() => {
    this.tempFolder.addMetadata('formId', this.model.id);
    restRequest({ method: 'DELETE',
        url: `folder/${this.tempFolder.id}?progress=false&countdown=3600` });
});
```

Every file the user uploads while filling the form lands here first. The
countdown delete guarantees abandoned drafts are cleaned up even if the form is
never submitted.

### 3.3. `uploadDialog` and the upload reference

`uploadDialog` (`EditFormView.js:235`) builds a **reference** object and hands
it to Girder's `UploadWidget`, uploading into `this.tempFolder`:

```js
var reference = {
    [this.uniqueField]: value[this.uniqueField],
    annotate: true,
    formField: field
};
if (value.targetPath) { reference.targetPath = value.targetPath; }
if (this.model.get('gdriveFolderId')) { reference.gdriveFolderId = ...; }
```

The reference is serialized into `otherParams.reference` and travels with the
upload to the server. Key fields:

| Field         | Meaning                                                        |
|---------------|----------------------------------------------------------------|
| `annotate`    | Tells the server to copy the reference into item metadata.     |
| `formField`   | The dotted path of the `file` field (used by batch numbering). |
| `targetPath`  | The value of `targetPath` **at upload time** (see §6 caveat).   |
| `<uniqueField>` | The entry's unique id (e.g. `sampleId`).                     |
| `gdriveFolderId` | Optional Google Drive target.                               |

On `g:uploadFinished` the returned file ids are appended to the `file` field via
`setField` (`EditFormView.js:271`), so the form value now records which files
belong to this control.

## 4. Server-side annotation on upload

Uploading a file triggers Girder's `data.process` event, bound to
`annotate_uploads` → `annotate_upload` (`__init__.py:47`, `__init__.py:59`).
When the reference has `annotate: true`, the handler writes the **entire
reference into the uploaded item's metadata**:

```python
if reference.get("annotate"):
    parent = Item().load(info["file"]["itemId"], level=AccessType.WRITE, user=...)
    reference.pop("file", None)
    reference.pop("annotate", None)
    Item().setMetadata(parent, reference)
```

So immediately after upload, each staged item carries `formField`, the unique
field, and the upload-time `targetPath` in its `meta`. This metadata is a
best-effort snapshot; it is **not** the authoritative source for the final
destination (see §5.2 and §6).

## 5. Submission

### 5.1. The submit request

On form submit (`EditFormView.js:73`) the view validates, then posts the form
value along with the staging and destination folder ids:

```js
var params = { formId, data: JSON.stringify(this.form.getValue()) };
if (this.tempFolder) { params.sourceId = this.tempFolder.id; }
if (this.destFolder) { params.destinationId = this.destFolder.id; }
```

`POST /entry` (create) or `PUT /entry/:id` (update) receive these as `source`
and `destination` model params (`rest/entry.py:213`, `rest/entry.py:154`) and
call `FormEntry.create_entry` / `update_entry`, which delegate the file move to
`handle_source` (`models/entry.py`).

### 5.2. `handle_source`: moving staged content into place

`handle_source` (`models/entry.py`) walks the staging (source) folder and moves
each child item and child folder into a destination derived from its
`targetPath`:

1. Build the authoritative `targetPath` map from the submitted data (§6).
2. For each child folder / item:
   * Resolve its `targetPath` (form data first, baked metadata as fallback).
   * Compute the destination folder with `get_destination_folder`, which
     creates the `targetPath` sub-folders under the destination on demand
     (`reuseExisting=True`).
   * Rename to avoid collisions (`unique`) and move it there.
   * Record the moved id on the entry (`entry["files"]` / `entry["folders"]`).
3. Remove the now-empty source folder.

`get_destination_folder(path, root, user)` (`models/entry.py:360`) splits
`path` on the OS separator and creates each segment as a nested folder, so a
`targetPath` of `a/b/c` yields `<destination>/a/b/c`.

## 6. When `targetPath` is evaluated (the important part)

The destination for each file is resolved from the **submitted form data**, not
from the metadata frozen onto the item at upload time. This matters because
`targetPath` is template-driven: its value can legitimately change between the
moment a file is uploaded and the moment the form is submitted (e.g. adding a
heat-treatment stage changes `heat_treatment_id`, and therefore every
`targetPath` bound to it). The intended and implemented behavior is: **all files
are placed according to the final form state.**

### 6.1. Building the map

`_collect_target_paths(data)` (`models/entry.py`) walks the entire submitted
data tree and, for every object that has a non-empty `file` string, maps each
file id in that string to the object's `targetPath`:

```python
{ "<fileId>": "<targetPath>", ... }
```

Because it walks the whole tree, it captures every `files` control wherever it
appears — top-level, inside `stress_relief`, inside each `heat_treatment[]`
entry, etc.

### 6.2. Resolving a staged item / folder

* `_item_target_path(item, target_paths)` matches a staged item to the map by
  the ids of the files it contains (`Item().childFiles`).
* `_folder_target_path(folder, creator, target_paths)` matches a staged
  directory by any file found under it (searched recursively).

Both return a sentinel (`_UNSET`) when nothing matches, in which case
`_get_meta` falls back to the item's baked `targetPath` metadata (§4),
preserving behavior for any form that does not carry `targetPath` in its data.

### 6.3. Applying the resolved path

`_get_meta(entry, child_meta, override_path=_UNSET)` (`models/entry.py`) uses
the override when present, and also writes it back into the item's `meta` so the
stored `targetPath` matches where the file was actually moved:

```python
if override_path is _UNSET:
    path = child_meta.get("targetPath")   # fallback: baked metadata
else:
    path = override_path                  # authoritative: submitted form data
    meta["targetPath"] = path
```

> **Rationale.** The upload-time `targetPath` written in §4 is a snapshot that
> can become stale. Resolving from the submitted data at move time guarantees a
> file lands in the folder implied by the *final* form, regardless of how the
> form changed after the file was uploaded. The upload reference still carries
> `targetPath` (as a harmless fallback), but form data always wins when present.

## 7. Batch numbering (IGSN sub-samples)

When `data["igsn"]["batch"]["method"] == "from_array"`, `_get_meta` derives a
per-file numeric suffix from the item's `formField` metadata and appends it to
the resolved `targetPath` (and to the assigned IGSN):

```python
number = str(int(re.search(r"\d+", child_meta.pop("formField")).group()) + 1)
meta["igsn"] = f"{entry['data']['assignedIGSN']}-{number}"   # if assignedIGSN present
path = os.path.join(path, number) if path else number
```

This is why `formField` is still carried in the upload reference and item
metadata even though `targetPath` itself is now resolved from form data: batch
numbering keys off `formField`, and the number is layered on top of the resolved
base path.

## 8. Serialization and Google Drive

If the form has `serialize: true`, `handle_serialization` (`models/entry.py:284`)
dumps the entry itself as a JSON file into each resolved destination folder,
reusing the same `targetPath` / `get_destination_folder` machinery. When a
`gdriveFolderId` is configured, both moved files and the serialized entry are
pushed to Google Drive via the `gdrive.upload` event, using
`os.path.join(path, file_name)` as the Drive-side path — again built from the
resolved `path`.

## 9. Lifecycle summary

```
┌──────────────┐  upload (reference: annotate, formField, targetPath@now)
│ user clicks  │ ───────────────────────────────────────────────► temp folder
│  "Browse"    │                                                    (auto-delete 1h)
└──────────────┘                                                         │
        │ file ids appended to the `file` field                         │ data.process
        ▼                                                                ▼
┌──────────────┐                                        annotate_upload writes the
│ user edits   │  targetPath field re-evaluates          reference into item metadata
│ form; watch  │  via watch/template (may change)                (snapshot, fallback)
│ updates      │
└──────────────┘
        │ submit: POST /entry  { data, sourceId=temp, destinationId=dest }
        ▼
┌───────────────────────── handle_source ─────────────────────────┐
│ _collect_target_paths(data)  →  { fileId: targetPath }           │  ← authoritative
│ for each staged item/folder:                                     │
│   path = form-data targetPath  (fallback: baked metadata)        │
│   dest = get_destination_folder(path, destination)  # creates    │
│   unique(...) ; move(...)                                        │
│ remove(temp) ; save(entry)                                       │
└──────────────────────────────────────────────────────────────────┘
```

## 10. Testing

`girder_jsonforms/tests/test_entry.py` covers this flow:

* `test_create_entry_with_folders` — create with `sourceId`/`destinationId`.
* `test_handle_source_uses_submitted_target_path` — regression test proving that
  a staged item whose *metadata* carries a stale `targetPath` is moved to the
  path in the *submitted data* instead, and that its stored metadata is
  corrected.

The suite requires a running MongoDB and Redis (see `CLAUDE.md`).
