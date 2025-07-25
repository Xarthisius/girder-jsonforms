import datetime
import re
import urllib.parse
import requests

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import (
    Resource,
    filtermodel,
)
from girder.constants import AccessType, SortDir, TokenScope
from girder.exceptions import RestException
from girder.models.setting import Setting
from girder.utility.progress import noProgress
from girder_sample_tracker.models.sample import Sample
from ..models.deposition import Deposition as DepositionModel
from ..settings import PluginSettings


orcid_headers = None


def get_orcid_headers():
    global orcid_headers
    if orcid_headers is None:
        # ORCID API endpoint
        url = "https://pub.orcid.org/oauth/token"

        # Headers and payload
        data = {
            "client_id": Setting().get("oauth.orcid_client_id"),
            "client_secret": Setting().get("oauth.orcid_client_secret"),
            "grant_type": "client_credentials",
            "scope": "/read-public",
        }
        headers = {"Accept": "application/json"}

        # Make the POST request
        token_response = requests.post(url, headers=headers, data=data)
        token_response.raise_for_status()

        orcid_headers = {
            "Accept": "application/vnd.orcid+json",
            "Authorization": "Bearer " + token_response.json()["access_token"],
        }

    return orcid_headers


class Deposition(Resource):
    def __init__(self):
        super(Deposition, self).__init__()
        self.resourceName = "deposition"
        self.route("GET", (), self.list_deposition)
        self.route("POST", (), self.create_deposition)
        self.route("GET", ("autocomplete",), self.autocomplete)
        self.route("GET", ("settings",), self.get_settings)
        self.route("DELETE", (":id",), self.delete_deposition)
        self.route("GET", (":id",), self.get_deposition)
        self.route("PUT", (":id",), self.update_deposition)
        self.route("GET", (":id", "access"), self.get_deposition_access)
        self.route("PUT", (":id", "access"), self.update_deposition_access)
        self.route("POST", (":id", "split"), self.create_child_deposition)

    @access.public
    @autoDescribeRoute(
        Description("List all depositions.")
        .param(
            "igsnPrefix",
            "Pass to lookup a form by exact IGSN prefix match.",
            required=False,
            dataType="string",
        )
        .param(
            "sampleId",
            "Pass to lookup a form by exact sample tracker ID match.",
            required=False,
            dataType="string",
        )
        .param(
            "q",
            "The query to search for on selected fields (title, igsn, alternateIdentifier)",
            required=False,
            dataType="string",
        )
        .param(
            "level",
            "The minimum access level to filter the forms by",
            dataType="integer",
            required=False,
            default=AccessType.READ,
            enum=[AccessType.NONE, AccessType.READ, AccessType.WRITE, AccessType.ADMIN],
        )
        .pagingParams(defaultSort="igsn", defaultSortDir=SortDir.ASCENDING)
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def list_deposition(self, igsnPrefix, sampleId, q, level, limit, offset, sort):
        user = self.getCurrentUser()
        if sampleId is not None:
            try:
                sample = Sample().load(
                    sampleId,
                    user=user,
                    level=AccessType.READ,
                    exc=True,
                )
            except Exception:
                return []
            return DepositionModel().findWithPermissions(
                query={"sampleId": sample["_id"]},
                offset=offset,
                limit=limit,
                sort=sort,
                user=user,
                fields={
                    "metadata.relatedIdentifiers": 0,
                },  # Exclude ACLed fields
                level=level,
            )

        query = {}
        if igsnPrefix is not None:
            query["igsn"] = re.compile(f"^{igsnPrefix}.*$")
        elif q is not None:
            query["$or"] = [
                {"metadata.titles.title": {"$regex": q, "$options": "i"}},
                {"igsn": {"$regex": q, "$options": "i"}},
                {
                    "metadata.alternateIdentifiers.alternateIdentifier": {
                        "$regex": q,
                        "$options": "i",
                    }
                },
            ]

        return DepositionModel().findWithPermissions(
            query=query,
            offset=offset,
            limit=limit,
            sort=sort,
            user=self.getCurrentUser(),
            fields={
                "metadata.relatedIdentifiers": 0,
                "sampleId": 0,
            },  # Exclude ACLed fields
            level=level,
        )

    @access.public
    @autoDescribeRoute(Description("Get the settings for the depositions"))
    def get_settings(self):
        return {
            "igsn_institutions": Setting().get(PluginSettings.IGSN_INSTITUTIONS),
            "igsn_materials": Setting().get(PluginSettings.IGSN_MATERIALS),
        }

    @access.public
    @autoDescribeRoute(
        Description("Get a single deposition").modelParam(
            "id",
            model=DepositionModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.READ,
        )
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def get_deposition(self, deposition):
        return deposition

    @access.user
    @autoDescribeRoute(
        Description("Create a new deposition")
        .param("prefix", "The prefix for IGSN", required=True, dataType="string")
        .param(
            "track",
            "Create a sample tracker for IGSN",
            required=False,
            dataType="boolean",
            default=False,
        )
        .jsonParam(
            "metadata",
            "JSON object with Datacite fields",
            requireObject=True,
            required=True,
        )
        .modelParam(
            "parentId",
            "The parent deposition ID.",
            model=DepositionModel,
            destName="parent",
            required=False,
            paramType="query",
            level=AccessType.WRITE,
        )
        .param(
            "batch",
            "The number of subsamples to create in the deposition",
            required=False,
            dataType="integer",
            default=0,
        )
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def create_deposition(self, prefix, track, metadata, parent, batch):
        # Logic to create a new deposition
        return DepositionModel().create_deposition(
            metadata,
            self.getCurrentUser(),
            prefix=prefix,
            track=track,
            parent=parent,
            batch=batch,
        )

    @access.user
    @autoDescribeRoute(
        Description("Create a child deposition from an existing one")
        .modelParam(
            "id",
            model=DepositionModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.WRITE,
        )
        .param("suffix", "The suffix for IGSN", required=True, dataType="string")
        .param(
            "track",
            "Create a sample tracker for IGSN",
            required=False,
            dataType="boolean",
            default=False,
        )
        .jsonParam(
            "metadata",
            "JSON object with Datacite fields for the child deposition",
            requireObject=True,
            required=False,
        )
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def create_child_deposition(self, deposition, suffix, track, metadata):
        # check if suffix is valid (non empty and alphanumeric)
        if not suffix or not re.match(r"^[a-zA-Z0-9]+$", suffix):
            raise RestException("Suffix must be a non-empty alphanumeric string.")

        new_igsn = f"{deposition['igsn']}-{suffix}"
        if DepositionModel().findOne({"igsn": new_igsn}):
            raise RestException(f"Deposition with IGSN {new_igsn} already exists.")

        local_identifier = DepositionModel().local_identifier(deposition["metadata"])
        if local_identifier:
            local_identifier = f"{local_identifier}-{suffix}"
        indices = [(suffix, local_identifier)]
        # Is not saved, but that's what's checked
        deposition.update(
            {
                "created:": datetime.datetime.now(datetime.UTC),
                "creatorId": self.getCurrentUser()["_id"],
                "updated": datetime.datetime.now(datetime.UTC),
                "track": track,
            }
        )
        result = DepositionModel().create_batch(deposition, indices)
        return DepositionModel().load(
            result.inserted_ids[0], user=self.getCurrentUser()
        )

    @access.public
    @autoDescribeRoute(
        Description("Update an existing deposition")
        .modelParam(
            "id",
            model=DepositionModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.WRITE,
        )
        .param("sampleId", "The sample tracker to associate with IGSN", required=False)
        .jsonParam(
            "metadata",
            "JSON object with Datacite fields",
            requireObject=True,
            required=True,
        )
    )
    def update_deposition(self, deposition, sampleId, metadata):
        # Logic to update an existing deposition
        return DepositionModel().update_deposition(
            deposition, metadata, sampleId, user=self.getCurrentUser()
        )

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description("Get the access control list for a deposition").modelParam(
            "id",
            "The ID of the deposition",
            model=DepositionModel,
            level=AccessType.ADMIN,
        )
    )
    def get_deposition_access(self, deposition):
        return DepositionModel().getFullAccessList(deposition)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description("Update the access control list for a deposition")
        .modelParam(
            "id", "The ID of the form", model=DepositionModel, level=AccessType.ADMIN
        )
        .jsonParam(
            "access", "The JSON-encoded access control list.", requireObject=True
        )
        .jsonParam(
            "publicFlags",
            "JSON list of public access flags.",
            requireArray=True,
            required=False,
        )
        .param(
            "public",
            "Whether the form should be publicly visible.",
            dataType="boolean",
            required=False,
        )
        .errorResponse("ID was invalid.")
        .errorResponse("Admin access was denied for the form.", 403)
    )
    def update_deposition_access(self, deposition, access, publicFlags, public):
        user = self.getCurrentUser()
        DepositionModel().setAccessList(
            deposition,
            access,
            save=True,
            recurse=True,
            user=user,
            progress=noProgress,
            setPublic=public,
            publicFlags=publicFlags,
        )

    @access.public
    @autoDescribeRoute(
        Description("Autocomplete ORCID")
        .param("query", "The query to search for", required=True, dataType="string")
        .param(
            "limit",
            "The maximum number of results to return",
            required=False,
            dataType="integer",
            default=10,
        )
    )
    def autocomplete(self, query, limit):
        url = (
            "https://pub.orcid.org/v3.0/expanded-search/?q="
            + urllib.parse.quote(query)
            + f"&start=0&rows={limit}"
        )
        response = requests.get(
            url,
            headers=get_orcid_headers(),
        )
        if (
            response.status_code != 200
            or "expanded-result" not in response.json()
            or not response.json()["expanded-result"]
        ):
            return []

        def get_last_inst(institutions):
            if institutions:
                return institutions[-1]
            else:
                return ""

        return [
            {
                "value": i + 1,
                "text": (
                    f"{_['family-names']}, {_['given-names']} "
                    f"({_['orcid-id']}) - {get_last_inst(_['institution-name'])}"
                ),
            }
            for i, _ in enumerate(response.json()["expanded-result"])
        ]

    @access.admin
    @autoDescribeRoute(
        Description("Delete a deposition").modelParam(
            "id",
            model=DepositionModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.ADMIN,
        )
    )
    def delete_deposition(self, deposition):
        # Logic to delete a deposition
        DepositionModel().remove(deposition)
