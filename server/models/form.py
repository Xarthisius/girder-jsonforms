import datetime
import json

import requests
from girder.constants import AccessType
from girder.models.model_base import AccessControlledModel

from ..lib.jq import find_key_paths, get_value, set_value


class Form(AccessControlledModel):
    def initialize(self):
        self.name = "form"
        self.ensureIndices(["name"])

        self.exposeFields(
            level=AccessType.READ,
            fields=(
                "_id",
                "name",
                "description",
                "entryFileName",
                "schema",
                "created",
                "updated",
                "gdriveFolderId",
                "folderId",
                "serialize",
                "pathTemplate",
                "uniqueField",
            ),
        )

    def validate(self, doc):
        return doc

    def create(
        self,
        name,
        description,
        schema,
        creator,
        folder=None,
        pathTemplate=None,
        entryFileName=None,
        gdriveFolderId=None,
        serialize=False,
        uniqueField=None,
    ):
        now = datetime.datetime.utcnow()

        form = {
            "name": name,
            "description": description,
            "schema": schema,
            "folderId": None,
            "gdriveFolderId": gdriveFolderId,
            "pathTemplate": pathTemplate,
            "entryFileName": entryFileName or "entry.json",
            "serialize": serialize,
            "created": now,
            "updated": now,
            "uniqueField": uniqueField or "sampleId",
        }
        if folder:
            form["folderId"] = folder["_id"]

        return self.save(form)

    def update(
        self,
        form,
        name,
        description,
        schema,
        folder=None,
        pathTemplate=None,
        entryFileName=None,
        gdriveFolderId=None,
        serialize=None,
        uniqueField=None,
    ):
        now = datetime.datetime.utcnow()

        form["name"] = name
        form["description"] = description
        form["schema"] = schema
        form["updated"] = now
        form["pathTemplate"] = pathTemplate

        if folder:
            form["folderId"] = folder["_id"]
        else:
            form["folderId"] = None

        if entryFileName:
            form["entryFileName"] = entryFileName

        if gdriveFolderId:
            form["gdriveFolderId"] = gdriveFolderId

        if serialize is not None:
            form["serialize"] = serialize

        if uniqueField:
            form["uniqueField"] = uniqueField

        return self.save(form)

    def materialize(self, form, user):
        from .entry import FormEntry

        if form["schema"].startswith("http"):
            form["schema"] = self._loadRemoteSchema(form["schema"])
        else:
            form["schema"] = json.loads(form["schema"])

        for keyPath in find_key_paths(form["schema"], "enumSource"):
            value = get_value(form["schema"], keyPath)
            if isinstance(value, str) and value.startswith("girder.formId:"):
                formId = value.split(":")[1]
                source_form = self.load(
                    formId, level=AccessType.READ, user=user, exc=True
                )
                enum_source = {
                    "source": [],
                    "title": "{{item.title}}",
                    "value": "{{item.value}}",
                }
                for entry in (
                    FormEntry()
                    .find(
                        {"formId": source_form["_id"]},
                        fields={"_id": 1, source_form["uniqueField"]: 1, "data": 1},
                    )
                    .sort([(source_form["uniqueField"], 1)])
                ):
                    enum_source["source"].append(
                        {
                            "value": str(entry["_id"]),
                            "title": entry["data"][source_form["uniqueField"]],
                        }
                    )
                    set_value(form["schema"], keyPath, [enum_source])

        return form

    def _loadRemoteSchema(self, url):
        return requests.get(url).json()
