from girder.utility.model_importer import ModelImporter
from girder_worker import GirderWorkerPluginABC

from ..models.deposition import Deposition
from ..models.form import Form


class JSONFormsWorkerPlugin(GirderWorkerPluginABC):
    def __init__(self, app, *args, **kwargs):
        self.app = app
        ModelImporter.registerModel("form", Form, plugin="jsonforms")
        ModelImporter.registerModel("deposition", Deposition, plugin="jsonforms")
        Deposition()  # bind events

    def task_imports(self):
        return [
            "girder_jsonforms.worker_plugin.pull_related_ids",
            "girder_jsonforms.worker_plugin.amdee",
        ]
