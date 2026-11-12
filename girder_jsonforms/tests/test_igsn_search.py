"""The ``igsn`` resource/search mode (the deposition page's data listing).

Server-level tests only, per the split this repo keeps between ``server``-backed
and model-level modules (pytest-girder's plugin loading is process-global).
"""

import json

import pytest
from girder.models.folder import Folder
from girder.models.item import Item
from girder.utility.model_importer import ModelImporter
from pytest_girder.assertions import assertStatusOk

from .. import igsn_search

IGSNS = [
    "APLMAA00001",
    "APLMAA00001-001",
    "APLMAA00001-001-001",
    "APLMAA00001-002",
    "APLMAA00002",
    "JHAMAA00001",
]
MODELS = {"item": Item, "folder": Folder}


@pytest.fixture
def tagged(admin):
    """One item and one subfolder per IGSN, under a private folder.

    meta.igsn is written straight to Mongo: saving a document with it fires the
    AIMD project propagation, which is beside the point here. The last IGSN
    contains the queries only in the middle and must never match. Inserted in
    reverse so natural order disagrees with the sort the paging relies on.
    """
    root = Folder().createFolder(
        admin, "igsn-search", parentType="user", public=False, creator=admin
    )
    for igsn in reversed(IGSNS + ["XXAPLMAA00001"]):
        item = Item().createItem(igsn, admin, root)
        Item().update({"_id": item["_id"]}, {"$set": {"meta.igsn": igsn}})
        folder = Folder().createFolder(root, f"{igsn} folder", creator=admin)
        Folder().update({"_id": folder["_id"]}, {"$set": {"meta.igsn": igsn}})
    return root


@pytest.fixture(params=["indexed", "unindexed"])
def index(request, admin):
    """Run once as deployed, and once with meta.igsn_1 dropped.

    The index already yields documents in IGSN order, which would hide a
    missing sort; without it the planner scans in natural (insertion) order.
    """
    if request.param == "unindexed":
        for model in MODELS.values():
            model().collection.drop_index("meta.igsn_1")
    yield request.param
    if request.param == "unindexed":
        for model in MODELS.values():
            model().collection.create_index("meta.igsn")


def search(server, user, q, type="item", **params):
    resp = server.request(
        path="/resource/search",
        user=user,
        params={"q": q, "mode": "igsn", "types": json.dumps([type]), **params},
    )
    assertStatusOk(resp)
    return [doc["meta"]["igsn"] for doc in resp.json[type]]


@pytest.mark.plugin("jsonforms")
@pytest.mark.parametrize("type", MODELS)
def test_prefix_match_includes_children_only(server, admin, tagged, type):
    assert search(server, admin, "APLMAA00001-001", type) == [
        "APLMAA00001-001",
        "APLMAA00001-001-001",
    ]


@pytest.mark.plugin("jsonforms")
@pytest.mark.parametrize("type", MODELS)
def test_query_is_case_insensitive_and_trimmed(server, admin, tagged, type):
    assert search(server, admin, " aplmaa00002 ", type) == ["APLMAA00002"]


@pytest.mark.plugin("jsonforms")
@pytest.mark.parametrize("type", MODELS)
def test_query_is_not_a_regex(server, admin, tagged, type):
    assert search(server, admin, ".*", type) == []


@pytest.mark.plugin("jsonforms")
@pytest.mark.parametrize("type", MODELS)
def test_paging_is_stable(server, admin, tagged, index, type):
    pages = [
        search(server, admin, "APLMAA", type, limit=2, offset=o) for o in (0, 2, 4)
    ]
    assert pages == [
        ["APLMAA00001", "APLMAA00001-001"],
        ["APLMAA00001-001-001", "APLMAA00001-002"],
        ["APLMAA00002"],
    ]


@pytest.mark.plugin("jsonforms")
@pytest.mark.parametrize("type", MODELS)
def test_uses_the_meta_igsn_index(server, admin, tagged, monkeypatch, type):
    model = MODELS[type]()
    plans = []
    find = model.find

    def spy(query, *args, **kwargs):
        cursor = find(query, *args, **kwargs)
        plans.append(cursor.clone().explain()["queryPlanner"]["winningPlan"])
        return cursor

    monkeypatch.setattr(model, "find", spy)
    igsn_search("APLMAA00001", [type], admin, 0, 10, 0)
    plan = json.dumps(plans[0])
    assert "meta.igsn_1" in plan
    assert "COLLSCAN" not in plan
    # Bounded to the prefix, not a walk over every key in the index.
    assert '"[\\"APLMAA00001\\", \\"APLMAA00002\\")"' in plan


@pytest.mark.plugin("jsonforms")
def test_model_without_permission_filtering_is_paged_in_mongo(
    server, admin, tagged, index, monkeypatch
):
    """The fallback for a model with no filterResultsByPermission.

    Both allowed models have one, so this branch is only reachable for a
    model that lacks it; a stand-in exposing just ``find`` takes that path.
    """

    class Unfiltered:
        find = Item().find

    monkeypatch.setattr(
        ModelImporter, "model", staticmethod(lambda *args, **kwargs: Unfiltered)
    )
    results = igsn_search(" aplmaa ", ["item", "user"], admin, 0, 2, 2)
    assert list(results) == ["item"]
    assert [doc["meta"]["igsn"] for doc in results["item"]] == [
        "APLMAA00001-001-001",
        "APLMAA00001-002",
    ]
    # Projected to the allowed fields only -- no ACL fields leak out.
    assert not {"access", "public"} & set(results["item"][0])
