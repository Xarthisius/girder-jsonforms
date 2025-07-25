from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.folder import Folder

from ..lib.project_tasks import trigger_post_entry_task
from ..models.entry import FormEntry as FormEntryModel
from ..models.form import Form as FormModel
from ..worker_plugin.pull_related_ids import run as pullRelatedIds


class FormEntry(Resource):
    def __init__(self):
        super(FormEntry, self).__init__()
        self.resourceName = "entry"
        self.route("GET", (), self.listFormEntry)
        self.route("GET", ("search",), self.searchFormEntry)
        self.route("GET", (":id",), self.getFormEntry)
        self.route("PUT", (":id",), self.updateFormEntry)
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
        Description("Update an entry")
        .modelParam(
            "id", "The ID of the entry", model=FormEntryModel, level=AccessType.WRITE
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
    def updateFormEntry(self, entry, data, source, destination):
        form = FormModel().load(
            entry["formId"], user=self.getCurrentUser(), level=AccessType.WRITE
        )
        if not form:
            raise RestException("Form not found or insufficient permissions")
        if entry["data"].get(form["uniqueField"]) != data.get(form["uniqueField"]):
            raise RestException(
                f"Update cannot change entry's unique id {entry['data'][form['uniqueField']]}"
                f" to {data[form['uniqueField']]}. Create a new entry instead."
            )
        assigned_igsn = entry["data"].get("assignedIGSN")
        if assigned_igsn and assigned_igsn != data.get("assignedIGSN"):
            raise RestException(
                "Update cannot change entry's assigned IGSN. Create a new entry instead."
            )

        entry = FormEntryModel().update_entry(
            form, entry, data, source, destination, self.getCurrentUser()
        )

        if task := form.get("postEntryTask"):
            trigger_post_entry_task(task, entry, self.getCurrentUser())
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
        if FormEntryModel().findOne(
            {
                "formId": form["_id"],
                f"data.{form['uniqueField']}": data.get(form["uniqueField"]),
            }
        ):
            raise RestException(
                f"An entry with sampleId {data.get('sampleId')} already exists in form {form['name']}"
            )
        entry = FormEntryModel().create_entry(
            form,
            data,
            source,
            destination,
            self.getCurrentUser(),
        )
        if task := form.get("postEntryTask"):
            trigger_post_entry_task(task, entry, self.getCurrentUser())
        return entry

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Delete an entry").modelParam(
            "id", "The ID of the entry", model=FormEntryModel, level=AccessType.WRITE
        )
    )
    def deleteFormEntry(self, entry):
        pullRelatedIds.delay(
            entry,
            user=self.getCurrentUser(),
            girder_job_title="Updating relatedIdentifiers in Depositions",
        )
        FormEntryModel().remove(entry)
