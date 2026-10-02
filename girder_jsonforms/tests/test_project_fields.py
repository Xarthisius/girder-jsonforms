"""Covers the proposal-form fields added for the 2026-09 feedback round.

The point of these tests is not that the values are stored -- it is that they
survive a round trip through the REST layer. `project_schema` ends with
`additionalProperties: False`, so an unknown field fails the whole save, and
`@filtermodel` drops anything missing from `exposeFields`, so a field can be
stored and still never come back. Both failures look like "the form lost my
input" from the browser.
"""

import json

import pytest
from girder.exceptions import ValidationException
from pytest_girder.assertions import assertStatus, assertStatusOk

from ..models.project import Project as ProjectModel

FULL_PROJECT = {
    "name": "Shock response of amorphous alloys",
    "accessCategory": "external-academic",
    "organization": "University of Elsewhere",
    "dataClassification": "confidential-proprietary",
    "assistanceRequired": True,
    "daysRequested": "3 days, ideally consecutive",
    "experimentPlan": "Indent 12 samples, 3 loads each.",
    "safety": {
        "sampleHazards": ["flammable", "energetic"],
        "otherHazards": ["laser", "high-voltage"],
        "description": "Thin energetic films; HELIX drive laser is class 4.",
    },
    "funding": {
        "grants": [
            {"agency": "NSF", "grantNumber": "DMR-0000000"},
            {"agency": "DOE", "grantNumber": "DE-SC0000000"},
        ],
        "internalBudgetNumber": "",
    },
}


@pytest.fixture(autouse=True)
def _eager_tasks(eagerWorkerTasks):
    """Run celery tasks inline.

    ``lib/events.py:ensure_group`` dispatches ``register_project_with_orcid``
    on every save of an existing project, and there is no broker in the test
    environment. Creates are unaffected -- the handler returns early before the
    dispatch while the document still has no ``_id`` -- so this only matters
    once a test issues a PUT.
    """


def _create(server, user, doc):
    resp = server.request(
        path="/project",
        method="POST",
        body=json.dumps(doc),
        type="application/json",
        user=user,
    )
    return resp


@pytest.mark.plugin("jsonforms")
class TestProjectFieldRoundTrip:
    def test_every_new_field_survives_create_and_fetch(self, server, user, admin):
        resp = _create(server, user, FULL_PROJECT)
        assertStatusOk(resp)
        created = resp.json

        # Stored and exposed on the create response...
        for key, expected in FULL_PROJECT.items():
            assert created[key] == expected, f"{key} did not survive create"

        # ...and still there on a separate fetch, which is the exposeFields check.
        resp = server.request(
            path=f"/project/{created['_id']}", method="GET", user=user
        )
        assertStatusOk(resp)
        for key, expected in FULL_PROJECT.items():
            assert resp.json[key] == expected, f"{key} did not survive fetch"

    def test_fields_survive_update(self, server, user, admin):
        resp = _create(server, user, {"name": "Draft"})
        assertStatusOk(resp)
        project_id = resp.json["_id"]

        resp = server.request(
            path=f"/project/{project_id}",
            method="PUT",
            body=json.dumps(FULL_PROJECT),
            type="application/json",
            user=user,
        )
        assertStatusOk(resp)
        for key, expected in FULL_PROJECT.items():
            assert resp.json[key] == expected, f"{key} did not survive update"

    def test_unset_fields_stay_absent(self, server, user, admin):
        """No accidental defaults: "not answered" must stay distinguishable from
        an answer, especially for `safety` -- an empty hazard list means the
        applicant ticked None, not that they were never asked."""
        resp = _create(server, user, {"name": "Bare draft"})
        assertStatusOk(resp)
        for key in FULL_PROJECT:
            if key == "name":
                continue
            assert key not in resp.json, f"{key} was defaulted when it should be unset"


@pytest.mark.plugin("jsonforms")
class TestProjectMemberFields:
    member = {
        "email": "postdoc@example.org",
        "role": "user",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "orcidId": "0000-0002-1825-0097",
        "isPointOfContact": True,
        "onSite": False,
        "status": "postdoc",
        "institution": "Somewhere Else University",
    }

    def test_member_fields_survive_round_trip(self, server, user, admin):
        resp = _create(server, user, {"name": "With members", "members": [self.member]})
        assertStatusOk(resp)
        stored = resp.json["members"][0]
        for key, expected in self.member.items():
            assert stored[key] == expected, f"members[].{key} did not survive"

    def test_unknown_member_field_is_rejected(self, server, user, admin):
        """The member sub-schema is `additionalProperties: False` too, so a typo
        in the frontend fails the save rather than being dropped."""
        bad = {**self.member, "pointOfContact": True}  # near-miss for isPointOfContact
        resp = _create(server, user, {"name": "Typo", "members": [bad]})
        assertStatus(resp, 400)

    def test_role_still_required(self, server, user, admin):
        """`role` is the access level applied on acceptance
        (lib/events.py:_role_to_access_level) and selects decision-mail
        recipients, so the new `status` field does not replace it."""
        no_role = {k: v for k, v in self.member.items() if k != "role"}
        resp = _create(server, user, {"name": "No role", "members": [no_role]})
        assertStatus(resp, 400)


@pytest.mark.plugin("jsonforms")
class TestProjectFieldValidation:
    @pytest.mark.parametrize(
        "doc",
        [
            {"accessCategory": "jhu-ish"},
            {"dataClassification": "secret"},
            {"safety": {"sampleHazards": ["spicy"]}},
            {"safety": {"otherHazards": ["cold"]}},
            {"safety": {"hazards": []}},
            {"funding": {"grants": [{"agency": "NSF", "number": "x"}]}},
            {"assistanceRequired": "yes"},
            {"daysRequested": 3},
        ],
        ids=[
            "bad-access-category",
            "bad-classification",
            "bad-sample-hazard",
            "bad-other-hazard",
            "unknown-safety-key",
            "unknown-grant-key",
            "assistance-not-boolean",
            "days-not-string",
        ],
    )
    def test_invalid_values_are_rejected(self, server, user, admin, doc):
        resp = _create(server, user, {"name": "Invalid", **doc})
        assertStatus(resp, 400)

    def test_priority_is_gone(self, server, user, admin):
        """`priority` implied a ranking the lab never allocated on and is
        replaced by the unranked `accessCategory`. It is not deprecated in
        place -- a frontend still sending it should fail loudly rather than
        have the value silently ignored."""
        resp = _create(server, user, {"name": "Old field", "priority": 3})
        assertStatus(resp, 400)

    def test_unknown_top_level_field_is_still_rejected(self, server, user, admin):
        """Guards the property the whole plan is sequenced around: a field the
        backend has not been taught about fails the save outright."""
        resp = _create(server, user, {"name": "Unknown", "notAField": 1})
        assertStatus(resp, 400)

    def test_model_level_validation_message_names_the_field(self, server, user, admin):
        with pytest.raises(ValidationException, match="Project validation failed"):
            ProjectModel().create_project(
                {
                    "name": "Invalid",
                    "creatorId": user["_id"],
                    "accessCategory": "nonsense",
                },
                user,
            )
