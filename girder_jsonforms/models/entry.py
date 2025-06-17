import datetime
import io
import json
import logging
import os
import re

from girder import events
from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.model_base import Model
from girder.models.upload import Upload
from girder.utility import JsonEncoder, RequestBodyStream, acl_mixin
from girder.utility.model_importer import ModelImporter
import jsondiff

logger = logging.getLogger(__name__)


def _get_meta(entry, child_meta):
    meta = {
        "entryId": entry["_id"],
    }
    path = child_meta.get("targetPath")
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
            fields=("_id", "entryId", "creatorId", "created", "diff"),
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
            "created": now,
        }
        if creator:
            changeset["creatorId"] = creator["_id"]
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
        doc["uniqueId"] = doc["data"][form["uniqueField"]]
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
                f"data.{unique_field}": data[unique_field],
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
        for child in Folder().childFolders(source, "folder", user=creator):
            child_meta = child.get("meta", {})
            path, meta = _get_meta(entry, child_meta)
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
            path, meta = _get_meta(entry, child_meta)
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
