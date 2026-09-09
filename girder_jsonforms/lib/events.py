import logging

from girder.constants import AccessType
from girder.models.collection import Collection
from girder.models.group import Group
from girder.models.setting import Setting
from girder.models.user import User

from ..settings import PluginSettings
from .locks import distributed_lock

logger = logging.getLogger(__name__)

#: Access flag that lets its holder review a proposal: see a submitted one and
#: change its status once it has left draft (rest/project.py:update_project).
#: Registered in JSONFormsPlugin.load.
REVIEW_FLAG = "jsonforms.review_projects"


def _role_to_access_level(member):
    role = member.get("role", "user")
    if role.lower() == "pi":
        level = AccessType.ADMIN
    elif role.lower() == "manager":
        level = AccessType.WRITE
    else:
        level = AccessType.READ
    return level


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
                if user := User().load(member["userId"], force=True):
                    Group().addUser(
                        project_group, user, level=_role_to_access_level(member)
                    )
        project_collection = Collection().createCollection(
            document["projectId"],
            admin,
            description="Collection for project {}".format(document["projectId"]),
            public=False,
        )
        project_collection = Collection().setGroupAccess(
            project_collection, project_group, AccessType.READ, save=True
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


def reviewers_group(create=True):
    """The standing group whose members review proposals, or None.

    Named by ``jsonforms.reviewers_group_name`` and created on first need, so
    an instance does not have to be seeded by hand; an empty setting means no
    standing group at all. The lock covers the check-then-create, which
    several workers run concurrently at boot -- the same reason the projects
    collection is created under one.
    """
    name = Setting().get(PluginSettings.REVIEWERS_GROUP_NAME)
    if not name:
        return None
    if group := Group().findOne({"name": name}):
        return group
    if not create:
        return None
    with distributed_lock("jsonforms:ensure-reviewers-group"):
        if group := Group().findOne({"name": name}):
            return group
        admin = User().findOne({"admin": True})
        if admin is None:
            # First boot, before setup has created anyone. The next call
            # creates it; nothing needs the group until a proposal is
            # submitted anyway.
            logger.warning(
                "No admin user yet; deferring creation of group %r", name
            )
            return None
        logger.info("Creating proposal reviewers group %r", name)
        return Group().createGroup(
            name,
            admin,
            description=(
                "Members review submitted proposals. Granted the "
                f"'{REVIEW_FLAG}' access flag on each proposal as it is "
                "submitted."
            ),
            public=False,
        )


def grant_reviewers_access(event):
    """Give the reviewers group its flag on a proposal being submitted.

    Bound to ``model.project.save``, before the mail handler so the
    notification's recipient lookup sees the group in the ACL. Access flags
    are per-document in Girder, so every proposal has to be granted
    individually -- there is no way to hold the flag globally.

    WRITE, not READ: a reviewer has to change the proposal's status, and
    ``rest/project.py:update_project`` requires write access *plus* the flag
    once a proposal has left draft.
    """
    from ..models.project import Project

    document = event.info
    if document.get("status") != "under review":
        return
    if "_id" in document:
        original = Project().load(document["_id"], force=True)
        if original is not None and original.get("status") == "under review":
            # Already submitted; the grant happened on that transition. Not
            # re-applied, so a deliberate revocation on one proposal sticks.
            return
    group = reviewers_group()
    if group is None:
        return
    # save=False: this runs inside the pending save, and setGroupAccess(save=True)
    # would re-trigger model.project.save from _saveAcl.
    #
    # force=True: there is no acting user in a model event, and this is a system
    # grant rather than one user handing another a permission.
    Project().setGroupAccess(
        document,
        group,
        AccessType.WRITE,
        save=False,
        flags=[REVIEW_FLAG],
        force=True,
    )
