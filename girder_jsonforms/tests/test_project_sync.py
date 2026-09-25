import datetime
import io

import pytest

import girder_jsonforms.rest.aimdl as aimdl_mod
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.upload import Upload
from girder.utility import RequestBodyStream

from ..models.project import Project as ProjectModel


def _upload_file(item, admin, name, content):
    return Upload().uploadFromFile(
        io.BytesIO(content), len(content), name, "item", item, admin
    )


def _read_file(file_doc):
    from girder.models.file import File

    with File().open(file_doc) as fh:
        return fh.read()


@pytest.fixture
def aimdl_collection(admin, monkeypatch):
    """A fresh Collection standing in for the blessed AIMDL collection.

    ``_AIMDL_COLLECTION_ID`` is read from the environment once at import
    time, so a real test database can't be pointed at via the env var after
    the fact. Patching the module attribute achieves the same thing.
    """
    collection = Collection().createCollection("AIMDL", admin, public=True)
    monkeypatch.setattr(aimdl_mod, "_AIMDL_COLLECTION_ID", str(collection["_id"]))
    return collection


@pytest.fixture
def aimdl_folder(aimdl_collection, admin):
    return Folder().createFolder(
        aimdl_collection, "raw", parentType="collection", creator=admin
    )


@pytest.fixture
def accepted_project(server, user, admin, eagerWorkerTasks):
    """A project that has transitioned to 'accepted', so its own collection
    (named after its projectId) exists, matching production's flow."""
    project = ProjectModel().create_project(
        {
            "name": "Test Project",
            "description": "A project for testing sync",
            "creatorId": user["_id"],
        },
        user,
    )
    return ProjectModel().update_project(project, {"status": "accepted"}, admin)


def _project_collection(project):
    return Collection().findOne({"name": project["projectId"]})


def _copies_for(project):
    project_collection = _project_collection(project)
    return list(
        Item().find(
            {
                "baseParentId": project_collection["_id"],
                "baseParentType": "collection",
            }
        )
    )


@pytest.mark.plugin("jsonforms")
def test_use_sample_matches_igsn_prefix(db):
    """Project.use_sample should match both the exact IGSN and any IGSN it
    is a prefix of (e.g. a top-level sample IGSN matching a sub-sample)."""
    assert list(ProjectModel().use_sample("JHAMAA00001")) == []

    project = ProjectModel().save(
        {
            "name": "Prefix project",
            "projectId": "JHUPFX01",
            "samples": ["JHAMAA00001"],
        }
    )

    matches = {str(p["_id"]) for p in ProjectModel().use_sample("JHAMAA00001")}
    assert str(project["_id"]) in matches

    matches = {str(p["_id"]) for p in ProjectModel().use_sample("JHAMAA00001-S2R0C0")}
    assert str(project["_id"]) in matches

    assert list(ProjectModel().use_sample("JHAMAB00002")) == []


@pytest.mark.plugin("jsonforms")
def test_item_outside_blessed_collection_is_not_propagated(
    server, admin, accepted_project, aimdl_collection, fsAssetstore, eagerWorkerTasks
):
    other_collection = Collection().createCollection("Not AIMDL", admin, public=True)
    other_folder = Folder().createFolder(
        other_collection, "raw", parentType="collection", creator=admin
    )
    item = Item().createItem("sample1.csv", admin, other_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")
    item = Item().load(item["_id"], force=True)
    Item().setMetadata(item, {"igsn": "JHAMAA00001"})

    ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )

    assert _copies_for(accepted_project) == []


@pytest.mark.plugin("jsonforms")
def test_adding_sample_propagates_existing_data(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    """Notes 3a: adding an IGSN to a project copies already-existing data."""
    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    content = b"hello world"
    _upload_file(item, admin, "sample1.csv", content)
    item = Item().load(item["_id"], force=True)
    item = Item().setMetadata(item, {"igsn": "JHAMAA00001", "data_type": "raw"})

    # Not yet a member of any project, so nothing should be copied yet.
    assert _copies_for(accepted_project) == []

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )

    copies = _copies_for(accepted_project)
    assert len(copies) == 1
    target = copies[0]
    assert target["copyOfItem"] == item["_id"]
    assert target["projectId"] == accepted_project["_id"]
    assert target["meta"] == item["meta"]

    files = list(Item().childFiles(target))
    assert len(files) == 1
    assert _read_file(files[0]) == content


@pytest.mark.plugin("jsonforms")
def test_materialization_flow_propagates_on_igsn_assignment(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    """Notes 4: create empty item, add a file, then assign the IGSN. This
    should propagate immediately since the sample is already registered."""
    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00002"],
        admin,
    )
    assert _copies_for(accepted_project) == []

    item = Item().createItem("sample2.csv", admin, aimdl_folder)
    content = b"some data"
    _upload_file(item, admin, "sample2.csv", content)
    item = Item().load(item["_id"], force=True)

    # File exists, but no IGSN yet -> still nothing propagated.
    assert _copies_for(accepted_project) == []

    item = Item().setMetadata(item, {"igsn": "JHAMAA00002", "data_type": "raw"})

    copies = _copies_for(accepted_project)
    assert len(copies) == 1
    assert copies[0]["copyOfItem"] == item["_id"]
    files = list(Item().childFiles(copies[0]))
    assert _read_file(files[0]) == content


