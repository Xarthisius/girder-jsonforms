import bson
import jsonschema
import jsonschema.validators as jsv
from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.model_base import AccessControlledModel

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
            "items": {"type": "string"},
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
            "items": {"type": "string"},
            "default": [],
        },
        "status": {
            "type": "string",
            "enum": ["draft", "under review", "accepted", "rejected"],
            "default": "draft",
        },
        "public": {"type": "boolean", "default": False},
        "updated": {"type": "string", "format": "date-time"},
    },
    "required": ["name"],
    "additionalProperties": False,
}


def _is_objectId(checker, instance):
    return isinstance(instance, bson.ObjectId)


class Project(AccessControlledModel):
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
                "public",
                "publicFlags",
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

    def validate(self, doc):
        if "status" not in doc:
            doc["status"] = "draft"
        try:
            self.validator(project_schema).validate(doc)
        except jsonschema.ValidationError as ve:
            raise ValidationException(
                f"Project validation failed: {ve.message}"
            ) from ve
        return doc

    def create_project(self, doc, user):
        doc = self.validate(doc)
        project = self.setUserAccess(doc, user, AccessType.ADMIN, save=True)
        return project

    def update_project(self, project, updates, user):
        for key, value in updates.items():
            project[key] = value
        return self.save(project)
