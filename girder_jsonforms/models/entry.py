import datetime
import io
import json
import logging
import os
import re

import bson
import jsondiff
import jsonschema
from girder import events
from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.model_base import Model
from girder.models.upload import Upload
from girder.models.user import User
from girder.utility import JsonEncoder, RequestBodyStream, acl_mixin
from girder.utility.model_importer import ModelImporter

logger = logging.getLogger(__name__)


_UNSET = object()


def _collect_target_paths(data):
    """Map every uploaded file id to the targetPath of its enclosing files
    sub-object, walking the whole submitted form tree.

    The ``file`` field of a files sub-object holds a comma-separated list of the
    Girder file ids uploaded for it, and ``targetPath`` is that group's
    destination as evaluated from the *current* submitted value. Using this at
    submission time lets a file land in the folder implied by the final form
    state (e.g. the latest ``heat_treatment_id``) rather than whatever value was
    frozen into the item's metadata when the file was first uploaded.
    """
    mapping = {}

    def walk(node):
        if isinstance(node, dict):
            files = node.get("file")
            if isinstance(files, str) and files:
                path = node.get("targetPath")
                for file_id in files.split(","):
                    file_id = file_id.strip()
                    if file_id:
                        mapping[file_id] = path
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return mapping


def _item_target_path(item, target_paths):
    """Resolve an uploaded item's targetPath from the submitted form data,
    matching by the ids of the files it contains. Returns ``_UNSET`` when the
    item can't be matched, so callers fall back to baked metadata."""
    for file in Item().childFiles(item):
        file_id = str(file["_id"])
        if file_id in target_paths:
            return target_paths[file_id]
    return _UNSET


def _folder_target_path(folder, creator, target_paths):
    """Resolve an uploaded directory's targetPath from the submitted form data,
    matching by any file it contains (searched recursively). Returns ``_UNSET``
    when nothing matches."""
    stack = [folder]
    while stack:
        current = stack.pop()
        for item in Folder().childItems(current):
            path = _item_target_path(item, target_paths)
            if path is not _UNSET:
                return path
        stack.extend(Folder().childFolders(current, "folder", user=creator))
    return _UNSET


def _get_meta(entry, child_meta, override_path=_UNSET):
    meta = {
        "entryId": entry["_id"],
    }
    if override_path is _UNSET:
        path = child_meta.get("targetPath")
    else:
        # Evaluated from the current form state at submission time; keep the
        # item's stored metadata in sync with where we actually move it.
        path = override_path
        meta["targetPath"] = path
    if batch_action := entry["data"].get("igsn", {}).get("batch", {}):
        logger.info(f"Batch action: {batch_action}")
        if batch_action.get("method") == "from_array" and child_meta.get("formField"):
            logger.info(f"Form field: {child_meta['formField']}")
            number = str(
                int(re.search(r"\d+", child_meta.pop("formField")).group()) + 1
            )
            logger.info(f"Number: {number}")
            if "assignedIGSN" in entry["data"]:
                meta["igsn"] = f"{entry['data']['assignedIGSN']}-{number}"
            if path:
                path = os.path.join(path, number)
            else:
                path = number
            meta["targetPath"] = path
    return path, meta


class Changeset(acl_mixin.AccessControlMixin, Model):
    def initialize(self):
        self.name = "changeset"
        self.resourceColl = ("form", "jsonforms")
        self.resourceParent = "entryId"

        self.exposeFields(
            level=AccessType.READ,
            fields=("_id", "entryId", "creatorId", "created", "diff", "full"),
        )

    def validate(self, doc):
        if not doc.get("entryId"):
            raise ValidationException("Entry ID is required", "entryId")
        return doc

    def create_changeset(self, entry, diff, creator):
        now = datetime.datetime.now(datetime.UTC)
        changeset = {
            "entryId": entry["_id"],
            "diff": diff,
            "full": None,  # Full entry can be added later
            "created": now,
        }
        if creator:
            changeset["creatorId"] = creator["_id"]
        try:
            return self.save(changeset)
        except bson.errors.InvalidDocument:
            changeset["diff"] = None
            changeset["full"] = entry["data"]
            return self.save(changeset)


