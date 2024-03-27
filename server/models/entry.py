import datetime
import os

from girder.constants import AccessType
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.model_base import AccessControlledModel


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
            result = eval(f"f\"{template}\"", safe_globals, safe_locals)
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

        if form["pathTransform"]:
            extra_path = self._getExtraPath(form["pathTransform"], data)

            if extra_path:
                for subfolder in extra_path.split(os.path.sep):
                    destination = Folder().createFolder(
                        destination,
                        subfolder,
                        parentType="folder",
                        creator=creator,
                        reuseExisting=True,
                    )

        entry["folderId"] = destination["_id"]

        # Move from temp to destination
        for child in Folder().childFolders(source, "folder", user=creator):
            entry["folders"].append(child["_id"])
            Folder().move(child, destination, "folder")
        for child in Folder().childItems(source):
            entry["files"].append(child["_id"])
            Item().move(child, destination)
        Folder().remove(source)

        return self.save(entry)
