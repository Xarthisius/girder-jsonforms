import re
import urllib.parse
import requests

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import (
    Resource,
    filtermodel,
)
from girder.constants import AccessType, SortDir
from girder.models.setting import Setting
from ..models.deposition import Deposition as DepositionModel


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
        self.route("GET", (":id",), self.get_deposition)
        self.route("POST", (), self.create_deposition)
        self.route("PUT", (":id",), self.update_deposition)
        self.route("GET", (":id", "access"), self.get_access)
        self.route("PUT", (":id", "access"), self.update_access)
        self.route("GET", ("autocomplete",), self.autocomplete)

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
    def list_deposition(self, igsnPrefix, q, level, limit, offset, sort):
        query = {}
        if igsnPrefix is not None:
            query["igsn"] = re.compile(f"^{igsnPrefix}.*$")
        elif q is not None:
            query["$or"] = [
                {"metadata.title": {"$regex": q, "$options": "i"}},
                {"igsn": {"$regex": q, "$options": "i"}},
                {
                    "metadata.attributes.alternateIdentifiers.alternateIdentifier": {
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
            level=level,
        )

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
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def create_deposition(self, prefix, metadata, parent):
        # Logic to create a new deposition
        return DepositionModel().create(
            metadata, self.getCurrentUser(), prefix, parent=parent
        )

    @access.public
    def update_deposition(self, id, params):
        # Logic to update an existing deposition
        pass

    @access.public
    def get_access(self, id):
        # Logic to get access information for a deposition
        pass

    @access.public
    def update_access(self, id, params):
        # Logic to update access information for a deposition
        pass

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