class FormEntry(acl_mixin.AccessControlMixin, Model):
    def initialize(self):
        global GDRIVE_SERVICE
        self.name = "entry"
        # TODO: create indices for all pairs?
        # self.ensureIndices(["formId", "data.sampleId"])
        self.resourceColl = ("form", "jsonforms")
        self.resourceParent = "formId"

        self.exposeFields(
            level=AccessType.READ,
            fields=(
                "_id",
                "formId",
                "folderId",
                "data",
                "creatorId",
                "created",
                "updated",
                "files",
                "folders",
                "uniqueId",
            ),
        )

    def save(self, doc, validate=True, triggerEvents=True, creator=None):
        if "_id" in doc:
            current_entry = self.load(doc["_id"], force=True, exc=True)
            diff = jsondiff.diff(
                current_entry["data"], doc["data"], syntax="explicit", marshal=True
            )
            if diff:
                Changeset().create_changeset(doc, diff, creator=creator)
        return super().save(doc, validate=validate, triggerEvents=triggerEvents)

    def validate(self, doc):
        if not doc.get("formId"):
            raise ValidationException("Form ID is required", "formId")
        model = ModelImporter.model("form", plugin="jsonforms")
        form = model.load(doc["formId"], force=True)
        if form["uniqueField"] not in doc["data"]:
            raise ValidationException(
                f"Unique field {form['uniqueField']} is required",
                f"data.{form['uniqueField']}",
            )
        doc["uniqueId"] = doc["data"][form["uniqueField"]]

        try:
            json.dumps(
                doc["data"], allow_nan=False, cls=JsonEncoder, separators=(",", ": ")
            )
        except (TypeError, ValueError) as e:
            raise ValidationException(f"Data is not valid JSON: {e}", "data")

        creator = User().load(doc.get("creatorId"), force=True)
        form = model.materialize(form, creator)
        try:
            jsonschema.Draft7Validator(form["schema"]).validate(doc["data"])
        except jsonschema.ValidationError as e:
            raise ValidationException(
                f"Data does not match schema: {e.message}", "data"
            )

        return doc

    def _getExtraPath(self, template, data):
        # Define a safe set of built-in functions and variables
        safe_globals = {"__builtins__": None}
        safe_locals = {"data": data, "ord": ord}

        # Evaluate the template
        try:
            result = eval(f'f"{template}"', safe_globals, safe_locals)
            return result
        except Exception as e:
            print("Error:", e)
            return None

    def update_entry(self, form, entry, data, source, destination, creator):
        entry["data"].update(data)
        entry["updated"] = datetime.datetime.now(datetime.UTC)

        # If the source is provided, handle moving files and folders
        if source is not None:
            entry = self.handle_source(form, source, destination, entry, creator)

        # If the form requires serialization, handle that
        if form.get("serialize", False):
            entry = self.handle_serialization(form, entry, destination, creator)

        return self.save(entry, creator=creator)

    def create_entry(self, form, data, source, destination, creator):
        now = datetime.datetime.now(datetime.UTC)
        unique_field = form.get("uniqueField")
        if destination is None:
            destination_id = None
        else:
            destination_id = destination["_id"]
        entry = {
            "formId": form["_id"],
            "data": data,
            "creatorId": creator["_id"],
            "created": now,
            "updated": now,
            "folderId": destination_id,
            "files": [],
            "folders": [],
            "uniqueId": data.get(unique_field),
        }

        if existing := self.findOne(
            {
                "formId": form["_id"],
                f"data.{unique_field}": data.get(unique_field),
            }
        ):
            # Update the existing entry
            entry.update(
                {
                    "_id": existing["_id"],
                    "created": existing["created"],
                    "files": existing["files"],
                    "folders": existing["folders"],
                }
            )

        # At this point we need to ensure we have _id and/or igsn was created
        entry = self.save(entry, creator=creator)

        if source is not None:
            entry = self.handle_source(form, source, destination, entry, creator)

        if form.get("serialize", False):
            entry = self.handle_serialization(form, entry, destination, creator)

        return entry

    def handle_source(self, form, source, destination, entry, creator):
        # Move from temp to destination
        unique_field = form.get("uniqueField")
        path = entry["data"].get("targetPath")
        known_targets = {
            None: (
                self.get_destination_folder(path, destination, creator),
                entry["data"].get(unique_field),
            )
        }
        dirty = False
        target_paths = _collect_target_paths(entry["data"])
        for child in Folder().childFolders(source, "folder", user=creator):
            child_meta = child.get("meta", {})
            override = _folder_target_path(child, creator, target_paths)
            path, meta = _get_meta(entry, child_meta, override_path=override)
            logger.info(f"Moving {child['_id']} to {path}")
            child = Folder().setMetadata(child, meta)
            try:
                target, _ = known_targets[path]
            except KeyError:
                target = self.get_destination_folder(path, destination, creator)
                known_targets[path] = (
                    target,
                    child.get("meta", {}).get(unique_field),
                )
            child = self.unique(child, target)
            Folder().move(child, target, "folder")
            # TODO upload to GDrive
            entry["folders"].append(child["_id"])
            dirty = True

        for child in Folder().childItems(source):
            child_meta = child.get("meta", {})
            override = _item_target_path(child, target_paths)
            path, meta = _get_meta(entry, child_meta, override_path=override)
            child = Item().setMetadata(child, meta)
            try:
                target, _ = known_targets[path]
            except KeyError:
                target = self.get_destination_folder(path, destination, creator)
                known_targets[path] = (
                    target,
                    child.get("meta", {}).get(unique_field),
                )
            child = self.unique(child, target)
            child = Item().move(child, target)
            for file in Item().childFiles(child):
                # Upload to GDrive
                gdrive_folder_id = child.get("meta", {}).get("gdriveFolderId")
                if gdrive_folder_id:
                    events.trigger(
                        "gdrive.upload",
                        {
                            "file": file,
                            "gdriveFolderId": gdrive_folder_id,
                            "path": os.path.join(path, file["name"]),
                            "currentUser": creator,
                        },
                    )
            entry["files"].append(child["_id"])
            dirty = True
        Folder().remove(source)
        if dirty:
            entry = self.save(entry, creator=creator)
        return entry

    def handle_serialization(self, form, entry, destination, creator):
        unique_field = form.get("uniqueField")
        path = entry["data"].get("targetPath")
        known_targets = {
            None: (
                self.get_destination_folder(path, destination, creator),
                entry["data"].get(unique_field),
            )
        }
        if len(known_targets) > 1:
            known_targets.pop(None)

        processed = set()
        for path, (target, uniqueId) in known_targets.items():
            if target["_id"] in processed:
                continue
            path = path or entry["data"].get("targetPath")
            with io.BytesIO(
                json.dumps(
                    entry, sort_keys=True, allow_nan=False, cls=JsonEncoder
                ).encode("utf-8")
            ) as f:
                reference = {
                    f"{unique_field}": uniqueId,
                    "targetPath": path,
                    "gdriveFolderId": form.get("gdriveFolderId"),
                }
                size = f.getbuffer().nbytes
                upload = self._get_upload_for_entry(
                    form["entryFileName"], target, creator, size, reference
                )
                # not really chunking here as JSON is small
                upload = Upload().handleChunk(upload, RequestBodyStream(f, size))
                if form.get("gdriveFolderId"):
                    events.trigger(
                        "gdrive.upload",
                        {
                            "file": upload,
                            "gdriveFolderId": form["gdriveFolderId"],
                            "gdriveFileId": reference.get("gdriveFileId"),
                            "path": os.path.join(path, upload["name"]),
                            "currentUser": creator,
                        },
                    )
            processed.add(target["_id"])

        return self.save(entry, creator=creator)

    @staticmethod
    def _get_upload_for_entry(fname, target, creator, size, reference):
        if existing_item := Item().findOne({"name": fname, "folderId": target["_id"]}):
            file = Item().childFiles(existing_item)[0]
            if "gdriveFileId" in existing_item.get("meta", {}):
                reference["gdriveFileId"] = existing_item["meta"]["gdriveFileId"]
            reference["itemId"] = existing_item["_id"]
            serialized_reference = json.dumps(
                reference, sort_keys=True, allow_nan=False, cls=JsonEncoder
            )
            upload = Upload().createUploadToFile(
                file=file, user=creator, size=size, reference=serialized_reference
            )
        else:
            serialized_reference = json.dumps(
                reference, sort_keys=True, allow_nan=False, cls=JsonEncoder
            )
            upload = Upload().createUpload(
                user=creator,
                name=fname,
                parentType="folder",
                parent=target,
                size=size,
                mimeType="application/json",
                reference=serialized_reference,
            )
        return upload

    @staticmethod
    def get_destination_folder(path, root, user):
        if path is None:
            return root

        destination = root
        for subfolder in path.split(os.path.sep):
            destination = Folder().createFolder(
                destination,
                subfolder,
                parentType="folder",
                creator=user,
                reuseExisting=True,
            )

        return destination

    @staticmethod
    def unique(child, destination):
        name = child["name"]
        n = 0
        checkName = True
        while checkName:
            q = {
                "name": name,
                "folderId": destination["_id"],
                "_id": {"$ne": child["_id"]},
            }
            dupItem = Item().findOne(q, fields=["_id"])
            q = {
                "name": name,
                "parentId": destination["_id"],
                "parentCollection": "folder",
            }
            dupFolder = Folder().findOne(q, fields=["_id"])

            if dupItem is None and dupFolder is None:
                child["name"] = name
                checkName = False
            else:
                n += 1
                name = f"{child['name']} ({n})"

        child["lowerName"] = child["name"].lower()
        return child
