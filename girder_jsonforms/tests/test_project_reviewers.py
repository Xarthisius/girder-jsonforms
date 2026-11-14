"""The standing reviewers group and the per-proposal flag grant."""

import io

import pytest

from girder.constants import AccessType
from girder.models.folder import Folder
from girder.models.group import Group
from girder.models.item import Item
from girder.models.upload import Upload
from pytest_girder.assertions import assertStatus, assertStatusOk
from pytest_girder.utils import getResponseBody
from girder.models.setting import Setting
from girder.models.user import User

from ..lib.events import REVIEW_FLAG, reviewers_group
from ..models.project import Project as ProjectModel
from ..settings import PluginSettings


@pytest.fixture
def reviewer(admin):
    """A user who reviews proposals only by way of the group."""
    user = User().createUser(
        login="reviewer",
        password="password",
        firstName="Rev",
        lastName="Iewer",
        email="reviewer@example.com",
    )
    Group().addUser(reviewers_group(), user, level=AccessType.READ)
    return user


@pytest.fixture
def draft_project(server, user):
    return ProjectModel().create_project(
        {
            "name": "Reviewer Access Project",
            "description": "A project for testing the reviewers group",
            "creatorId": user["_id"],
        },
        user,
    )


def _upload_document(parent, user, name=b"proposal.pdf"):
    """Put a document where the proposal app does: in the submission folder."""
    item = Item().createItem(name.decode(), user, parent)
    content = b"%PDF-1.4 proposal"
    return Upload().uploadFromFile(
        io.BytesIO(content), len(content), name.decode(), "item", item, user
    )


def _download(server, file_doc, user):
    return server.request(
        path=f"/file/{file_doc['_id']}/download", method="GET", user=user, isJson=False
    )


def _group_entry(doc, group):
    for entry in doc.get("access", {}).get("groups", []):
        if entry["id"] == group["_id"]:
            return entry
    return None


@pytest.mark.plugin("jsonforms")
def test_group_is_created_on_demand(server, admin):
    """The group need not be seeded by hand; asking for it creates it."""
    name = Setting().get(PluginSettings.REVIEWERS_GROUP_NAME)
    assert name == "AIMDL Proposal Reviewers"

    Group().remove(reviewers_group())
    assert Group().findOne({"name": name}) is None

    group = reviewers_group()
    assert group is not None
    assert group["name"] == name
    # Idempotent: a second call returns the same group, not a duplicate.
    assert reviewers_group()["_id"] == group["_id"]
    assert len(list(Group().find({"name": name}))) == 1


@pytest.mark.plugin("jsonforms")
def test_submitting_grants_the_group_its_flag(
    server, user, draft_project, eagerWorkerTasks
):
    group = reviewers_group()
    assert _group_entry(draft_project, group) is None, "not while it is a draft"

    project = ProjectModel().update_project(
        draft_project, {"status": "under review"}, user
    )

    entry = _group_entry(project, group)
    assert entry is not None, "expected the reviewers group in the ACL"
    assert entry["flags"] == [REVIEW_FLAG]
    # WRITE, since reviewing means changing the proposal's status.
    assert entry["level"] == AccessType.WRITE
    # Persisted, not just set on the in-flight document.
    reloaded = ProjectModel().load(project["_id"], force=True)
    assert _group_entry(reloaded, group)["flags"] == [REVIEW_FLAG]


@pytest.mark.plugin("jsonforms")
def test_group_member_can_review_a_submitted_proposal(
    server, user, reviewer, draft_project, eagerWorkerTasks
):
    """The point of the grant: group membership alone is enough to accept a
    proposal, which update_project allows only with write access plus the
    flag once the proposal has left draft."""
    project = ProjectModel().update_project(
        draft_project, {"status": "under review"}, user
    )

    assert ProjectModel().hasAccessFlags(project, user=reviewer, flags=REVIEW_FLAG)
    assert ProjectModel().hasAccess(project, user=reviewer, level=AccessType.WRITE)
    loaded = ProjectModel().load(
        project["_id"], level=AccessType.WRITE, user=reviewer
    )
    assert loaded is not None


@pytest.mark.plugin("jsonforms")
def test_group_members_are_notified_of_a_submission(
    server, user, reviewer, draft_project, sent_mail, eagerWorkerTasks
):
    """The grant lands in the ACL before the mail handler reads it, so a
    group member is among the reviewers who get told."""
    ProjectModel().update_project(draft_project, {"status": "under review"}, user)

    assert reviewer["email"] in {msg["To"] for msg, _ in sent_mail}


@pytest.mark.plugin("jsonforms")
def test_draft_edits_do_not_grant_access(
    server, user, draft_project, eagerWorkerTasks
):
    group = reviewers_group()
    project = ProjectModel().update_project(
        draft_project, {"description": "Still drafting"}, user
    )
    assert _group_entry(project, group) is None


@pytest.mark.plugin("jsonforms")
def test_revoking_the_grant_is_not_undone_by_later_saves(
    server, admin, user, draft_project, eagerWorkerTasks
):
    """Only the transition grants, so an admin who deliberately removes the
    group from one proposal does not have it put back."""
    group = reviewers_group()
    project = ProjectModel().update_project(
        draft_project, {"status": "under review"}, user
    )
    project = ProjectModel().setGroupAccess(project, group, None, save=True)
    assert _group_entry(project, group) is None

    project = ProjectModel().update_project(
        project, {"description": "Under review, edited"}, admin
    )
    assert _group_entry(project, group) is None


