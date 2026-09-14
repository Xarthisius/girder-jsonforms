import logging

from girder.constants import AccessType
from girder_worker.app import app
from ..models.deposition import Deposition
from ..models.entry import FormEntry as Entry

logger = logging.getLogger(__name__)


@app.task(queue="local")
def htmax_specimen_relations(entry, user):
    """
    Update IGSNs related identifiers based on the used formulation.
    """

    igsn = entry["data"]["assignedIGSN"]
    deposition = Deposition().findOne({"igsn": igsn})
    formulation_id = entry["data"]["powder"].split(";")[0]
    formulation = Entry().load(formulation_id, user=user, level=AccessType.READ)
    parents = []
    for ceramic in formulation["data"]["composition"]["ceramic"]:
        if ";" not in ceramic["compound"]:
            continue
        powder = Entry().load(
            ceramic["compound"].split(";")[0], user=user, level=AccessType.READ
        )
        if powder and powder["data"]["assignedIGSN"]:
            parents.append(powder["data"]["assignedIGSN"])

    if not parents:
        return
    parent_depositions = [Deposition().findOne({"igsn": parent}) for parent in parents]

    # IsDerivedFrom  IsSourceOf
    is_derived_from = [
        {
            "relationType": "IsDerivedFrom",
            "relatedIdentifier": _["igsn"],
            "relatedIdentifierType": "IGSN",
        }
        for _ in parent_depositions
    ]

    Deposition().collection.update_one(
        {"_id": deposition["_id"]},
        {"$addToSet": {"metadata.relatedIdentifiers": {"$each": is_derived_from}}},
    )

    is_source_of = {
        "relationType": "IsSourceOf",
        "relatedIdentifier": deposition["igsn"],
        "relatedIdentifierType": "IGSN",
    }
    Deposition().collection.update_many(
        {"_id": {"$in": [_["_id"] for _ in parent_depositions]}},
        {"$addToSet": {"metadata.relatedIdentifiers": is_source_of}},
    )
