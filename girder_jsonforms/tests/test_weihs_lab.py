import json
import os

import pytest
from pytest_girder.assertions import assertStatusOk
from girder_jsonforms.models.deposition import Deposition


def _load_schema(schema_file):
    with open(f"{os.path.dirname(__file__)}/data/{schema_file}", "r") as f:
        return json.load(f)


def _create_form(server, user, schema, unique_field="name"):
    # Create a form in the server for power supplies
    resp = server.request(
        path="/form",
        method="POST",
        user=user,
        params={
            "name": schema["title"],
            "description": schema["description"],
            "schema": json.dumps(schema),
            "pathTemplate": None,
            "entryFileName": None,
            "gdriveFolderId": None,
            "uniqueField": unique_field,  # Use the unique field specified
        },
    )
    assertStatusOk(resp)
    return resp.json


def _delete_form(server, admin, form):
    resp = server.request(
        path="/form/%s" % form["_id"],
        method="DELETE",
        user=admin,
    )
    assertStatusOk(resp)


@pytest.fixture
def powders():
    return [
        {
            "prefix": "JHAMAL",
            "metadata": {
                "titles": [{"title": "Pure Nb powder"}],
            },
        },
        {
            "prefix": "JHAMAL",
            "metadata": {
                "titles": [{"title": "Pure Ti powder"}],
            },
        },
    ]


@pytest.fixture
def guns():
    """
    Fixture to provide gun metadata for testing.
    """
    return [
        {
            "name": "Gun 1",
            "manufacturer": "MDX",
            "geometry": "Geometry 1",
            "serialNumber": "123456",
            "gunType": "Gun Type 1",
            "size": "Small",
        },
        {
            "name": "Gun 2",
            "manufacturer": "MDX",
            "geometry": "Geometry 2",
            "serialNumber": "654321",
            "gunType": "Gun Type 2",
            "size": "Medium",
        },
        {
            "name": "Gun 3",
            "manufacturer": "MDX",
            "geometry": "Geometry 3",
            "serialNumber": "789012",
            "gunType": "Gun Type 3",
            "size": "Large",
        },
        {
            "name": "Gun 4",
            "manufacturer": "MDX",
            "geometry": "Geometry 1",
            "serialNumber": "210987",
            "gunType": "Gun Type 1",
            "size": "Small",
        },
    ]


@pytest.fixture
def power_supplies():
    """
    Fixture to provide power supplies for testing.
    """
    return [
        {"name": "PS1", "manufacturer": "MDX", "power": 1.5, "serialNumber": "109992"},
        {"name": "PS2", "manufacturer": "MDX", "power": 1.5, "serialNumber": "109995"},
        {"name": "PS3", "manufacturer": "MDX", "power": 1.5, "serialNumber": "3175"},
        {"name": "PS4", "manufacturer": "MDX", "power": 2.5, "serialNumber": "139138"},
    ]


@pytest.fixture
def ps_form(server, user, admin):
    """
    Fixture to create a power supply form for testing.
    """
    form = _create_form(
        server, user, _load_schema("power_supply_schema.json"), unique_field="name"
    )
    yield form
    _delete_form(server, admin, form)


@pytest.fixture
def gun_form(server, user, admin):
    """
    Fixture to create a gun form for testing.
    """
    # Create a form in the server for guns
    form = _create_form(
        server, user, _load_schema("gun_schema.json"), unique_field="name"
    )
    yield form
    _delete_form(server, admin, form)


@pytest.fixture
def sources(server, user, target_source_form, powders):
    for powder in powders:
        element = powder["metadata"]["titles"][0]["title"].split(" ")[1]
        resp = server.request(
            path="/deposition",
            method="POST",
            user=user,
            params={
                "prefix": powder["prefix"],
                "metadata": json.dumps(powder["metadata"]),
            },
        )
        assertStatusOk(resp)
        deposition = resp.json

        data = {
            "IGSN": deposition["igsn"],
            "contaminants": "S, Fe, Cl",
            "depositionId": deposition["_id"],
            "element": element,
            "lookup": f"{deposition['igsn']} - {deposition['_id']}",
            "manufacturer": "MDX",
            "purchaseOrder": "https://foo.com/1234",
            "purity": 99.99,
            "sampleId": f"{deposition['igsn']} - {element}",
        }
        resp = server.request(
            path="/entry",
            method="POST",
            user=user,
            params={
                "formId": target_source_form["_id"],
                "data": json.dumps(data),
            },
        )
        assertStatusOk(resp)


