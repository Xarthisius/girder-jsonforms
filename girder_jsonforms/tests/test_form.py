import json

import pytest
import responses
from girder.constants import AccessType
from pytest_girder.assertions import assertStatus, assertStatusOk


@pytest.fixture
def basic_schema():
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name"},
            "age": {"type": "integer", "title": "Age"},
        },
        "required": ["name", "age"],
    }


@pytest.mark.plugin("jsonforms")
def test_basic_rest(server, user, admin, basic_schema):
    """
    Test basic functionality of the jsonforms plugin.
    """
    resp = server.request(
        path="/form",
        method="POST",
        params={
            "name": "My form",
            "description": "This is a test form",
            "uniqueField": "name",
        },
        body=json.dumps(basic_schema),  # Ensure the schema is JSON-encoded
        type="application/json",
        user=admin,
    )
    assertStatusOk(resp)
    form = resp.json
    # Ensure the form was created
    assert form is not None
    assert form["_id"] is not None
    assert form["name"] == "My form"
    assert form["description"] == "This is a test form"
    assert json.loads(form["schema"]) == basic_schema

    resp = server.request(
        path="/form/%s" % form["_id"],
        method="GET",
        user=user,  # Use a regular user to test permissions
    )
    assertStatus(resp, 403)

    resp = server.request(
        path="/form/%s/access" % form["_id"],
        method="PUT",
        user=admin,
        params={
            "access": json.dumps(
                {
                    "users": [
                        {
                            "login": admin["login"],  # Ensure admin can access
                            "level": AccessType.ADMIN,
                            "id": str(admin["_id"]),  # Ensure we specify the user id
                            "flags": [],
                            "name": f"{admin['firstName']} {admin['lastName']}",
                        },
                        {
                            "login": user["login"],  # Ensure admin can access
                            "level": AccessType.WRITE,
                            "id": str(user["_id"]),  # Ensure we specify the user id
                            "flags": [],
                            "name": f"{user['firstName']} {user['lastName']}",
                        },
                    ],
                    "groups": [],
                }
            ),
        },
    )
    assertStatusOk(resp)

    resp = server.request(
        path="/form/%s/access" % form["_id"],
        method="GET",
        user=admin,
    )
    assertStatusOk(resp)
    access = resp.json
    assert len(access["users"]) == 2, "There should be two users with access."
    assert len(access["groups"]) == 0, "There should be no groups with access."

    resp = server.request(
        path="/form/%s" % form["_id"],
        method="GET",
        user=user,  # Use a regular user to test permissions
    )
    assertStatusOk(resp)
    form = resp.json

    resp = server.request(
        path="/form",
        method="GET",
        user=user,  # Use a regular user to test permissions
    )
    assertStatusOk(resp)
    assert len(resp.json) == 1
    assert resp.json[0]["_id"] == form["_id"], \
        "The user should be able to see the form after access was granted."

    resp = server.request(
        path="/form",
        method="GET",
        user=user,
        params={"entryFileName": "empty"},
    )
    assertStatusOk(resp)
    assert len(resp.json) == 0

    resp = server.request(
        path=f"/form/{form['_id']}",
        method="PUT",
        user=admin,
        params={
            "name": "Updated form",
            "description": "This is an updated test form",
            "entryFileName": "updated_form.json",
            "serialize": True,
            "jsHelpers": "",
            "uniqueField": "name",
            "pathTemplate": "somewhere/blah",
        },
    )
    assertStatusOk(resp)
    updated_form = resp.json

    assert updated_form is not None
    assert updated_form["_id"] == form["_id"]
    assert updated_form["name"] == "Updated form"
    assert updated_form["description"] == "This is an updated test form"
    assert updated_form["entryFileName"] == "updated_form.json"
    assert updated_form["serialize"] is True
    assert updated_form["jsHelpers"] == ""
    assert updated_form["uniqueField"] == "name"
    assert updated_form["pathTemplate"] == "somewhere/blah"

    resp = server.request(
        path="/form",
        method="GET",
        user=user,
        params={"entryFileName": "updated_form.json"},
    )
    assertStatusOk(resp)
    assert len(resp.json) == 1

    # Now delete the form
    resp = server.request(
        path="/form/%s" % form["_id"],
        method="DELETE",
        user=user,
    )
    assertStatusOk(resp)


@responses.activate
@pytest.mark.plugin("jsonforms")
def test_http_schema(server, user, basic_schema):
    """
    'schema' paramater can be a json encoded object or string with url that returns json. Check the
    latter case.
    """

    responses.get(
        "https://some.url/test/schema",  # This URL will be used in the request
        body=json.dumps(basic_schema),  # Return the basic schema as JSON
        status=200,
        content_type="application/json",
    )

    # Now create a form using the HTTP endpoint
    resp = server.request(
        path="/form",
        method="POST",
        params={
            "name": "My form",
            "description": "This is a test form",
            "uniqueField": "name",
        },
        body="https://some.url/test/schema",  # Use the URL as the schema
        type="plain/text",
        user=user,
    )
    assertStatusOk(resp)
    form = resp.json
    assert form is not None
    assert form["schema"] == "https://some.url/test/schema", \
        "The schema should be the URL we provided, not the actual schema content."

    resp = server.request(
        path="/form/%s" % form["_id"],
        method="GET",
        user=user,
    )
    assertStatusOk(resp)
    # Ensure the schema was resolved correctly
    assert resp.json["schema"] == basic_schema, \
        "The resolved schema should match the original basic schema."
