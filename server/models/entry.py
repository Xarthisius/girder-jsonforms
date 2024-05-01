import datetime
import io
import json
import os

from girder import events
from girder.constants import AccessType
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.model_base import Model
from girder.models.upload import Upload
from girder.utility import acl_mixin, JsonEncoder, RequestBodyStream


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
                "created",
                "updated",
                "files",
                "folders",
            ),
        )

    def validate(self, doc):
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

    def create(self, form, data, source, destination, creator):
        now = datetime.datetime.utcnow()
        unique_field = form.get("uniqueField")
        entry = {
            "formId": form["_id"],
            "data": data,
            "created": now,
            "updated": now,
            "folderId": destination["_id"],
            "files": [],
            "folders": [],
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

        # Move from temp to destination
        path = entry["data"].get("targetPath")
        known_targets = {
            None: (
                self.get_destination_folder(path, destination, creator),
                entry["data"].get(unique_field),
            )
        }
        if source is not None:
            for child in Folder().childFolders(source, "folder", user=creator):
                path = child.get("meta", {}).get("targetPath")
                try:
                    target, _ = known_targets[path]
                except KeyError:
                    target = self.get_destination_folder(path, destination, creator)
                    known_targets[path] = target, child.get("meta", {}).get(unique_field)
                child = self.unique(child, target)
                Folder().move(child, target, "folder")
                # TODO upload to GDrive
                entry["folders"].append(child["_id"])

            for child in Folder().childItems(source):
                path = child.get("meta", {}).get("targetPath")
                try:
                    target, _ = known_targets[path]
                except KeyError:
                    target = self.get_destination_folder(path, destination, creator)
                    known_targets[path] = target, child.get("meta", {}).get(unique_field)
                child = self.unique(child, target)
                child = Item().move(child, target)
                for file in Item().childFiles(child):
                    # Upload to GDrive
                    gdrive_folder_id = child.get("meta", {}).get("gdriveFolderId")
                    if gdrive_folder_id:
                        events.daemon.trigger(
                            "gdrive.upload",
                            {
                                "file": file,
                                "gdriveFolderId": gdrive_folder_id,
                                "path": os.path.join(path, file["name"]),
                                "currentUser": creator,
                            },
                        )
                entry["files"].append(child["_id"])
            Folder().remove(source)

        if not form.get("serialize", False):
            return self.save(entry)

        # Dump the entry into json file, by creating bytes buffer from json dump and
        # Upload().uploadFromFile will create a file in each destination folder
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
                    events.daemon.trigger(
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

        return self.save(entry)

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
