"""Resolving an IGSN to its record, and to the sample behind it.

Server-level tests only, per the split this repo keeps between ``server``-backed
and model-level modules (pytest-girder's plugin loading is process-global).
"""

import json

import pytest
from girder.constants import AccessType
from pytest_girder.assertions import assertStatus, assertStatusOk

from ..models.deposition import Deposition as DepositionModel

METADATA = {
    "titles": [{"title": "Scanned Sample"}],
    "creators": [{"name": "Test Creator", "nameType": "Organizational"}],
    "publisher": {"name": "Test Publisher"},
    "publicationYear": "2026",
    "descriptions": [
        {"description": "Test description", "descriptionType": "Abstract"}
    ],
}


def lookup(server, user, **params):
    return server.request(
        path="/deposition", method="GET", user=user, params=params
    )


@pytest.fixture
def batch(server, admin, igsn_settings, eagerWorkerTasks):
    """A tracked deposition with three batch children under it.

    ``track`` gives the parent a sample, which is what a scanner is really
    after; the children are what a prefix match wrongly picks up.
    """
    resp = server.request(
        path="/deposition",
        method="POST",
        user=admin,
        params={
            "prefix": "ABCDEF",
            "batch": 3,
            "track": True,
            "metadata": json.dumps(METADATA),
        },
    )
    assertStatusOk(resp)
    parent = resp.json
    assert parent["sampleId"] is not None

    children = lookup(server, admin, igsnPrefix=parent["igsn"], limit=0)
    assertStatusOk(children)
    assert len(children.json) == 4
    return parent


@pytest.mark.plugin("sample_tracker")
@pytest.mark.plugin("wholetale")
@pytest.mark.plugin("jsonforms")
class TestExactIgsnLookup:
    def test_an_exact_igsn_excludes_the_batch_children(self, server, admin, batch):
        resp = lookup(server, admin, igsn=batch["igsn"])

        assertStatusOk(resp)
        assert [d["igsn"] for d in resp.json] == [batch["igsn"]]

    def test_a_child_resolves_to_itself(self, server, admin, batch):
        child = f"{batch['igsn']}-002"

        resp = lookup(server, admin, igsn=child)

        assertStatusOk(resp)
        assert [d["igsn"] for d in resp.json] == [child]

    def test_a_prefix_still_matches_the_whole_family(self, server, admin, batch):
        """Regression guard: other callers depend on prefix semantics."""
        resp = lookup(server, admin, igsnPrefix=batch["igsn"], limit=0)

        assertStatusOk(resp)
        igsns = sorted(d["igsn"] for d in resp.json)
        assert igsns == [
            batch["igsn"],
            f"{batch['igsn']}-001",
            f"{batch['igsn']}-002",
            f"{batch['igsn']}-003",
        ]

    def test_lower_case_input_resolves(self, server, admin, batch):
        """A label is read as printed; IGSNs are stored upper-case."""
        resp = lookup(server, admin, igsn=batch["igsn"].lower())

        assertStatusOk(resp)
        assert [d["igsn"] for d in resp.json] == [batch["igsn"]]

    def test_surrounding_whitespace_is_ignored(self, server, admin, batch):
        resp = lookup(server, admin, igsn=f"  {batch['igsn']}\n")

        assertStatusOk(resp)
        assert [d["igsn"] for d in resp.json] == [batch["igsn"]]

    def test_an_unknown_igsn_is_an_empty_list(self, server, admin, batch):
        resp = lookup(server, admin, igsn="ABCDEF99999")

        assertStatusOk(resp)
        assert resp.json == []

    def test_igsn_and_igsn_prefix_together_are_rejected(self, server, admin, batch):
        resp = lookup(server, admin, igsn=batch["igsn"], igsnPrefix="ABCDEF")

        assertStatus(resp, 400)
        assert "not both" in resp.json["message"]


@pytest.mark.plugin("sample_tracker")
@pytest.mark.plugin("wholetale")
@pytest.mark.plugin("jsonforms")
class TestSampleIdInTheListResponse:
    """The point of the lookup: the trackable sample behind the identifier."""

    def test_a_reader_of_the_sample_sees_its_id(self, server, admin, batch):
        resp = lookup(server, admin, igsn=batch["igsn"])

        assertStatusOk(resp)
        assert resp.json[0]["sampleId"] == batch["sampleId"]

    def test_a_prefix_match_carries_it_too(self, server, admin, batch):
        resp = lookup(server, admin, igsnPrefix=batch["igsn"], limit=0)

        assertStatusOk(resp)
        parent = next(d for d in resp.json if d["igsn"] == batch["igsn"])
        assert parent["sampleId"] == batch["sampleId"]

    def test_someone_who_cannot_read_the_sample_gets_none(
        self, server, admin, user, batch
    ):
        """Deposition.filter() nulls it, which is what makes exposing it safe.

        The deposition is readable, the sample it points at is not.
        """
        deposition = DepositionModel().load(batch["_id"], force=True)
        DepositionModel().setUserAccess(
            deposition, user, AccessType.READ, save=True
        )

        resp = lookup(server, user, igsn=batch["igsn"])

        assertStatusOk(resp)
        assert [d["igsn"] for d in resp.json] == [batch["igsn"]]
        assert resp.json[0]["sampleId"] is None

    def test_the_sample_lookup_route_still_works(self, server, admin, batch):
        """The reverse direction, sample -> depositions, is untouched."""
        resp = lookup(server, admin, sampleId=batch["sampleId"])

        assertStatusOk(resp)
        assert [d["igsn"] for d in resp.json] == [batch["igsn"]]
