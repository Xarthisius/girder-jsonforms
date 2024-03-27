import datetime
from girder.constants import AccessType
from girder.models.model_base import AccessControlledModel


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
                "schema",
                "created",
                "updated",
                "folderId",
                "pathTransform",
            ),
        )

    def validate(self, doc):
        return doc

    def create(self, name, description, schema, creator, folder=None, pathTransform=None):
        now = datetime.datetime.utcnow()

        form = {
            "name": name,
            "description": description,
            "schema": schema,
            "folderId": None,
            "pathTransform": pathTransform,
            "created": now,
            "updated": now,
        }
        if folder:
            form["folderId"] = folder["_id"]

        return self.save(form)

    def update(self, form, name, description, schema, folder=None, pathTransform=None):
        now = datetime.datetime.utcnow()

        form["name"] = name
        form["description"] = description
        form["schema"] = schema
        form["updated"] = now
        form["pathTransform"] = pathTransform

        if folder:
            form["folderId"] = folder["_id"]
        else:
            form["folderId"] = None

        return self.save(form)
