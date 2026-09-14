import re
from girder.api.rest import getApiUrl
from girder.constants import AccessType
from girder.exceptions import GirderException
from girder.models.user import User
from girder_worker.app import app
from ..models.deposition import Deposition
from ..models.entry import FormEntry as Entry


@app.task(queue="local")
def run(entryId, enum_sources, userId=None):
    user = User().load(userId, force=True)
    entry = Entry().load(entryId, user=user, level=AccessType.WRITE)

    for key_path, source in enum_sources.items():
        key = key_path.split(".")[1]  # this only works for 'properties.key'
        try:
            values = entry["data"][key]
        except KeyError:
            print(f"Key '{key}' not found in entry data; skipping.")
            continue
        if not isinstance(values, list):
            values = [values]
        _handle_source(entry, source["formId"], values)


def _handle_source(entry, formId, values):
    entryId = str(entry["_id"])
    try:
        api_url = getApiUrl()
    except GirderException:
        api_url = "/api/v1"
    regex = re.compile(f"/api/v1/entry/{entryId}$")
    query = {"metadata.relatedIdentifiers.relatedIdentifier": regex}
    update_pipeline = {
        "$pull": {"metadata.relatedIdentifiers": {"relatedIdentifier": regex}}
    }
    # get 'formId' from any value in enum_sources dict
    # regex_pattern = re.compile(f"/api/v1/form/{formId}/schema")
    values_set = list(set(values))
    new_identifier_template = {
        "relationType": "HasMetadata",
        "relatedIdentifierType": "URL",
        "relatedMetadataScheme": "/".join((api_url, "form", str(formId), "schema")),
    }
    entry_url_prefix = "/".join((api_url, "entry"))
    update_pipeline = [
        {
            "$set": {
                "metadata.relatedIdentifiers": {
                    # We combine two arrays:
                    # 1. The identifiers that should be preserved (those not matching the regex).
                    # 2. The new list of identifiers that match the regex prefix, constructed from the values_set.
                    "$concatArrays": [
                        {
                            "$filter": {
                                "input": "$metadata.relatedIdentifiers",
                                "as": "item",
                                "cond": {
                                    "$not": {
                                        "$regexMatch": {
                                            "input": "$$item.relatedMetadataScheme",
                                            "regex": "/api/v1/form/"
                                            + str(formId)
                                            + "/schema",
                                        }
                                    }
                                },
                            }
                        },
                        {
                            "$map": {
                                "input": values_set,
                                "as": "val",
                                "in": {
                                    "$mergeObjects": [
                                        new_identifier_template,
                                        {
                                            "relatedIdentifier": {
                                                "$concat": [
                                                    entry_url_prefix,
                                                    "/",
                                                    "$$val",
                                                ]
                                            }
                                        },
                                    ]
                                },
                            }
                        },
                    ]
                }
            }
        }
    ]

    try:
        result = Deposition().collection.update_many(query, update_pipeline)
        print(
            f"Update operation completed successfully. Documents matched: {result.matched_count},"
            f" Documents modified: {result.modified_count}"
        )
    except Exception as e:
        print(f"An error occurred during the update operation: {e}")
