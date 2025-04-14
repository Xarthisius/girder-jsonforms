from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel
from girder.constants import AccessType, TokenScope
from girder.models.folder import Folder

from ..models.form import Form as FormModel
from ..models.entry import FormEntry as FormEntryModel


class FormEntry(Resource):
    def __init__(self):
        super(FormEntry, self).__init__()
        self.resourceName = "entry"
        self.route("GET", (), self.listFormEntry)
        self.route("GET", ("search",), self.searchFormEntry)
        self.route("GET", (":id",), self.getFormEntry)
        self.route("POST", (), self.createFormEntry)
        self.route("DELETE", (":id",), self.deleteFormEntry)

    @access.public
    @autoDescribeRoute(
        Description("List all entries")
        .param("query", "Regex for Sample Id", dataType="string", required=False)
        .param(
            "field",
            "Field to search",
            dataType="string",
            required=False,
            default="sampleId",
        )
        .modelParam(
            "formId",
            "The ID of the form",
            model=FormModel,
            level=AccessType.READ,
            paramType="query",
            required=False,
        )
        .pagingParams(defaultSort="created")
    )
    def listFormEntry(self, query, field, form, limit, offset, sort):
        q = {}
        if form:
            q = {"formId": form["_id"]}
        if query:
            q[f"data.{field}"] = {"$regex": query}

        cursor = FormEntryModel().findWithPermissions(
            q,
            sort=sort,
            user=self.getCurrentUser(),
            level=AccessType.READ,
            limit=limit,
            offset=offset,
        )
        return list(cursor)

    @access.public
    @autoDescribeRoute(
        Description("Search entries")
        .param("query", "Regex for Sample Id", dataType="string", required=True)
        .param(
            "field",
            "Field to search",
            dataType="string",
            required=False,
            default="sampleId",
        )
        .modelParam(
            "formId",
            "The ID of the form",
            destName="form",
            model=FormModel,
            level=AccessType.READ,
            paramType="query",
            required=False,
        )
        .pagingParams(defaultSort="data.sampleId")
    )
    def searchFormEntry(self, query, field, form, limit, offset, sort):
        q = {f"data.{field}": {"$regex": query}}
        if form:
            q["formId"] = form["_id"]
        cursor = FormEntryModel().findWithPermissions(
            q,
            user=self.getCurrentUser(),
            level=AccessType.READ,
            limit=limit,
            offset=offset,
            sort=sort,
        )
        return [f"{_['_id']};{_['data'][field]}" for _ in cursor]

    @access.public
    @autoDescribeRoute(
        Description("Get an entry by ID").modelParam(
            "id", "The ID of the form", model=FormEntryModel, level=AccessType.READ
        )
    )
    @filtermodel(model=FormEntryModel, plugin="jsonforms")
    def getFormEntry(self, entry):
        return entry

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Create a new entry")
        .modelParam(
            "formId",
            "The ID of the form",
            model=FormModel,
            level=AccessType.READ,
            destName="form",
            paramType="query",
            required=True,
        )
        .jsonParam("data", "The data of the entry", required=True)
        .modelParam(
            "sourceId",
            "The folder ID of uploaded data",
            required=False,
            model=Folder,
            paramType="query",
            destName="source",
            level=AccessType.WRITE,
        )
        .modelParam(
            "destinationId",
            "The folder ID of destination",
            required=False,
            model=Folder,
            paramType="query",
            destName="destination",
            level=AccessType.WRITE,
        )
    )
    @filtermodel(model=FormEntryModel, plugin="jsonforms")
    def createFormEntry(self, form, data, source, destination):
        return FormEntryModel().create_entry(
            form,
            data,
            source,
            destination,
            self.getCurrentUser(),
        )

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Delete an entry").modelParam(
            "id", "The ID of the entry", model=FormEntryModel, level=AccessType.WRITE
        )
    )
    def deleteFormEntry(self, entry):
        FormEntryModel().remove(entry)
