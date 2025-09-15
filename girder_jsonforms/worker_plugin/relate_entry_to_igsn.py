import re

from girder.api.rest import getApiUrl
from girder.exceptions import GirderException
from girder_worker.app import app

from ..models.deposition import Deposition


@app.task(queue="local")
def run(entry, igsn_field="assignedIGSN"):
    # Remove relatedIdentifier from previous depositions if any
    regex = re.compile(f"/entry/{entry['_id']}$")
    query = {"metadata.relatedIdentifiers.relatedIdentifier": regex}
    update = {"$pull": {"metadata.relatedIdentifiers": {"relatedIdentifier": regex}}}
    Deposition().update(query, update)

    # define new relatedIdentifier
    try:
        api_url = getApiUrl()
    except GirderException:
        api_url = "/api/v1"
    related_identifier = {
        "relationType": "HasMetadata",
        "relatedIdentifier": "/".join((api_url, "entry", str(entry["_id"]))),
        "relatedIdentifierType": "URL",
        "relatedMetadataScheme": "/".join(
            (api_url, "form", str(entry["formId"]), "schema")
        ),
    }

    # add relatedIdentifier to all depositions with the same IGSN
    igsn = entry["data"].get(igsn_field)
    query = {"igsn": igsn}
    update = {"$addToSet": {"metadata.relatedIdentifiers": related_identifier}}
    Deposition().update(query, update)