@pytest.fixture
def target_source_form(server, user):
    """
    Fixture to create a target source form for testing.
    """
    # Create a form in the server for target sources
    form = _create_form(
        server, user, _load_schema("target_schema.json"), unique_field="sampleId"
    )
    yield form
    # Clean up the form after use
    _delete_form(server, user, form)


@pytest.fixture
def target_form(server, user, admin, target_source_form):
    """
    Fixture to create a target source form for testing.
    """
    # Create a form in the server for target sources
    schema = _load_schema("target_schema.json")
    source = (
        f"girder.formId:{target_source_form['_id']}"
        ":{entry[data][element]} - {entry[_id]}"
    )
    schema["properties"]["sources"]["items"]["properties"]["source"][
        "enumSource"
    ] = source
    form = _create_form(server, user, schema, unique_field="name")
    yield form
    _delete_form(server, admin, form)


@pytest.fixture
def sputter_run_form(server, user, admin, gun_form, target_form, ps_form):
    schema = _load_schema("sputter_run_schema.json")
    schema["definitions"]["sputter"]["properties"]["gun"][
        "enumSource"
    ] = f"girder.formId:{gun_form['_id']}"
    schema["definitions"]["sputter"]["properties"]["target"][
        "enumSource"
    ] = f"girder.formId:{target_form['_id']}"
    schema["definitions"]["sputter"]["properties"]["powerSupply"][
        "enumSource"
    ] = f"girder.formId:{ps_form['_id']}"

    form = _create_form(
        server,
        user,
        schema,
        unique_field="sputterRunId",  # Ensure this is unique for sputter runs
    )
    yield form
    _delete_form(server, admin, form)


@pytest.fixture
def sputter_record():
    return {
        "basePressure": 1e-06,
        "bilayerSpacing": 100,
        "blueGun": {"used": False},
        "cryoTemp": 12,
        "gasFlowRate": 1,
        "gasType": "Argon",
        "greenGun": {"used": False},
        "igsn": {
            "_text1": "",
            "groupJH": "A",
            "institution": "JH",
            "material": "BO",
            "subCols": 2,
            "subRows": 2,
            "submaterialBO": "X",
            "substrates": ["2", "8"],
            "title": "",
        },
        "igsn_field": "sputterRunId",
        "igsn_prefix": "JHABOX",
        "igsn_request": True,
        "igsn_suffix": "",
        "igsn_track": True,
        "leakRate": 1e-06,
        "measurements": [],
        "name": "",
        "orangeGun": {"used": False},
        "purpleGun": {"used": False},
        "sputterRunId": "JHABOX",
        "sputterType": "Horizontal",
        "substrateOrientation": 0,
        "substrateType": "Si",
        "thickness": 100,
    }


@pytest.mark.plugin("jsonforms")
def test_full_flow(server, user, sputter_run_form, sputter_record):
    Deposition()  # Ensure the Deposition model is loaded for the test
    resp = server.request(
        path="/entry",
        method="POST",
        user=user,
        params={
            "formId": sputter_run_form["_id"],
            "data": json.dumps(sputter_record),
        },
    )
    assertStatusOk(resp)
    entry = resp.json
    assert not entry["data"]["igsn_request"], "IGSN request should be consumed"
    assert (
        entry["data"]["sputterRunId"] == "JHABOX00001"
    ), "sputterRunId should match the expected value"
    assert (
        entry["data"]["igsn_suffix"] == "00001"
    ), "igsn_suffix should be set to '00001' after the first entry creation"

    resp = server.request(
        path="/deposition",
        method="GET",
        user=user,
        params={
            "q": "JHABOX00001",  # The IGSN we expect from the sputter run
        },
    )
    assertStatusOk(resp)
    assert {_["igsn"] for _ in resp.json} == {
        "JHABOX00001",
        "JHABOX00001/S2R1C1",
        "JHABOX00001/S2R1C2",
        "JHABOX00001/S2R2C1",
        "JHABOX00001/S2R2C2",
        "JHABOX00001/S8R1C1",
        "JHABOX00001/S8R1C2",
        "JHABOX00001/S8R2C1",
        "JHABOX00001/S8R2C2",
    }
