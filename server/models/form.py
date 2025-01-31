import datetime
import io
import json

import jsonschema
import numpy as np
import pandas as pd
import requests
from girder.constants import AccessType
from girder.models.model_base import AccessControlledModel

from ..lib.jq import (
    convert_to_jq_notation,
    find_key_paths,
    get_value,
    parse_jq_notation,
    set_value,
)


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

    def export(self, form, export_format):
        from .entry import FormEntry

        entries = [
            convert_to_jq_notation(entry)
            for entry in FormEntry()
            .find(
                {"formId": form["_id"]},
                fields={"_id": 1, "data": 1},
            )
            .sort([("created", 1)])
        ]
        buffer = io.BytesIO()
        if export_format == "csv":
            pd.DataFrame(entries).to_csv(buffer, index=False)
        elif export_format == "xlsx":
            pd.DataFrame(entries).to_excel(buffer, index=False)
        return buffer

    @staticmethod
    def resolve_ref(ref, definitions):
        ref_path = ref.lstrip("#/").split("/")
        ref_value = definitions
        for part in ref_path[1:]:
            ref_value = ref_value.get(part, {})
        return ref_value

    def get_data_types(self, form):
        schema = json.loads(form["schema"])
        types = self.infer_column_types(
            schema, definitions=schema.get("definitions", {})
        )
        return {"data." + key: value for key, value in types.items()}

    def schema_type_to_pandas(self, typename):
        if isinstance(typename, list):
            for t in typename:
                if t == "null":
                    continue
                return self.schema_type_to_pandas(t)
        if typename == "string":
            return "object"
        if typename == "integer":
            return "int64"
        if typename == "number":
            return "float64"
        if typename == "boolean":
            return "bool"

    def infer_column_types(self, schema, definitions=None, parent_key=""):
        properties = {}
        definitions = definitions or {}

        if "properties" in schema:
            for key, value in schema["properties"].items():
                full_key = f"{parent_key}.{key}" if parent_key else key

                if "$ref" in value:
                    value = self.resolve_ref(value["$ref"], definitions)

                if (
                    "type" in value
                    and value["type"] != "object"
                    and value["type"] != "array"
                ):
                    properties[full_key] = self.schema_type_to_pandas(value["type"])

                if value.get("type", "object") == "object":
                    properties.update(
                        self.infer_column_types(
                            value, definitions=definitions or None, parent_key=full_key
                        )
                    )

                if value.get("type") == "array" and "items" in value:
                    properties[full_key] = "array"
                    properties.update(
                        self.infer_column_types(
                            value["items"],
                            definitions=definitions or None,
                            parent_key=full_key + "[]",
                        )
                    )

        return properties

    def import_entries(self, form, file_obj, file_type, dry_run=True):
        from .entry import FormEntry

        schema = json.loads(form["schema"])
        io_buffer = io.BytesIO(file_obj.read())
        if file_type == "csv":
            entries = pd.read_csv(
                io_buffer, na_values=["None", "nan"], dtype=self.get_data_types(form)
            )
        elif file_type == "xlsx":
            entries = pd.read_excel(io_buffer)

        for col in entries.columns:
            if entries[col].dtype == "object":
                entries[col] = entries[col].replace(np.nan, "")

        parsed_entries = [
            parse_jq_notation(entry) for entry in entries.to_dict(orient="records")
        ]
        failed = new = updated = 0
        for row in parsed_entries:
            entry = row["data"]
            try:
                jsonschema.Draft7Validator(schema).validate(entry)
            except jsonschema.ValidationError as e:
                print(str(e))
                failed += 1
                continue
            try:
                unique_id = entry[form["uniqueField"]]
            except KeyError:
                failed += 1
                continue
            if existing_entry := FormEntry().findOne(
                {"formId": form["_id"], f"data.{form['uniqueField']}": unique_id}
            ):
                updated += 1
                print("Updating entry", existing_entry["_id"])
            else:
                new += 1
        return json.dumps({"new": new, "updated": updated, "failed": failed})

    def _loadRemoteSchema(self, url):
        return requests.get(url).json()
