import bson
import datetime
import jsonschema
import jsonschema.validators as jsv
from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.model_base import AccessControlledModel, Model
from girder.models.setting import Setting
from girder.models.group import Group
from girder.models.user import User
from pymongo import ReturnDocument

from ..settings import PluginSettings

#  * Request Information
#    * Project Title
#    * Public Overview
#    * Keywords (comma-separated)
#  * Fields of Science (N/A?)
#  * Related Personnel
#    * Last, First, Org, Role
#    Add Personel (search + role)
#  * Supporting Grants
#  * Documents
#    Type / Title (optional) / Document (browse)  / Add Another Document
#  * Available Resources

project_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "_id": {"type": "objectId"},
        "access": {"type": "object"},
        "name": {"type": "string", "minLength": 1},
        "created": {"type": "string", "format": "date-time"},
        "creatorId": {"type": "objectId"},
        "description": {"type": "string"},
        "startDate": {"type": "string", "format": "date"},
        "endDate": {"type": "string", "format": "date"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "fileId": {"type": "objectId"},
                },
            },
            "default": [],
        },
        "members": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "userId": {"type": ["objectId", "null"]},
                    "role": {"type": "string", "enum": ["PI", "manager", "user"]},
                    "firstName": {"type": "string"},
                    "lastName": {"type": "string"},
                    "orcidId": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                },
                "required": ["email", "role"],
                "additionalProperties": False,
            },
            "default": [],
        },
        "samples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "_id": {"type": "objectId"},
                    "igsn": {"type": "string"},
                },
                "additionalProperties": False,
                "required": ["_id", "igsn"],
            },
            "default": [],
        },
        "status": {
            "type": "string",
            "enum": ["draft", "under review", "accepted", "rejected"],
            "default": "draft",
        },
        "public": {"type": "boolean", "default": False},
        "projectId": {"type": "string"},
        "updated": {"type": "string", "format": "date-time"},
        "submissionFolderId": {"type": "objectId"},
    },
    "required": ["name", "projectId"],
    "additionalProperties": False,
}


def _is_objectId(checker, instance):
    return isinstance(instance, bson.ObjectId)


class ProjectCounter(Model):
    def initialize(self):
        self.name = "projectCounter"
        self.ensureIndices(["prefix"])
        self.exposeFields(
            level=AccessType.READ,
            fields=(
                "_id",
                "prefix",
                "seq",
            ),
        )

    def validate(self, doc):
        if not doc.get("prefix"):
            raise ValidationException("Missing prefix")
        prefix = doc["prefix"]
        if not isinstance(prefix, str) or len(prefix) != 5:
            raise ValidationException(f"Prefix must be 5 characters long {prefix}")
        inst = prefix[:3]
        if not inst.isalpha():
            raise ValidationException("Invalid project code in prefix")
        try:
            int(prefix[-2:])
        except ValueError:
            raise ValidationException("Invalid year in prefix")
        return doc

    def get_counter(self, prefix):
        if existing := self.findOne({"prefix": prefix}):
            return existing
        return self.save({"prefix": prefix, "seq": 0})

    def increment(self, counter):
        return self.collection.find_one_and_update(
            counter, {"$inc": {"seq": 1}}, return_document=ReturnDocument.AFTER
        )

    def get_next(self, prefix):
        counter = self.get_counter(prefix)
        counter = self.increment(counter)
        return f"{counter['prefix']}{counter['seq']:04d}"


class Project(AccessControlledModel):
    _project_collection = None

    def initialize(self):
        self.name = "project"
        self.exposeFields(
            level=AccessType.READ,
            fields=(
                "_id",
                "created",
                "creatorId",
                "description",
                "files",
                "name",
                "metadata",
                "members",
                "projectId",
                "public",
                "publicFlags",
                "submissionFolderId",
                "status",
                "updated",
            ),
        )
        custom_type_checker = jsv.Draft7Validator.TYPE_CHECKER.redefine(
            "objectId", _is_objectId
        )
        self.validator = jsv.extend(
            jsv.Draft7Validator, type_checker=custom_type_checker
        )

    def ensure_group(self, event):
        document = event.info
        if "_id" not in document:
            return document

        original = self.load(document["_id"], force=True)
        if (
            original["status"] != document["status"]
            and document["status"] == "accepted"
        ):
            project_group = Group().createGroup(
                document["projectId"],
                User().findOne({"admin": True}),
                description="Group for project {}:{}".format(
                    document["projectId"], document["name"]
                ),
                public=document.get("public", False),
            )
            for member in document.get("members", []):
                if "userId" in member and member["userId"] is not None:
                    user = User().load(member["userId"], force=True)
                    if user:
                        Group().addUser(project_group, user, level=AccessType.READ)
            return self.setGroupAccess(
                document, project_group, AccessType.READ, save=False
            )
        return document

    def validate(self, doc):
        if "status" not in doc:
            doc["status"] = "draft"
        if "files" not in doc:
            doc["files"] = []
        for file in doc["files"]:
            if isinstance(file["fileId"], str):
                file["fileId"] = bson.ObjectId(file["fileId"])
        for member in doc.get("members", []):
            if "userId" in member and isinstance(member["userId"], str):
                member["userId"] = bson.ObjectId(member["userId"])
        if "submissionFolderId" in doc and isinstance(doc["submissionFolderId"], str):
            doc["submissionFolderId"] = bson.ObjectId(doc["submissionFolderId"])
        try:
            self.validator(project_schema).validate(doc)
        except jsonschema.ValidationError as ve:
            import pprint

            pprint.pprint(ve.message)
            raise ValidationException(
                f"Project validation failed: {ve.message}"
            ) from ve
        return doc

    @property
    def project_collection(self):
        if self._project_collection is None:
            self._project_collection = Collection().findOne(
                {"name": Setting().get(PluginSettings.PROJECTS_COLLECTION_NAME)}
            )
        return self._project_collection

    def create_project(self, doc, user):
        project_id = ProjectCounter().get_next(f"JHU{datetime.datetime.now():%y}")
        if not doc.get("projectId"):
            doc["projectId"] = project_id
        doc.pop("submissionFolderId", None)
        doc = self.validate(doc)
        submission_folder = Folder().createFolder(
            self.project_collection,
            project_id,
            parentType="collection",
            public=False,
            creator=User().findOne({"admin": True}),
            reuseExisting=False,
        )
        submission_folder = Folder().setMetadata(
            submission_folder,
            {"creator_id": str(user["_id"])},
        )
        Folder().setUserAccess(submission_folder, user, AccessType.WRITE, save=True)
        doc["submissionFolderId"] = submission_folder["_id"]
        project = self.setUserAccess(doc, user, AccessType.ADMIN, save=True)
        return project

    def remove(self, project):
        if "submissionFolderId" in project:
            folder = Folder().load(project["submissionFolderId"], force=True)
            if folder:
                Folder().remove(folder)
        super().remove(project)

    def update_project(self, project, updates, user):
        protected_fields = {
            "_id",
            "creatorId",
            "created",
            "projectId",
            "submissionFolderId",
        }
        for key, value in updates.items():
            if key in protected_fields:
                continue
            project[key] = value
        return self.save(project)
