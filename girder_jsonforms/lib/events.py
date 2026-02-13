from girder.constants import AccessType
from girder.models.group import Group
from girder.models.user import User

from ..models.project import Project
from ..worker_plugin.orcid import register_project_with_orcid


def ensure_group(event):
    document = event.info
    if "_id" not in document:
        return document

    original = Project().load(document["_id"], force=True)
    if original["status"] != document["status"] and document["status"] == "accepted":
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
        return Project().setGroupAccess(
            document, project_group, AccessType.READ, save=False
        )
    register_project_with_orcid.delay(
        str(document["creatorId"]),
        str(document["_id"]),
        girder_job_title=f"Registering {document['projectId']} with ORCID",
    )
    return document
