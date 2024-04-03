import datetime
import io
import json
import os

from girder.constants import AccessType
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.model_base import AccessControlledModel
from girder.models.upload import Upload
from girder.utility import JsonEncoder


class FormEntry(AccessControlledModel):
    def initialize(self):
        self.name = "entry"
        self.ensureIndices(["formId"])

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

        entry = {
            "formId": form["_id"],
            "data": data,
            "created": now,
            "updated": now,
            "folderId": None,
            "files": [],
            "folders": [],
        }

        entry["folderId"] = destination["_id"]

        # Move from temp to destination
        known_targets = {None: destination}
        for child in Folder().childFolders(source, "folder", user=creator):
            try:
                target = known_targets[child.get("meta", {}).get("targetPath")]
            except KeyError:
                target = self.get_destination_folder(child, destination, creator)
                known_targets[child["_id"]] = target
            child = self.unique(child, target)
            Folder().move(child, target, "folder")
            entry["folders"].append(child["_id"])

        for child in Folder().childItems(source):
            try:
                target = known_targets[child.get("meta", {}).get("targetPath")]
            except KeyError:
                target = self.get_destination_folder(child, destination, creator)
                known_targets[child["_id"]] = target
            child = self.unique(child, target)
            Item().move(child, target)
            entry["files"].append(child["_id"])
        Folder().remove(source)

        # Dump the entry into json file, by creating bytes buffer from json dump and
        # Upload().uploadFromFile will create a file in each destination folder
        if len(known_targets) > 1:
            known_targets.pop(None)

        for target in known_targets.values():
            with io.BytesIO(
                json.dumps(
                    entry, sort_keys=True, allow_nan=False, cls=JsonEncoder
                ).encode("utf-8")
            ) as f:
                Upload().uploadFromFile(
                    f,
                    f.getbuffer().nbytes,
                    form["entryFileName"],
                    parentType="folder",
                    parent=target,
                    mimeType="application/json",
                )

        return self.save(entry)

    @staticmethod
    def get_destination_folder(child, root, user):
        destination = root
        if "targetPath" not in child["meta"]:
            return destination

        for subfolder in child["meta"]["targetPath"].split(os.path.sep):
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
