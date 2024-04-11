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
                "entryFileName",
                "schema",
                "created",
                "updated",
                "gdriveFolderId",
                "folderId",
                "pathTemplate",
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
            "created": now,
            "updated": now,
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

        return self.save(form)
