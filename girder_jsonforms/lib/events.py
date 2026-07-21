from girder.constants import AccessType
from girder.models.collection import Collection
from girder.models.group import Group
from girder.models.user import User


def ensure_group(event):
    from ..models.project import Project
    from ..worker_plugin.orcid import register_project_with_orcid

    document = event.info
    if "_id" not in document:
        return document

    original = Project().load(document["_id"], force=True)
    if original["status"] != document["status"] and document["status"] == "accepted":
        admin = User().findOne({"admin": True})
        project_group = Group().createGroup(
            document["projectId"],
            admin,
            description="Group for project {}".format(document["projectId"]),
            public=document.get("public", False),
        )
        for member in document.get("members", []):
            if "userId" in member and member["userId"] is not None:
                user = User().load(member["userId"], force=True)
                if user:
                    Group().addUser(project_group, user, level=AccessType.READ)
        project_collection = Collection().createCollection(
            document["projectId"],
            admin,
            description="Collection for project {}".format(document["projectId"]),
        )
        project_collection = Collection().setGroupAccess(
            project_collection, project_group, AccessType.READ
        )
        document = Project().setGroupAccess(
            document, project_group, AccessType.READ, save=False
        )
    register_project_with_orcid.delay(
        str(document["creatorId"]),
        str(document["_id"]),
        girder_job_title=f"Registering {document['projectId']} with ORCID",
    )
    return document


def process_add_samples(event):
    from ..worker_plugin.projects import add_sample_data

    add_sample_data.delay(str(event.info["_id"]), event.info["samples"])


def process_remove_samples(event):
    from ..worker_plugin.projects import remove_sample_data

    remove_sample_data.delay(str(event.info["_id"]), event.info["samples"])
