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
        path = entry["data"].get("targetPath")
        known_targets = {None: self.get_destination_folder(path, destination, creator)}
        for child in Folder().childFolders(source, "folder", user=creator):
            path = child.get("meta", {}).get("targetPath")
            try:
                target = known_targets[path]
            except KeyError:
                target = self.get_destination_folder(path, destination, creator)
                known_targets[child["_id"]] = target
            child = self.unique(child, target)
            Folder().move(child, target, "folder")
            entry["folders"].append(child["_id"])

        for child in Folder().childItems(source):
            path = child.get("meta", {}).get("targetPath")
            try:
                target = known_targets[path]
            except KeyError:
                target = self.get_destination_folder(path, destination, creator)
                known_targets[child["_id"]] = target
            child = self.unique(child, target)
            Item().move(child, target)
            entry["files"].append(child["_id"])
        Folder().remove(source)

        # Dump the entry into json file, by creating bytes buffer from json dump and
        # Upload().uploadFromFile will create a file in each destination folder
        if len(known_targets) > 1:
            known_targets.pop(None)

        processed = set()
        for target in known_targets.values():
            if target["_id"] in processed:
                continue
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
            processed.add(target["_id"])

        return self.save(entry)

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
