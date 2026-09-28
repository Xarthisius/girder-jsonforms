import pytest

from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.setting import Setting
from pytest_girder.assertions import assertStatusOk

from ..settings import PluginSettings
from ..worker_plugin import folder_ops


@pytest.fixture
def ebsd_tree(db, admin):
    """A small folder tree exercising both classification paths: an item
    classified by its own extension, and a nested one classified by the name of
    the folder holding it."""
    root = Folder().createFolder(admin, "Root", parentType="user", creator=admin)
    nested = Folder().createFolder(root, "raw data", creator=admin)

    root_item = Item().setMetadata(
        Item().createItem("scan.ctf", admin, root), {"existing": True}
    )
    nested_item = Item().createItem("unknown.dat", admin, nested)
    unclassifiable = Item().createItem("notes.txt", admin, root)
    # Would classify as EBSD_Derived, but already belongs to another AIMD
    # partition and must be left alone.
    foreign_item = Item().setMetadata(
        Item().createItem("plot.png", admin, root), {"data_type": "xrd_raw"}
    )

    yield {
        "root": root,
        "root_item": root_item,
        "nested_item": nested_item,
        "unclassifiable": unclassifiable,
        "foreign_item": foreign_item,
    }

    Folder().remove(root)


@pytest.mark.plugin("jsonforms")
class TestEbsdFolderOperations:
    @pytest.mark.parametrize(
        "file_name,folder_name,expected",
        [
            ("scan.ctf", "", "EBSD_Raw"),
            ("scan.ang", "", "EBSD_Raw"),
            ("scan.ebsd", "", "EBSD_Raw"),
            ("process.py", "", "EBSD_Scripts"),
            ("process.m", "", "EBSD_Scripts"),
            ("process.js", "", "EBSD_Scripts"),
            ("process.ipynb", "", "EBSD_Scripts"),
            ("process.mat", "", "EBSD_Scripts"),
            ("map.png", "", "EBSD_Derived"),
            ("map.xlsx", "", "EBSD_Derived"),
            ("map.pdf", "", "EBSD_Derived"),
            ("map.pptx", "", "EBSD_Derived"),
            ("sample.dat", "raw scans", "EBSD_Raw"),
            ("sample.dat", "analysis scripts", "EBSD_Scripts"),
            ("sample.dat", "derived maps", "EBSD_Derived"),
            ("sample.dat", "other", "unknown"),
            ("sample.dat", "EBSD Stats", "EBSD_Derived"),
            # Whole-word matching: these folder names merely contain the keywords.
            ("notes.txt", "Drawings", "unknown"),
            ("notes.txt", "Sitemap", "unknown"),
            ("notes.txt", "Manuscripts", "unknown"),
        ],
    )
    def test_classify_ebsd(self, file_name, folder_name, expected):
        assert folder_ops.classify_ebsd(file_name, folder_name) == expected

    def test_recursive_classify_ebsd_updates_nested_items(self, admin, ebsd_tree):
        folder_ops.recursive_classify_ebsd(ebsd_tree["root"], admin)

        def reload(item):
            return Item().load(item["_id"], force=True)

        assert reload(ebsd_tree["root_item"])["meta"] == {
            "existing": True,
            "data_type": "EBSD_Raw",
        }
        assert reload(ebsd_tree["nested_item"])["meta"] == {"data_type": "EBSD_Raw"}
        assert reload(ebsd_tree["unclassifiable"])["meta"] == {}
        assert reload(ebsd_tree["foreign_item"])["meta"] == {"data_type": "xrd_raw"}

    def test_recursive_classify_ebsd_reclassifies_own_data_types(
        self, admin, ebsd_tree
    ):
        """A stale EBSD_* value is ours to correct, unlike a foreign one."""
        stale = Item().setMetadata(
            Item().createItem("scan.ang", admin, ebsd_tree["root"]),
            {"data_type": "EBSD_Derived"},
        )

        folder_ops.recursive_classify_ebsd(ebsd_tree["root"], admin)

        assert Item().load(stale["_id"], force=True)["meta"] == {
            "data_type": "EBSD_Raw"
        }

    def test_classify_ebsd_folder_endpoint_classifies_subtree(
        self, server, admin, ebsd_tree, eagerWorkerTasks
    ):
        response = server.request(
            path=f"/folder/{ebsd_tree['root']['_id']}/classify_ebsd",
            method="PUT",
            user=admin,
            params={"progress": True},
        )

        assertStatusOk(response)
        assert "Classifying EBSD files" in response.json["message"]
        # The nested item is only reachable if the task recursed from the root.
        assert Item().load(ebsd_tree["nested_item"]["_id"], force=True)["meta"] == {
            "data_type": "EBSD_Raw"
        }

    def test_classify_ebsd_folder_task_returns_error_without_write_access(
        self, user, ebsd_tree
    ):
        assert folder_ops.classify_ebsd_folder_task.run(
            str(ebsd_tree["root"]["_id"]), str(user["_id"])
        ) == {
            "status": "error",
            "message": "write access denied",
        }
        assert Item().load(ebsd_tree["root_item"]["_id"], force=True)["meta"] == {
            "existing": True
        }

    def test_classify_ebsd_folder_task_returns_error_for_missing_folder(
        self, db, admin
    ):
        assert folder_ops.classify_ebsd_folder_task.run(
            "000000000000000000000000", str(admin["_id"])
        ) == {
            "status": "error",
            "message": "folder not found",
        }


@pytest.mark.plugin("jsonforms")
class TestMainProjectPublicSetting:
    """The web client only shows the Classify EBSD folder action for IMQCAM,
    so it needs to know which project this instance is flavored as."""

    @pytest.mark.parametrize("main_project", ["imqcam", "aimdl"])
    def test_main_project_is_published(self, server, admin, main_project):
        Setting().set(PluginSettings.MAIN_PROJECT, main_project)
        response = server.request(path="/system/public_settings", method="GET")
        assertStatusOk(response)
        assert response.json[PluginSettings.MAIN_PROJECT] == main_project
