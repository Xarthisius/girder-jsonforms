from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel
from girder.constants import AccessType, TokenScope
from girder.models.folder import Folder

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

    @access.public
    @autoDescribeRoute(Description("List all forms"))
    @filtermodel(model="form", plugin="jsonforms")
    def listForm(self, params):
        return FormModel().find()

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
            "pathTransform",
            "Python template string to transform destination path based on form entry",
            required=False,
            dataType="string",
        )
    )
    @filtermodel(model="form", plugin="jsonforms")
    def createForm(self, name, description, schema, folder, pathTransform):
        return FormModel().create(
            name,
            description,
            schema,
            self.getCurrentUser(),
            folder=folder,
            pathTransform=pathTransform,
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
            "pathTransform",
            "Python template string to transform destination path based on form entry",
            required=False,
            dataType="string",
        )
        .responseClass('Form')
        .errorResponse("ID was invalid.")
        .errorResponse("Write access was denied on the form.", 403)
    )
    def updateForm(self, form, name, description, schema, folder, pathTransform):
        if name is not None:
            form["name"] = name
        if description is not None:
            form["description"] = description
        if schema is not None:
            form["schema"] = schema
        print(":!!!!")
        print(folder)
        print(":!!!!")
        if folder:
            form["folderId"] = folder["_id"]
        if pathTransform is not None:
            if not pathTransform:
                form["pathTransform"] = None
            else:
                form["pathTransform"] = pathTransform
        print(form)
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
