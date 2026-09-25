"""Tests for the folder-scoped ACL shortcut behind ``/aimdl/datafiles``.

``BaseLabResource._acl_scoped_query`` replaces girder's per-item ``$lookup``
with a ``folderId`` clause built from the folders the caller can read. It is a
permission boundary, so what matters here is not that it is faster but that it
admits and excludes exactly the same items ``findWithPermissions`` would --
every test below asserts against the thing it replaces rather than against a
hand-written expectation.

Model level, no ``server`` fixture, per CLAUDE.md on not mixing the two.
"""

import pytest
from girder.constants import AccessType
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.group import Group
from girder.models.item import Item
from girder.models.user import User

from ..rest.aimdl import BaseLabResource

SORT = [("created", -1), ("_id", 1)]


def query(base):
    """The shape ``get_items_by_datatype`` builds."""
    return {
        "meta.igsn": {"$exists": True},
        "meta.data_type": "xrd_raw",
        "baseParentId": base["_id"],
        "baseParentType": "collection",
    }


def readable_via_core(q, user):
    """What ``findWithPermissions`` admits -- the reference answer."""
    cursor = Item().findWithPermissions(q, user=user, level=AccessType.READ, sort=SORT)
    return [item["_id"] for item in cursor]


def readable_via_shortcut(q, user):
    scoped = BaseLabResource._acl_scoped_query(q, user)
    return [item["_id"] for item in Item().find(scoped, sort=SORT)]


@pytest.fixture
def tree(db, admin):
    """A collection with an open folder, a closed one, and a stray item.

    ``open`` is readable by ``members``; ``closed`` is not readable by anyone
    but the admin. Both hold a matching item, so a correct filter returns one
    and an incorrect one returns zero or two.
    """
    collection = Collection().createCollection("AIMDL-ACL", admin, public=False)
    folders = {}
    items = {}
    for name in ("open", "closed"):
        folder = Folder().createFolder(
            collection, name, parentType="collection", creator=admin, public=False
        )
        item = Item().createItem(f"{name}.xrdml", admin, folder)
        Item().setMetadata(item, {"data_type": "xrd_raw", "igsn": f"IGSN-{name}"})
        folders[name] = folder
        items[name] = Item().load(item["_id"], force=True)

    # An item with no folder at all. The $lookup joins nothing for it and so
    # drops it; the shortcut must drop it too.
    orphan = Item().createItem("orphan.xrdml", admin, folders["open"])
    Item().setMetadata(orphan, {"data_type": "xrd_raw", "igsn": "IGSN-orphan"})
    Item().collection.update_one({"_id": orphan["_id"]}, {"$unset": {"folderId": ""}})
    items["orphan"] = Item().load(orphan["_id"], force=True)

    yield {"collection": collection, "folders": folders, "items": items}
    Collection().remove(collection)


@pytest.fixture
def member(db, tree):
    """A non-admin who can read ``open`` and not ``closed``, via a group."""
    person = User().createUser(
        "aclmember", "P@ssw0rd123", "Acl", "Member", "aclmember@example.invalid"
    )
    group = Group().createGroup("acl-members", person, public=False)
    Folder().setGroupAccess(tree["folders"]["open"], group, AccessType.READ, save=True)
    yield User().load(person["_id"], force=True)
    Group().remove(Group().load(group["_id"], force=True))
    User().remove(User().load(person["_id"], force=True))


@pytest.fixture
def outsider(db):
    """A non-admin with no access to anything in the tree."""
    person = User().createUser(
        "acloutsider", "P@ssw0rd123", "Acl", "Outsider", "acloutsider@example.invalid"
    )
    yield person
    User().remove(User().load(person["_id"], force=True))


class TestShortcutMatchesCore:
    def test_partial_access(self, tree, member):
        q = query(tree["collection"])
        assert readable_via_shortcut(q, member) == readable_via_core(q, member)

    def test_partial_access_sees_only_the_open_folder(self, tree, member):
        # Pinned explicitly as well as against core: if both regressed the same
        # way, comparing them to each other would not notice.
        q = query(tree["collection"])
        assert readable_via_shortcut(q, member) == [tree["items"]["open"]["_id"]]

    def test_no_access(self, tree, outsider):
        q = query(tree["collection"])
        assert readable_via_shortcut(q, outsider) == []
        assert readable_via_core(q, outsider) == []

    def test_admin_sees_everything_with_a_folder(self, tree, admin):
        q = query(tree["collection"])
        assert sorted(readable_via_shortcut(q, admin)) == sorted(
            readable_via_core(q, admin)
        )

    def test_item_without_a_folder_is_excluded(self, tree, member, admin):
        q = query(tree["collection"])
        orphan = tree["items"]["orphan"]["_id"]
        assert orphan not in readable_via_shortcut(q, member)
        assert orphan not in readable_via_core(q, member)

    def test_access_granted_is_reflected(self, tree, member):
        q = query(tree["collection"])
        group = Group().findOne({"name": "acl-members"})
        Folder().setGroupAccess(
            tree["folders"]["closed"], group, AccessType.READ, save=True
        )
        member = User().load(member["_id"], force=True)
        assert sorted(readable_via_shortcut(q, member)) == sorted(
            readable_via_core(q, member)
        )
        assert len(readable_via_shortcut(q, member)) == 2

    def test_access_revoked_is_reflected(self, tree, member):
        q = query(tree["collection"])
        group = Group().findOne({"name": "acl-members"})
        Folder().setGroupAccess(tree["folders"]["open"], group, None, save=True)
        member = User().load(member["_id"], force=True)
        # Nothing is cached, so a revoke takes effect on the next request.
        assert readable_via_shortcut(q, member) == readable_via_core(q, member) == []


class TestScopedQueryShape:
    def test_admin_gets_no_folder_clause(self, tree, admin):
        scoped = BaseLabResource._acl_scoped_query(query(tree["collection"]), admin)
        assert "folderId" not in scoped

    def test_non_admin_gets_a_folder_clause(self, tree, member):
        scoped = BaseLabResource._acl_scoped_query(query(tree["collection"]), member)
        assert scoped["folderId"] == {"$in": [tree["folders"]["open"]["_id"]]}

    def test_no_access_yields_an_empty_clause(self, tree, outsider):
        # An empty $in matches nothing, which is the correct answer -- not a
        # missing filter, which would match everything.
        scoped = BaseLabResource._acl_scoped_query(query(tree["collection"]), outsider)
        assert scoped["folderId"] == {"$in": []}

    def test_original_query_is_not_mutated(self, tree, member):
        q = query(tree["collection"])
        BaseLabResource._acl_scoped_query(q, member)
        assert "folderId" not in q

    @pytest.mark.parametrize("missing", ["baseParentId", "baseParentType"])
    def test_unscoped_query_falls_back(self, tree, member, missing):
        q = query(tree["collection"])
        del q[missing]
        assert BaseLabResource._acl_scoped_query(q, member) is None

    def test_anonymous_falls_back_to_public_folders_only(self, tree):
        # user=None is not a route this endpoint takes today (@access.user), but
        # the helper must not blow up on it if one ever does.
        scoped = BaseLabResource._acl_scoped_query(query(tree["collection"]), None)
        assert scoped["folderId"] == {"$in": []}
