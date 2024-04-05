from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel
from girder.constants import AccessType, TokenScope, SortDir
from girder.models.folder import Folder
from girder.utility.progress import noProgress

from ..models.form import Form as FormModel


class Form(Resource):
    def __init__(self):
        super(Form, self).__init__()
        self.resourceName = "form"
        self.route("GET", (), self.listForm)
        self.route("GET", (":id",), self.getForm)
        self.route("POST", (), self.createForm)
        self.route("PUT", (":id",), self.updateForm)
        self.route("DELETE", (":id",), self.deleteForm)
        self.route("GET", (":id", "access"), self.getFromAccess)
        self.route("PUT", (":id", "access"), self.updateFromAccess)

    @access.public
    @autoDescribeRoute(
        Description("List all forms")
        .param(
            "level", "The minimum access level to filter the forms by",
            dataType="integer",
            required=False,
            default=AccessType.READ,
            enum=[AccessType.NONE, AccessType.READ, AccessType.WRITE, AccessType.ADMIN],
        )
        .pagingParams(defaultSort="name", defaultSortDir=SortDir.ASCENDING)
    )
    @filtermodel(model="form", plugin="jsonforms")
    def listForm(self, level, limit, offset, sort):
        return FormModel().findWithPermissions(
            query={},
            offset=offset,
            limit=limit,
            sort=sort,
            user=self.getCurrentUser(),
            level=level,
        )

    @access.public
    @autoDescribeRoute(
        Description("Get a form by ID").modelParam(
            "id", "The ID of the form", model=FormModel, level=AccessType.READ
        )
    )
    @filtermodel(model="form", plugin="jsonforms")
    def getForm(self, form):
        return form

    @access.user
    @autoDescribeRoute(
        Description("Create a new form")
        .param("name", "The name of the form", required=True, dataType="string")
        .param(
            "description",
            "The description of the form",
            required=True,
            dataType="string",
        )
        .param("schema", "The schema of the form", required=True, dataType="string")
        .modelParam(
            "folderId",
            "The folder ID to save the form",
            required=False,
            model=Folder,
            paramType="query",
            level=AccessType.WRITE,
        )
        .param(
            "pathTemplate",
            "Python template string to transform destination path based on form entry",
            required=False,
            dataType="string",
        )
        .param(
            "entryFileName",
            "The name of the file to save the form entry in the destination folder",
            required=False,
            dataType="string",
        )
    )
    @filtermodel(model="form", plugin="jsonforms")
    def createForm(
        self, name, description, schema, folder, pathTemplate, entryFileName
    ):
        return FormModel().create(
            name,
            description,
            schema,
            self.getCurrentUser(),
            folder=folder,
            pathTemplate=pathTemplate,
            entryFileName=entryFileName,
        )

    @access.user(scope=TokenScope.DATA_WRITE)
    @filtermodel(model="form", plugin="jsonforms")
    @autoDescribeRoute(
        Description("Update a form")
        .modelParam("id", "The ID of the form", model=FormModel, level=AccessType.WRITE)
        .param("name", "The name of the form", required=False, dataType="string")
        .param(
            "description",
            "The description of the form",
            required=False,
            dataType="string",
        )
        .param("schema", "The schema of the form", required=False, dataType="string")
        .modelParam(
            "folderId",
            "The folder ID to save the form",
            model=Folder,
            required=False,
            paramType="query",
            level=AccessType.WRITE,
        )
        .param(
            "pathTemplate",
            "Python template string to transform destination path based on form entry",
            required=False,
            dataType="string",
        )
        .param(
            "entryFileName",
            "The name of the file to save the form entry in the destination folder",
            required=False,
            dataType="string",
        )
        .responseClass("Form")
        .errorResponse("ID was invalid.")
        .errorResponse("Write access was denied on the form.", 403)
    )
    def updateForm(
        self, form, name, description, schema, folder, pathTemplate, entryFileName
    ):
        if name is not None:
            form["name"] = name
        if description is not None:
            form["description"] = description
        if schema is not None:
            form["schema"] = schema
        if entryFileName is not None:
            form["entryFileName"] = entryFileName
        if folder:
            form["folderId"] = folder["_id"]
        if pathTemplate is not None:
            if not pathTemplate:
                form["pathTemplate"] = None
            else:
                form["pathTemplate"] = pathTemplate
        return FormModel().save(form)

    @access.user
    @autoDescribeRoute(
        Description("Delete a form").modelParam(
            "id", "The ID of the form", model=FormModel, level=AccessType.WRITE
        )
    )
    @filtermodel(model="form", plugin="jsonforms")
    def deleteForm(self, form):
        FormModel().remove(form)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description("Get the access control list for a form").modelParam(
            "id", "The ID of the form", model=FormModel, level=AccessType.ADMIN
        )
    )
    def getFromAccess(self, form):
        return FormModel().getFullAccessList(form)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description("Update the access control list for a form")
        .modelParam("id", "The ID of the form", model=FormModel, level=AccessType.ADMIN)
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
    def updateFromAccess(self, form, access, publicFlags, public):
        user = self.getCurrentUser()
        if form["folderId"]:
            folder = Folder().load(form["folderId"], force=True)
            Folder().setAccessList(
                folder,
                access,
                save=True,
                recurse=True,
                user=user,
                progress=noProgress,
                setPublic=public,
                publicFlags=publicFlags,
            )

        return FormModel().setAccessList(form, access, save=True, user=user)
