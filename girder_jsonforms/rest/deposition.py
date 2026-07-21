import datetime
import re
import urllib.parse

import pymongo
import requests
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import (
    Resource,
    filtermodel,
    getApiUrl,
)
from girder.constants import AccessType, SortDir, TokenScope
from girder.exceptions import GirderException, RestException
from girder.models.item import Item
from girder.models.setting import Setting
from girder.utility.progress import noProgress
from girder_oauth import providers
from girder_sample_tracker.models.sample import Sample

from ..models.deposition import Deposition as DepositionModel
from ..models.entry import FormEntry as EntryModel
from ..settings import PluginSettings
from ..worker_plugin.amdee import register_deposition_with_aimd

orcid_headers = None


def get_orcid_headers():
    global orcid_headers
    if orcid_headers is None:
        provider = providers.idMap.get("orcid")
        # ORCID API endpoint
        url = provider._TOKEN_URL

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

    print("Using ORCID headers:", orcid_headers)
    return orcid_headers


class Deposition(Resource):
    def __init__(self):
        super(Deposition, self).__init__()
        self.resourceName = "deposition"
        self.route("GET", (), self.list_deposition)
        self.route("POST", (), self.create_deposition)
        self.route("GET", ("autocomplete",), self.autocomplete)
        self.route("GET", ("settings",), self.get_settings)
        self.route("POST", ("relation",), self.update_deposition_relations)
        self.route("DELETE", (":id",), self.delete_deposition)
        self.route("GET", (":id",), self.get_deposition)
        self.route("PUT", (":id",), self.update_deposition)
        self.route("GET", (":id", "access"), self.get_deposition_access)
        self.route("GET", (":id", "assets"), self.get_deposition_assets)
        self.route("PUT", (":id", "access"), self.update_deposition_access)
        self.route("PUT", (":id", "task"), self.submit_deposition_task)
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
        assets_folder = DepositionModel()._get_assets_folder(deposition)
        image = Item().findOne(
            {"folderId": assets_folder["_id"], "meta.type": "deposition_image"},
            sort=[("created", SortDir.DESCENDING)],
        )
        if image:
            deposition["imageId"] = image["_id"]
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
        .param("suffix", "The suffix for IGSN", required=False, dataType="string")
        .param(
            "track",
            "Create a sample tracker for IGSN",
            required=False,
            dataType="boolean",
            default=False,
        )
        .param(
            "batch",
            "The number of subsamples to create in the deposition",
            required=False,
            dataType="integer",
            default=0,
        )
        .jsonParam(
            "metadata",
            "JSON object with Datacite fields for the child deposition",
            requireObject=True,
            required=False,
        )
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def create_child_deposition(self, deposition, suffix, track, batch, metadata):
        if suffix and batch > 0:
            raise RestException("Cannot specify both suffix and batch parameters.")
        if not (suffix or batch > 0):
            raise RestException("Must specify either suffix or batch parameter.")
        # check if suffix is valid (non empty and alphanumeric)
        if suffix:
            if not re.match(r"^[a-zA-Z0-9]+$", suffix):
                raise RestException("Suffix must be a non-empty alphanumeric string.")
            new_igsn = f"{deposition['igsn']}-{suffix}"
            if DepositionModel().findOne({"igsn": new_igsn}):
                raise RestException(f"Deposition with IGSN {new_igsn} already exists.")

        local_identifier = DepositionModel().local_identifier(deposition["metadata"])
        if batch > 0:
            # find the highest existing batch number for this deposition
            existing_batches = DepositionModel().find(
                {"igsn": {"$regex": f"^{deposition['igsn']}-(\\d+)$"}}
            )
            max_batch = 0
            for batch_deposition in existing_batches:
                batch_num = int(batch_deposition["igsn"].split("-")[-1])
                max_batch = max(max_batch, batch_num)

            suffix = f"batch{max_batch + 1}"
            indices = []
            for i in range(batch):
                batch_suffix = f"{max_batch + 1 + i:03d}"
                indices.append(
                    (
                        batch_suffix,
                        f"{local_identifier}-{batch_suffix}"
                        if local_identifier
                        else None,
                    )
                )
        else:
            indices = [
                (suffix, f"{local_identifier}-{suffix}" if local_identifier else None)
            ]
        # Is not saved, but that's what's checked
        deposition.update(
            {
                "created:": datetime.datetime.now(datetime.UTC),
                "creatorId": self.getCurrentUser()["_id"],
                "updated": datetime.datetime.now(datetime.UTC),
                "track": track,
            }
        )
        try:
            result = DepositionModel().create_batch(deposition, indices)
        except pymongo.errors.BulkWriteError as e:
            raise RestException(f"Error creating child depositions: {e.details}")
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
        if sampleId is None:
            sampleId = deposition["sampleId"]

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

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Update the relations of depositions")
        .jsonParam(
            "depositionIds",
            "List of deposition IDs to update.",
            requireArray=True,
            paramType="body",
            required=True,
        )
        .modelParam(
            "entryId",
            "The form entry being (un)linked to.",
            model=EntryModel,
            destName="entry",
            required=True,
            paramType="query",
            level=AccessType.READ,
        )
        .param(
            "action",
            "The action to perform: add (1) or remove (-1).",
            required=False,
            enum=[-1, 1],
            dataType="integer",
            default=1,
        )
    )
    def update_deposition_relations(self, depositionIds, entry, action):
        print(depositionIds, entry, action)
        user = self.getCurrentUser()
        try:
            api_url = getApiUrl()
        except GirderException:
            api_url = "/api/v1"
        relatedIdentifier = {
            "relationType": "HasMetadata",
            "relatedIdentifier": "/".join((api_url, "entry", str(entry["_id"]))),
            "relatedIdentifierType": "URL",
            "relatedMetadataScheme": "/".join(
                (api_url, "form", str(entry["formId"]), "schema")
            ),
        }

        # Validate all deposition IDs first
        ids = [
            DepositionModel().load(
                depositionId, user=user, level=AccessType.WRITE, exc=True
            )["_id"]
            for depositionId in depositionIds
        ]

        op = "$pull" if action == -1 else "$addToSet"
        DepositionModel().collection.update_many(
            {"_id": {"$in": ids}},
            {op: {"metadata.relatedIdentifiers": relatedIdentifier}},
        )

        return True

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
        provider = providers.idMap.get("orcid")
        if provider is None:
            raise RestException("ORCID not set up")

        path = (
            "expanded-search/?q="
            + urllib.parse.quote(query)
            + f"&start=0&rows={limit}"
        )
        url = provider._API_USER_URL.format(orcid="", path=path)
        print(f"Making ORCID API request to {url} with headers {get_orcid_headers()}")
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

    @access.user(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description("Submit a deposition task")
        .modelParam(
            "id",
            model=DepositionModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.READ,
        )
        .param(
            "action",
            "The action to perform: register_aimd or tba.",
            required=True,
            enum=["register_aimd"],
            dataType="string",
        )
    )
    @filtermodel(model="job", plugin="jobs")
    def submit_deposition_task(self, deposition, action):
        if action == "register_aimd":
            task = register_deposition_with_aimd.delay(
                [{"_id": str(deposition["_id"]), "igsn": deposition["igsn"]}],
                girder_job_title=f"Registering {deposition['igsn']} with AIMD portal",
            )
        else:
            raise RestException(f"Unknown action: {action}")
        return task.job

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
        if deposition["state"] != "draft":
            raise RestException("Only draft depositions can be deleted.")
        DepositionModel().remove(deposition)

    @access.public
    @autoDescribeRoute(
        Description("Get the assets folder associated with a deposition").modelParam(
            "id",
            model=DepositionModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.READ,
        )
    )
    @filtermodel(model="folder")
    def get_deposition_assets(self, deposition):
        return DepositionModel()._get_assets_folder(deposition)
