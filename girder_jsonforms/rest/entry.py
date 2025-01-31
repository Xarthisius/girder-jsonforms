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
        .modelParam(
            "formId",
            "The ID of the form",
            model=FormModel,
            level=AccessType.READ,
            required=False,
        )
        .pagingParams(defaultSort="created")
    )
    def listFormEntry(self, form, limit, offset, sort):
        q = {}
        if form:
            q = {"formId": form["_id"]}

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
        .pagingParams(defaultSort="data.sampleId")
    )
    def searchFormEntry(self, query, limit, offset, sort):
        print(query)
        q = {"data.sampleId": {"$regex": query}}
        cursor = FormEntryModel().findWithPermissions(
            q,
            user=self.getCurrentUser(),
            level=AccessType.READ,
            limit=limit,
            offset=offset,
            sort=sort,
        )
        return list(cursor)

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
            required=True,
            model=Folder,
            paramType="query",
            destName="destination",
            level=AccessType.WRITE,
        )
    )
    @filtermodel(model=FormEntryModel, plugin="jsonforms")
    def createFormEntry(self, form, data, source, destination):
        return FormEntryModel().create(
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
