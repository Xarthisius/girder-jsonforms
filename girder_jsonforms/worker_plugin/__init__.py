from girder_worker import GirderWorkerPluginABC


class JSONFormsWorkerPlugin(GirderWorkerPluginABC):
    def __init__(self, app, *args, **kwargs):
        self.app = app

    def task_imports(self):
        return [
            "girder_jsonforms.worker_plugin.pull_related_ids",
        ]

