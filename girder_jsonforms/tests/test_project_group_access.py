import pytest

from girder.constants import AccessType
from girder.models.collection import Collection
from girder.models.group import Group

from ..models.project import Project as ProjectModel


@pytest.fixture
def draft_project(server, user, admin):
    return ProjectModel().create_project(
        {
            "name": "Group Access Project",
            "description": "A project for testing group/collection creation",
            "creatorId": user["_id"],
        },
        user,
    )


def _group_access_level(doc, group):
    """Read-back the access level a group has on a document straight from
    its persisted access list."""
    for entry in doc.get("access", {}).get("groups", []):
        if entry["id"] == group["_id"]:
            return entry["level"]
    return None


@pytest.mark.plugin("jsonforms")
def test_accepting_project_creates_group_and_collection(
    server, admin, draft_project, eagerWorkerTasks
):
    """Transitioning a project to 'accepted' should create a Girder Group and
    Collection named after the projectId, and grant the group READ access to
    the collection."""
    project_id = draft_project["projectId"]

    # Sanity: neither exists while the project is still a draft.
    assert Group().findOne({"name": project_id}) is None
    assert Collection().findOne({"name": project_id}) is None

    ProjectModel().update_project(draft_project, {"status": "accepted"}, admin)

    group = Group().findOne({"name": project_id})
    assert group is not None, "Expected a group to be created for the project"

    collection = Collection().findOne({"name": project_id})
    assert collection is not None, "Expected a collection to be created for the project"

    # The group must have (persisted) READ access to the collection.
    assert _group_access_level(collection, group) == AccessType.READ
