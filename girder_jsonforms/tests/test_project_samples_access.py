import json

import pytest
import girder_jsonforms.rest.aimdl as aimdl_mod
from girder.constants import AccessType
from girder.exceptions import AccessException
from girder.models.collection import Collection
from pytest_girder.assertions import assertStatus, assertStatusOk

from ..models.project import Project as ProjectModel


@pytest.fixture
def aimdl_collection(admin, monkeypatch):
    """A fresh Collection standing in for the blessed AIMDL collection, so
    that adding a sample doesn't fail trying to sync AIMDL-visible data."""
    collection = Collection().createCollection("AIMDL", admin, public=True)
    monkeypatch.setattr(aimdl_mod, "_AIMDL_COLLECTION_ID", str(collection["_id"]))
    return collection


@pytest.fixture
def owned_project(server, user, admin, eagerWorkerTasks, aimdl_collection):
    """A project owned by ``user`` (ADMIN access) but without the
    ``jsonforms.manage_samples`` flag granted to anyone but site admins."""
    return ProjectModel().create_project(
        {
            "name": "Test Project",
            "description": "A project for testing sample manager access",
            "creatorId": user["_id"],
        },
        user,
    )


def _grant_manage_samples(project, user, admin):
    return ProjectModel().setUserAccess(
        project,
        user,
        AccessType.ADMIN,
        flags="jsonforms.manage_samples",
        currentUser=admin,
        save=True,
    )


@pytest.mark.plugin("jsonforms")
class TestSampleManagerFlag:
    def test_owner_without_flag_cannot_update_samples(self, owned_project, user):
        with pytest.raises(AccessException):
            ProjectModel().update_samples(owned_project, ["JHAMAA00001"], user)

    def test_owner_can_update_non_sample_fields_without_flag(
        self, owned_project, user
    ):
        updated = ProjectModel().update_project(
            owned_project, {"description": "updated"}, user
        )
        assert updated["description"] == "updated"

    def test_updating_samples_via_generic_update_project_is_a_no_op(
        self, owned_project, user, admin
    ):
        """The ``samples`` field is protected on the generic update path;
        it can only be changed through Project.update_samples / the
        dedicated /project/:id/samples endpoint."""
        updated = ProjectModel().update_project(
            owned_project, {"samples": ["JHAMAA00001"]}, admin
        )
        assert updated["samples"] == []

    def test_setting_samples_to_same_value_still_requires_flag(
        self, owned_project, user
    ):
        with pytest.raises(AccessException):
            ProjectModel().update_samples(
                owned_project, list(owned_project["samples"]), user
            )

    def test_user_with_flag_can_update_samples(self, owned_project, user, admin):
        _grant_manage_samples(owned_project, user, admin)
        updated = ProjectModel().update_samples(
            owned_project, ["JHAMAA00001"], user
        )
        assert updated["samples"] == ["JHAMAA00001"]

    def test_site_admin_bypasses_flag_requirement(self, owned_project, admin):
        updated = ProjectModel().update_samples(owned_project, ["JHAMAA00001"], admin)
        assert updated["samples"] == ["JHAMAA00001"]

    def test_samples_can_be_updated_on_non_draft_project(
        self, owned_project, user, admin
    ):
        """Unlike the general project update, sample changes aren't gated
        on the project being in 'draft' status."""
        _grant_manage_samples(owned_project, user, admin)
        non_draft = ProjectModel().update_project(
            owned_project, {"status": "under review"}, admin
        )
        updated = ProjectModel().update_samples(non_draft, ["JHAMAA00001"], user)
        assert updated["samples"] == ["JHAMAA00001"]


@pytest.mark.plugin("jsonforms")
class TestSampleManagerFlagRest:
    def test_put_project_does_not_change_samples(self, server, owned_project, admin):
        resp = server.request(
            path=f"/project/{owned_project['_id']}",
            method="PUT",
            body=json.dumps({"samples": ["JHAMAA00001"]}),
            type="application/json",
            user=admin,
        )
        assertStatusOk(resp)
        assert resp.json["samples"] == []

    def test_put_project_samples_forbidden_without_flag(
        self, server, owned_project, user
    ):
        resp = server.request(
            path=f"/project/{owned_project['_id']}/samples",
            method="PUT",
            body=json.dumps(["JHAMAA00001"]),
            type="application/json",
            user=user,
        )
        assertStatus(resp, 403)

    def test_put_project_samples_allowed_with_flag(
        self, server, owned_project, user, admin
    ):
        _grant_manage_samples(owned_project, user, admin)
        resp = server.request(
            path=f"/project/{owned_project['_id']}/samples",
            method="PUT",
            body=json.dumps(["JHAMAA00001"]),
            type="application/json",
            user=user,
        )
        assertStatusOk(resp)
        assert resp.json["samples"] == ["JHAMAA00001"]

    def test_put_project_samples_allowed_on_non_draft_project(
        self, server, owned_project, user, admin
    ):
        _grant_manage_samples(owned_project, user, admin)
        ProjectModel().update_project(owned_project, {"status": "accepted"}, admin)

        resp = server.request(
            path=f"/project/{owned_project['_id']}/samples",
            method="PUT",
            body=json.dumps(["JHAMAA00001"]),
            type="application/json",
            user=user,
        )
        assertStatusOk(resp)
        assert resp.json["samples"] == ["JHAMAA00001"]
