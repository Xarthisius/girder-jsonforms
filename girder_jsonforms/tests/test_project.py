import datetime
import json

import pytest
from girder.exceptions import ValidationException
from pytest_girder.assertions import assertStatusOk

from ..models.project import Project as ProjectModel


def _year_suffix():
    return f"{datetime.datetime.now():%y}"


@pytest.fixture
def project_doc():
    return {
        "name": "Test Project",
        "description": "A project for testing prefix handling",
    }


@pytest.mark.plugin("jsonforms")
class TestCreateProjectPrefix:
    """Covers the optional `prefix` argument added to Project.create_project."""

    def test_default_prefix_is_jhu(self, server, user, admin, project_doc):
        project = ProjectModel().create_project(
            {**project_doc, "creatorId": user["_id"]}, user
        )
        assert project["projectId"].startswith(f"JHU{_year_suffix()}")

    def test_custom_prefix_is_used(self, server, user, admin, project_doc):
        project = ProjectModel().create_project(
            {**project_doc, "creatorId": user["_id"]}, user, prefix="TAM"
        )
        assert project["projectId"].startswith(f"TAM{_year_suffix()}")

    def test_distinct_prefixes_get_independent_counters(
        self, server, user, admin, project_doc
    ):
        first = ProjectModel().create_project(
            {**project_doc, "creatorId": user["_id"]}, user, prefix="ABC"
        )
        second = ProjectModel().create_project(
            {**project_doc, "creatorId": user["_id"]}, user, prefix="XYZ"
        )
        assert first["projectId"] != second["projectId"]
        assert first["projectId"].startswith(f"ABC{_year_suffix()}")
        assert second["projectId"].startswith(f"XYZ{_year_suffix()}")

    def test_invalid_prefix_length_is_rejected(self, server, user, admin, project_doc):
        with pytest.raises(ValidationException, match="5 characters long"):
            ProjectModel().create_project(
                {**project_doc, "creatorId": user["_id"]}, user, prefix="AB"
            )


@pytest.mark.plugin("jsonforms")
class TestCreateProjectRestPrefix:
    """Covers the `prefix` query parameter added to POST /project."""

    def test_create_without_prefix_defaults_to_jhu(self, server, user, project_doc):
        resp = server.request(
            path="/project",
            method="POST",
            body=json.dumps(project_doc),
            type="application/json",
            user=user,
        )
        assertStatusOk(resp)
        assert resp.json["projectId"].startswith(f"JHU{_year_suffix()}")

    def test_create_with_prefix_overrides_default(self, server, user, project_doc):
        resp = server.request(
            path="/project",
            method="POST",
            params={"prefix": "TAM"},
            body=json.dumps(project_doc),
            type="application/json",
            user=user,
        )
        assertStatusOk(resp)
        assert resp.json["projectId"].startswith(f"TAM{_year_suffix()}")