@pytest.mark.plugin("jsonforms")
def test_removing_sample_deletes_project_copy_but_not_original(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    """Notes 3b: removing an IGSN removes the project's copy, but leaves
    the blessed AIMDL item untouched."""
    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")
    item = Item().load(item["_id"], force=True)
    item = Item().setMetadata(item, {"igsn": "JHAMAA00001"})

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )
    assert len(_copies_for(accepted_project)) == 1

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        [],
        admin,
    )

    assert _copies_for(accepted_project) == []
    # Original item is untouched in the blessed collection.
    assert Item().load(item["_id"], force=True) is not None


@pytest.mark.plugin("jsonforms")
def test_updating_samples_adds_and_removes_in_one_call(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    item_a = Item().createItem("a.csv", admin, aimdl_folder)
    _upload_file(item_a, admin, "a.csv", b"aaa")
    item_a = Item().load(item_a["_id"], force=True)
    item_a = Item().setMetadata(item_a, {"igsn": "JHAMAA00001"})

    item_b = Item().createItem("b.csv", admin, aimdl_folder)
    _upload_file(item_b, admin, "b.csv", b"bbb")
    item_b = Item().load(item_b["_id"], force=True)
    item_b = Item().setMetadata(item_b, {"igsn": "JHAMAA00002"})

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )
    assert {c["copyOfItem"] for c in _copies_for(accepted_project)} == {item_a["_id"]}

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00002"],
        admin,
    )
    assert {c["copyOfItem"] for c in _copies_for(accepted_project)} == {item_b["_id"]}


@pytest.mark.plugin("jsonforms")
def test_metadata_update_syncs_to_project_copies(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    """Notes 3c: updating an item's metadata updates every copy's metadata."""
    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")
    item = Item().load(item["_id"], force=True)
    item = Item().setMetadata(item, {"igsn": "JHAMAA00001", "data_type": "raw"})

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )
    target = _copies_for(accepted_project)[0]
    assert "experiment_date" not in target["meta"]

    item = Item().setMetadata(item, {"experiment_date": "2026-01-01"})

    target = Item().load(target["_id"], force=True)
    assert target["meta"] == item["meta"]
    # ISO date strings in metadata are coerced to BSON datetimes on save
    # (see girder_jsonforms.lib.metadata_dates), so the copy holds a datetime.
    assert target["meta"]["experiment_date"] == datetime.datetime(
        2026, 1, 1, tzinfo=datetime.timezone.utc
    )


@pytest.mark.plugin("jsonforms")
def test_new_file_added_to_item_syncs_to_project_copies(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    """Notes 3d (file added): adding a new file to an already-propagated
    item copies it to the project's copy as well."""
    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")
    item = Item().load(item["_id"], force=True)
    item = Item().setMetadata(item, {"igsn": "JHAMAA00001"})

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )
    target = _copies_for(accepted_project)[0]
    assert len(list(Item().childFiles(target))) == 1

    _upload_file(item, admin, "extra.csv", b"more data")

    target = Item().load(target["_id"], force=True)
    files = {f["name"]: _read_file(f) for f in Item().childFiles(target)}
    assert files == {"sample1.csv": b"hello world", "extra.csv": b"more data"}


@pytest.mark.plugin("jsonforms")
def test_file_content_updated_in_place_syncs_to_project_copies(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    """Notes 3d (content updated in place): replacing an existing file's
    bytes (rather than adding a new file) also propagates to copies."""
    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")
    item = Item().load(item["_id"], force=True)
    item = Item().setMetadata(item, {"igsn": "JHAMAA00001"})

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )
    target = _copies_for(accepted_project)[0]

    source_file = list(Item().childFiles(item))[0]
    new_content = b"updated in place"
    upload = Upload().createUploadToFile(source_file, admin, len(new_content))
    Upload().handleChunk(
        upload, RequestBodyStream(io.BytesIO(new_content), len(new_content))
    )

    target = Item().load(target["_id"], force=True)
    files = list(Item().childFiles(target))
    assert len(files) == 1
    assert _read_file(files[0]) == new_content
    assert target["size"] == len(new_content)


@pytest.mark.plugin("jsonforms")
def test_propagate_item_to_project_raises_if_project_collection_missing(
    server, user, admin, aimdl_folder, fsAssetstore
):
    from ..rest.aimdl import propagate_item_to_project

    # A draft project never went through the "accepted" transition, so it
    # has no collection of its own yet.
    project = ProjectModel().create_project(
        {
            "name": "Draft Project",
            "description": "never accepted",
            "creatorId": user["_id"],
        },
        user,
    )

    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")

    with pytest.raises(ValueError, match="Project collection not found"):
        propagate_item_to_project(item, project)