@pytest.mark.plugin("jsonforms")
def test_empty_setting_means_no_standing_group(
    server, admin, user, draft_project, eagerWorkerTasks
):
    """An instance can opt out: no group, and submission still works."""
    Setting().set(PluginSettings.REVIEWERS_GROUP_NAME, "")
    assert reviewers_group() is None

    project = ProjectModel().update_project(
        draft_project, {"status": "under review"}, user
    )
    assert project["status"] == "under review"
    assert project.get("access", {}).get("groups", []) == []


def _can_review(server, project, user):
    resp = server.request(path=f"/project/{project['_id']}", method="GET", user=user)
    assert resp.status == "200 OK", resp.json
    return resp.json["_canReview"]


@pytest.mark.plugin("jsonforms")
def test_can_review_tells_the_client_who_gets_the_buttons(
    server, admin, user, reviewer, draft_project, eagerWorkerTasks
):
    """_canReview mirrors update_project's check (WRITE plus the flag), so the
    approve/reject buttons appear for reviewers and site admins only."""
    project = ProjectModel().update_project(
        draft_project, {"status": "under review"}, user
    )

    assert _can_review(server, project, reviewer) is True
    assert _can_review(server, project, admin) is True
    # The creator holds ADMIN on their own proposal but not the flag, so may
    # not judge it.
    assert _can_review(server, project, user) is False


@pytest.mark.plugin("jsonforms")
def test_can_review_needs_write_as_well_as_the_flag(
    server, admin, user, reviewer, draft_project, eagerWorkerTasks
):
    group = reviewers_group()
    project = ProjectModel().update_project(
        draft_project, {"status": "under review"}, user
    )
    project = ProjectModel().setGroupAccess(
        project, group, AccessType.READ, flags=[REVIEW_FLAG], save=True
    )

    assert _can_review(server, project, reviewer) is False


@pytest.mark.plugin("jsonforms")
def test_can_review_is_set_on_listed_projects(
    server, admin, user, reviewer, draft_project, eagerWorkerTasks
):
    ProjectModel().update_project(draft_project, {"status": "under review"}, user)

    resp = server.request(path="/project", method="GET", user=reviewer)
    assert resp.status == "200 OK", resp.json
    assert [p["_canReview"] for p in resp.json] == [True]


@pytest.mark.plugin("jsonforms")
def test_public_settings_name_the_reviewers_group(server, admin):
    """The web client shows the Projects nav entry to members of this group."""
    group = reviewers_group()  # a fresh test database has none until asked
    resp = server.request(path="/system/public_settings", method="GET")
    assert resp.json["jsonforms.reviewers_group_id"] == str(group["_id"])

    Setting().set(PluginSettings.REVIEWERS_GROUP_NAME, "")
    resp = server.request(path="/system/public_settings", method="GET")
    assert resp.json["jsonforms.reviewers_group_id"] is None


@pytest.mark.plugin("jsonforms")
def test_public_settings_do_not_create_the_group(server, admin):
    """Anyone can fetch public settings, so doing so must not create anything."""
    Group().remove(reviewers_group())

    resp = server.request(path="/system/public_settings", method="GET")
    assert resp.json["jsonforms.reviewers_group_id"] is None
    name = Setting().get(PluginSettings.REVIEWERS_GROUP_NAME)
    assert Group().findOne({"name": name}) is None


@pytest.mark.plugin("jsonforms")
def test_group_member_can_download_submitted_documents(
    server, user, reviewer, draft_project, fsAssetstore, eagerWorkerTasks
):
    """The project ACL shows a reviewer the document list; downloading needs
    access to the submission folder the documents were uploaded to."""
    folder = Folder().load(draft_project["submissionFolderId"], force=True)
    top = _upload_document(folder, user)
    nested = _upload_document(
        Folder().createFolder(folder, "attachments", creator=user),
        user,
        name=b"letter.pdf",
    )
    draft_project["files"] = [
        {"type": "proposal", "fileId": top["_id"]},
        {"type": "letterOfSupport", "fileId": nested["_id"]},
    ]
    draft_project = ProjectModel().save(draft_project)

    for file_doc in (top, nested):
        # Not while it is a draft.
        assertStatus(_download(server, file_doc, reviewer), 403)

    ProjectModel().update_project(draft_project, {"status": "under review"}, user)

    for file_doc in (top, nested):
        resp = _download(server, file_doc, reviewer)
        assertStatusOk(resp)
        assert getResponseBody(resp, text=False) == b"%PDF-1.4 proposal"

    # Read only: reviewing a proposal is no licence to replace its documents.
    folder = Folder().load(folder["_id"], force=True)
    assert Folder().hasAccess(folder, user=reviewer, level=AccessType.READ)
    assert not Folder().hasAccess(folder, user=reviewer, level=AccessType.WRITE)
    # The creator keeps the access they had.
    assert Folder().hasAccess(folder, user=user, level=AccessType.WRITE)


@pytest.mark.plugin("jsonforms")
def test_missing_submission_folder_does_not_block_submission(
    server, user, draft_project, eagerWorkerTasks
):
    Folder().remove(Folder().load(draft_project["submissionFolderId"], force=True))

    project = ProjectModel().update_project(
        draft_project, {"status": "under review"}, user
    )

    assert project["status"] == "under review"
    assert _group_entry(project, reviewers_group()) is not None
