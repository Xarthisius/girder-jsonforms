import io
import json

import pandas as pd
import pytest
from pytest_girder.assertions import assertStatusOk

from girder_jsonforms.models.entry import FormEntry as Entry
from girder_jsonforms.models.form import Form


@pytest.fixture
def basic_schema():
    return {
        "title": "Basic Form",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "title": "Name",
                "description": "Enter your name",
            },
            "age": {"type": "integer", "title": "Age", "description": "Enter your age"},
            "email": {
                "type": "string",
                "format": "email",
                "title": "Email",
                "description": "Enter your email address",
            },
            "date_of_birth": {
                "type": "string",
                "format": "date",
                "title": "Date of Birth",
                "description": "Enter your date of birth",
            },
        },
    }


@pytest.fixture
def basic_form(db, user, basic_schema):
    """
    Fixture to create a basic form instance based on the provided schema.
    """
    form = Form().create_form(
        "Test Form",
        "This is a test form for unit testing",
        basic_schema,  # Use the simple schema fixture
        user,
        uniqueField="email",  # Ensure we have a unique field for testing
    )
    Entry().create_entry(
        form,
        {
            "name": "John Doe",
            "age": 30,
            "email": "john@doe.com",
            "date_of_birth": "1993-01-01",
        },
        None,
        None,
        user,
    )
    Entry().create_entry(
        form,
        {
            "name": "Jane Doe",
            "age": 25,
            "email": "jane@doe.com",
            "date_of_birth": "1992-10-12",
        },
        None,
        None,
        user,
    )
    yield form
    Form().remove(form)


@pytest.mark.plugin("jsonforms")
def test_export_import(server, user, basic_form):
    resp = server.request(
        path="/form/%s/export" % basic_form["_id"],
        method="GET",
        user=user,
        params={"exportFormat": "csv"},
        isJson=False,  # Ensure we get CSV format
    )
    assertStatusOk(resp)

    df = pd.read_csv(io.BytesIO(resp.body[0]))
    # Ensure the CSV has the correct columns and data
    assert not df.empty, "Exported CSV should not be empty"
    assert list(df.columns) == [
        "_id",
        "data.name",
        "data.age",
        "data.email",
        "data.date_of_birth",
    ], "CSV columns do not match expected schema"
    assert len(df) == 2, "CSV should contain two entries"

    first_entry_id = df.iloc[0]["_id"]
    resp = server.request(
        path=f"/entry/{first_entry_id}",
        method="GET",
        user=user,
    )
    assertStatusOk(resp)
    entry = resp.json
    # Verify the first entry matches the original data
    for key in ["name", "age", "email", "date_of_birth"]:
        assert (
            entry["data"][key] == df.iloc[0][f"data.{key}"]
        ), f"First entry {key} does not match"

    # Now modify the CSV to test import
    # Change the age of the first entry to 35
    df.at[0, "data.age"] = 35
    # Remove _id column
    df = df.drop(columns=["_id"])
    new_row = pd.DataFrame(
        {
            "data.name": ["Eve McClusky"],
            "data.age": [28],
            "data.email": ["eve@mcc.com"],
            "data.date_of_birth": ["1995-05-15"],
        }
    )

    df = pd.concat([df, new_row], ignore_index=True)
    # Convert DataFrame back to CSV for import
    csv_data = df.to_csv(index=False).encode("utf-8")

    # Now dryRun import the modified CSV
    resp = server.request(
        path="/form/%s/import" % basic_form["_id"],
        method="POST",
        user=user,
        params={"dryRun": True},
        body=csv_data,
        type="application/csv",  # Ensure we specify CSV content typ
        isJson=True,
    )
    assertStatusOk(resp)
    assert json.loads(resp.json) == {"new": 1, "updated": 2, "failed": 0}

    resp = server.request(
        path=f"/entry/{first_entry_id}",
        method="GET",
        user=user,
    )
    assertStatusOk(resp)
    entry = resp.json
    assert (
        entry["data"]["age"] == 30
    ), "Age should not have changed for existing entry during dry run"
    assert (
        Entry().collection.count_documents({"formId": basic_form["_id"]}) == 2
    ), "There should still be 2 entries in the form"

    resp = server.request(
        path="/form/%s/import" % basic_form["_id"],
        method="POST",
        user=user,
        params={"dryRun": False},
        body=csv_data,
        type="application/csv",  # Ensure we specify CSV content typ
        isJson=True,
    )
    assertStatusOk(resp)
    assert json.loads(resp.json) == {"new": 1, "updated": 2, "failed": 0}

    resp = server.request(
        path=f"/entry/{first_entry_id}",
        method="GET",
        user=user,
    )
    assertStatusOk(resp)
    entry = resp.json
    assert entry["data"]["age"] == 35, "Age should have changed to 35"
    assert (
        Entry().collection.count_documents({"formId": basic_form["_id"]}) == 3
    ), "There should be 3 entries in the form"

    # Verify the new entry was created
    assert (
        Entry().findOne({"formId": basic_form["_id"], "data.name": "Eve McClusky"})
        is not None
    ), "New entry 'Eve McClusky' should have been created during import"