@pytest.mark.plugin("jsonforms")
def test_propagate_item_to_project_skips_name_collision(
    server, admin, accepted_project, aimdl_folder, fsAssetstore
):
    from ..rest.aimdl import propagate_item_to_project

    project_collection = _project_collection(accepted_project)
    colliding_folder = Folder().createFolder(
        project_collection, "raw", parentType="collection", creator=admin
    )
    colliding_item = Item().createItem("sample1.csv", admin, colliding_folder)
    colliding_item["projectId"] = accepted_project["_id"]
    Item().save(colliding_item, triggerEvents=False)

    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")

    propagate_item_to_project(item, accepted_project)

    items_named = list(
        Item().find({"folderId": colliding_folder["_id"], "name": "sample1.csv"})
    )
    assert len(items_named) == 1
    assert items_named[0]["_id"] == colliding_item["_id"]
    assert "copyOfItem" not in items_named[0]


@pytest.fixture
def igsn_family(aimdl_folder, admin, fsAssetstore):
    """A small IGSN hierarchy to exercise derived-IGSN propagation:

    JHABOX00001
    |-- JHABOX00001-001
    |    `-- JHABOX00001-001-001
    `-- JHABOX00001-002
    JHABOX00002 (unrelated top-level IGSN)
    """
    items = {}
    for key, igsn in [
        ("parent", "JHABOX00001"),
        ("child", "JHABOX00001-001"),
        ("grandchild", "JHABOX00001-001-001"),
        ("sibling_child", "JHABOX00001-002"),
        ("unrelated", "JHABOX00002"),
    ]:
        item = Item().createItem(f"{igsn}.csv", admin, aimdl_folder)
        _upload_file(item, admin, f"{igsn}.csv", igsn.encode())
        item = Item().load(item["_id"], force=True)
        items[key] = Item().setMetadata(item, {"igsn": igsn})
    return items


@pytest.mark.plugin("jsonforms")
def test_adding_parent_sample_propagates_all_derived_igsns(
    server, admin, accepted_project, igsn_family, fsAssetstore, eagerWorkerTasks
):
    """Adding a top-level IGSN as a sample must pull in data for every
    derived/child IGSN underneath it (any depth), not just an exact match."""
    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHABOX00001"],
        admin,
    )

    copied_ids = {c["copyOfItem"] for c in _copies_for(accepted_project)}
    assert copied_ids == {
        igsn_family["parent"]["_id"],
        igsn_family["child"]["_id"],
        igsn_family["grandchild"]["_id"],
        igsn_family["sibling_child"]["_id"],
    }


@pytest.mark.plugin("jsonforms")
def test_adding_child_sample_only_covers_its_own_subtree(
    server, admin, accepted_project, igsn_family, fsAssetstore, eagerWorkerTasks
):
    """Adding a derived IGSN as a sample should cover its own descendants
    only, not its ancestor or sibling branches."""
    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHABOX00001-001"],
        admin,
    )

    copied_ids = {c["copyOfItem"] for c in _copies_for(accepted_project)}
    assert copied_ids == {
        igsn_family["child"]["_id"],
        igsn_family["grandchild"]["_id"],
    }


@pytest.mark.plugin("jsonforms")
def test_removing_parent_sample_removes_all_derived_copies(
    server, admin, accepted_project, igsn_family, fsAssetstore, eagerWorkerTasks
):
    """Removing a top-level IGSN must clean up copies of every derived
    IGSN it covered, while leaving the originals in the AIMDL collection."""
    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHABOX00001"],
        admin,
    )
    assert len(_copies_for(accepted_project)) == 4

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        [],
        admin,
    )

    assert _copies_for(accepted_project) == []
    for item in igsn_family.values():
        assert Item().load(item["_id"], force=True) is not None


@pytest.mark.plugin("jsonforms")
def test_removing_child_sample_only_removes_its_own_subtree(
    server, admin, accepted_project, igsn_family, fsAssetstore, eagerWorkerTasks
):
    """Removing a derived IGSN sample must only remove copies within its
    own subtree, leaving copies tracked under a sibling sample intact."""
    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHABOX00001-001", "JHABOX00001-002"],
        admin,
    )
    assert len(_copies_for(accepted_project)) == 3

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHABOX00001-002"],
        admin,
    )

    copied_ids = {c["copyOfItem"] for c in _copies_for(accepted_project)}
    assert copied_ids == {igsn_family["sibling_child"]["_id"]}


@pytest.mark.plugin("jsonforms")
def test_propagation_is_idempotent_for_already_copied_item(
    server, admin, accepted_project, aimdl_folder, fsAssetstore, eagerWorkerTasks
):
    """A second data.process/model.item.save.after event for an item that
    was already propagated should sync the existing copy, not duplicate it."""
    item = Item().createItem("sample1.csv", admin, aimdl_folder)
    _upload_file(item, admin, "sample1.csv", b"hello world")
    item = Item().load(item["_id"], force=True)
    item = Item().setMetadata(item, {"igsn": "JHAMAA00001"})

    accepted_project = ProjectModel().update_samples(
        accepted_project,
        ["JHAMAA00001"],
        admin,
    )
    assert len(_copies_for(accepted_project)) == 1

    from ..rest.aimdl import propagate_to_projects

    propagate_to_projects(item)
    propagate_to_projects(item)

    assert len(_copies_for(accepted_project)) == 1
