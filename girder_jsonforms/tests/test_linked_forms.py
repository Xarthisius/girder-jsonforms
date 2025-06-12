import json

import pytest
from girder_jsonforms.models.entry import FormEntry as Entry
from girder_jsonforms.models.form import Form
from pytest_girder.assertions import assertStatusOk


@pytest.fixture
def simple_schema():
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name"},
            "age": {"type": "integer", "title": "Age"},
        },
        "required": ["name", "age"],
    }


@pytest.fixture
def simple_form(db, user, simple_schema):
    """
    Create a simple form for testing purposes.
    """
    form = Form().create_form(
        "Test Form",
        "This is a test form for unit testing",
        simple_schema,  # Use the simple schema fixture
        user,
        uniqueField="name",  # Ensure we have a unique field for testing
    )
    Entry().create_entry(form, {"name": "John Doe", "age": 30}, None, None, user)
    Entry().create_entry(form, {"name": "Jane Doe", "age": 25}, None, None, user)
    yield form
    Form().remove(form)  # Clean up the form after the test is done


@pytest.mark.plugin("jsonforms")
def test_form_link(server, user, simple_form):
    schema = {
        "type": "object",
        "properties": {
            "powderName": {
                "type": "string",
                "enumSource": f"girder.formId:{simple_form['_id']}",
            },
            "someOtherField": {"type": "string"},
        },
    }

    # Create a linked form
    resp = server.request(
        path="/form",
        method="POST",
        params={
            "name": "Linked Form",
            "description": "This is a linked form",
            "schema": json.dumps(schema),  # Ensure the schema is JSON-encoded
            "uniqueField": "someOtherField",
        },
        user=user,
    )
    assertStatusOk(resp)
    linked_form_id = resp.json["_id"]

    def get_linked_form():
        """
        Helper function to retrieve the linked form by ID.
        """
        resp = server.request(
            path=f"/form/{linked_form_id}",
            method="GET",
            user=user,
        )
        assertStatusOk(resp)
        return resp.json

    # Materialize the linked form to ensure it was created correctly
    form = get_linked_form()
    assert isinstance(form["schema"]["properties"]["powderName"]["enumSource"], list)
    assert len(form["schema"]["properties"]["powderName"]["enumSource"]) == 1
    source = form["schema"]["properties"]["powderName"]["enumSource"][0]["source"]
    assert source[0]["title"] == "John Doe"
    assert source[1]["title"] == "Jane Doe"

    entry1_id = source[0]["value"]
    entry2_id = source[1]["value"]

    schema["properties"]["powderName"]["enumSource"] = (
        f"girder.formId:{simple_form['_id']}"
        ":{entry[data][age]} - {entry[_id]}"
    )
    resp = server.request(
        path=f"/form/{form['_id']}",
        method="PUT",
        params={
            "schema": json.dumps(schema),  # Update the schema to use the new format
        },
        user=user,
    )
    assertStatusOk(resp)
    form = get_linked_form()
    assert isinstance(form["schema"]["properties"]["powderName"]["enumSource"], list)
    assert len(form["schema"]["properties"]["powderName"]["enumSource"]) == 1
    source = form["schema"]["properties"]["powderName"]["enumSource"][0]["source"]
    assert source[0]["value"] == f"30 - {entry1_id}"
    assert source[1]["value"] == f"25 - {entry2_id}"
