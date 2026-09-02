import copy
import datetime
import json
import logging
from pathlib import Path

from girder import events
from girder.api.rest import getApiUrl
from girder.constants import AccessType
from girder.exceptions import GirderException, ValidationException
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.model_base import AccessControlledModel, Model
from girder.models.setting import Setting
from girder.models.user import User
from girder.settings import SettingKey
from girder.utility.model_importer import ModelImporter
from girder.utility.progress import noProgress
from girder_sample_tracker.models.sample import Sample
from pymongo import ReturnDocument
import jsonschema

from ..lib.igsn_client import IGSNServiceError, get_client
from ..lib.igsn_vocab import get_vocabularies
from ..lib.project_helpers import batch_indices
from ..settings import COLLECTION_NAME, PluginSettings
from .form import Form

logger = logging.getLogger(__name__)


class PrefixCounter(Model):
    def initialize(self):
        self.name = "prefixCounter"
        self.ensureIndices(["prefix"])
        self.exposeFields(
            level=AccessType.READ,
            fields=(
                "_id",
                "prefix",
                "seq",
            ),
        )

    def validate(self, doc):
        if not doc.get("prefix"):
            raise ValidationException("Missing prefix")
        prefix = doc["prefix"]
        if not isinstance(prefix, str) or len(prefix) != 6:
            raise ValidationException("Prefix must be 6 characters long")
        vocabularies = get_vocabularies()
        inst = prefix[:2]
        institutions = vocabularies["institutions"]
        if inst not in institutions.keys():
            raise ValidationException(f"Invalid institution {inst}")
        subinst = prefix[2]
        if subinst not in institutions[inst]["labs"]:
            raise ValidationException(f"Invalid subinstitution {subinst}")

        materials = vocabularies["materials"]
        material = prefix[3:5]
        if material not in materials.keys():
            raise ValidationException(f"Invalid material {material}")
        submaterial = prefix[5]
        subcategories = materials[material].get("subcategories", {"X": "empty"})
        if submaterial not in subcategories.keys():
            raise ValidationException(f"Invalid submaterial {submaterial}")
        return doc

    def get_counter(self, prefix):
        if existing := self.findOne({"prefix": prefix}):
            return existing
        return self.save({"prefix": prefix, "seq": 0})

    def increment(self, counter):
        # Filter on _id alone. Passing the whole document made this a
        # compare-and-swap that returns None whenever another process
        # incremented in between, which then blew up in get_next.
        return self.collection.find_one_and_update(
            {"_id": counter["_id"]},
            {"$inc": {"seq": 1}},
            return_document=ReturnDocument.AFTER,
        )

    def get_next(self, prefix):
        """Allocate one IGSN under ``prefix``."""
        return self.get_next_many(prefix, 1)[0]

    def get_next_many(self, prefix, count):
        """Allocate ``count`` IGSNs under ``prefix``.

        In remote mode the central registry allocates, so instances sharing a
        prefix cannot collide. In local mode this is the original per-instance
        counter, which is only safe while exactly one instance uses the prefix.
        """
        client = get_client()
        if client is not None:
            records = client.allocate(prefix, count=count)
            return [record["igsn"] for record in records]

        # Local mode: validate the prefix here, since remote mode gets that
        # from the service.
        self.validate({"prefix": prefix})
        counter = self.get_counter(prefix)
        igsns = []
        for _ in range(count):
            counter = self.increment(counter)
            igsns.append(f"{counter['prefix']}{counter['seq']:05d}")
        return igsns


class SchemaValidator:
    def __init__(self, filename):
        with open(filename, "r") as file:
            schema = json.loads(file.read())
        self.validator = jsonschema.Draft201909Validator(schema)

    def validate(self, data):
        return self.validator.validate(data)


class Deposition(AccessControlledModel):
    def initialize(self):
        self.name = "deposition"
        self.exposeFields(
            level=AccessType.READ,
            fields=(
                "_id",
                "created",
                "creatorId",
                "igsn",
                "imageId",
                "metadata",
                "parentId",
                "public",
                "publicFlags",
                "state",
                "submitted",
                "updated",
                "sampleId",
                "track",
                # Mirrored from the central registry in remote mode; absent in
                # local mode.
                "serviceStatus",
                "publishedAt",
                "serviceError",
            ),
        )
        self.ensureIndices([("igsn", {"unique": True})])
        events.bind("model.entry.save", "jsonforms", self.register_deposition)
        events.bind("model.entry.save.created", "jsonforms", self.updateRelations)
        self.schema_validator = SchemaValidator(
            Path(__file__).parent.parent / "schemas" / "datacite-v4.5.json"
        )

    def filter(self, deposition, user=None, additionalKeys=None):
        deposition = super().filter(
            deposition, user=user, additionalKeys=additionalKeys
        )
        if not isinstance(deposition.get("metadata"), dict):
            return deposition

        # super().filter() copies field-by-field, so `metadata` is still the very
        # same object as the caller's. Replace it with a filtered copy rather
        # than editing it in place, or filtering for one reader would strip
        # identifiers out of the document everyone else is holding.
        deposition["metadata"] = self.visible_metadata(deposition["metadata"], user)

        if deposition.get("sampleId"):
            try:
                Sample().load(
                    deposition["sampleId"], user=user, level=AccessType.READ, exc=True
                )
            except Exception:
                deposition["sampleId"] = None
        return deposition

    @staticmethod
    def visible_metadata(metadata, user):
        """A copy of ``metadata`` holding only what ``user`` may see.

        Related identifiers of type ``HasMetadata`` point at form entries, which
        carry their own ACLs; a reader who cannot read the entry must not learn
        that it exists. ``user=None`` therefore yields the public projection --
        which is what may be published to DataCite, since a DOI record is world
        readable.
        """
        if not isinstance(metadata, dict):
            return metadata
        metadata = copy.deepcopy(metadata)

        visible = []
        for identifier in metadata.get("relatedIdentifiers", []):
            if (
                identifier.get("relationType") == "HasMetadata"
                and "entry" in identifier.get("relatedIdentifier", "")
            ):
                entryId = identifier["relatedIdentifier"].split("/")[-1]
                try:
                    ModelImporter.model("entry", "jsonforms").load(
                        entryId, user=user, level=AccessType.READ, exc=True
                    )
                except Exception:
                    continue
            visible.append(identifier)

        if "relatedIdentifiers" in metadata or visible:
            metadata["relatedIdentifiers"] = visible
        return metadata

    def require_publishable(self, deposition, recurse=False):
        """Refuse to publish a deposition that is not already public.

        Publication mints a world-readable DOI, so it must not be the act that
        makes a record public: whoever publishes has to have made that decision
        first, explicitly. Nothing here flips ``public`` on the caller's behalf.

        With ``recurse`` the batch children are checked too, since the registry
        publishes them as one unit -- a public parent must not carry private
        children into DataCite.
        """
        private = []
        if not deposition.get("public"):
            private.append(deposition["igsn"])
        if recurse:
            children = self.collection.find(
                {"parentId": deposition["_id"], "public": {"$ne": True}},
                {"igsn": 1},
            )
            private += sorted(child["igsn"] for child in children)

        if not private:
            return

        shown = ", ".join(private[:10])
        if len(private) > 10:
            shown += f", and {len(private) - 10} more"
        raise ValidationException(
            f"Refusing to publish: {shown} "
            f"{'is' if len(private) == 1 else 'are'} not public. Publishing mints "
            "a permanent public DOI, so make the record public first -- this will "
            "not do it for you."
        )

    def public_metadata(self, deposition_or_metadata):
        """The metadata that may be published: the anonymous projection.

        Everything the registry sends to DataCite goes through here. Publishing
        the raw document would put links to non-public form entries into a
        world-readable DOI record.
        """
        metadata = deposition_or_metadata
        if isinstance(metadata, dict) and "metadata" in metadata:
            metadata = metadata["metadata"]
        return self.visible_metadata(metadata, None)

    def register_deposition(self, event: events.Event) -> None:
        entry = event.info
        if "_id" in entry:
            logger.info("Entry already exists. Skipping IGSN registration")
            return

        logger.info("Registering deposition from entry save event")
        data = entry.get("data")
        if "igsn_request" in data and not data["igsn_request"]:
            logger.info("No IGSN request or entry already exists")
            return
        else:
            request = data.get("igsn", {}).get("request", False)
            if not request:
                logger.info("No IGSN request or entry already exists")
                return

        if "igsn_prefix" in data:
            prefix = data["igsn_prefix"]
            suffix = data["igsn_suffix"]
            track = data.get("igsn_track", False)
            igsn_metadata = data["igsn"]
        else:
            prefix = data["igsn"]["prefix"]
            suffix = data["igsn"]["suffix"]
            track = data["igsn"].get("track", False)
            igsn_metadata = data["igsnMeta"]

        logger.info(f"Prefix: {prefix}, Suffix: {suffix}, Track: {track}")

        if suffix:
            if self.findOne({"igsn": f"{prefix}{suffix}"}) is not None:
                logger.info("IGSN already exists")
                return

        igsn = PrefixCounter().get_next(prefix)
        suffix = igsn[len(prefix) :]
        creator = User().load(entry["creatorId"], force=True)
        logger.info(f"Creating master IGSN {igsn}")
        master_metadata = {}
        if "title" in igsn_metadata:
            master_metadata["titles"] = [{"title": igsn_metadata.pop("title")}]
        self.fill_metadata(master_metadata, creator)
        if "descriptionAbstract" in igsn_metadata:
            master_metadata["descriptions"].append(
                {
                    "description": igsn_metadata.pop("descriptionAbstract"),
                    "descriptionType": "Abstract",
                }
            )
        if "descriptionMethods" in igsn_metadata:
            master_metadata["descriptions"].append(
                {
                    "description": igsn_metadata.pop("descriptionMethods"),
                    "descriptionType": "Methods",
                }
            )
        if "relatedIdentifiers" in igsn_metadata:
            master_metadata["relatedIdentifiers"] += igsn_metadata.pop(
                "relatedIdentifiers"
            )
        if "attributes" in igsn_metadata:
            if "alternateIdentifiers" in igsn_metadata["attributes"]:
                master_metadata["alternateIdentifiers"] += igsn_metadata[
                    "attributes"
                ].pop("alternateIdentifiers")

        logger.info(f"Whether to track: {track}")
        # Copy access policies from the form to the master sample
        form = Form().load(entry["formId"], force=True)
        master_sample = self.create_deposition(
            master_metadata,
            creator,
            igsn=igsn,
            track=track,
            access=form["access"],
            public=form.get("public", False),
        )
        logger.info(f"Creating batch for {igsn}")
        self.create_batch_from_entry(master_sample, data)

        if "igsn_prefix" in data:
            data["igsn_suffix"] = suffix
            data[data["igsn_field"]] = f"{prefix}{suffix}"
            data["igsn_request"] = False
        else:
            data["igsn"]["suffix"] = suffix
            data["igsn"]["request"] = False
            data[data["igsn"]["field"]] = f"{prefix}{suffix}"
        entry["uniqueId"] = data[form["uniqueField"]]
        event.addResponse(entry)

    def updateRelations(self, event: events.Event) -> None:
        formId = event.info.get("formId")
        data = event.info.get("data", {})
        if "igsn_prefix" in data:
            igsn_suffix = data.get("igsn_suffix")
            igsn_prefix = data.get("igsn_prefix")
        else:
            igsn_suffix = data.get("igsn", {}).get("suffix")
            igsn_prefix = data.get("igsn", {}).get("prefix")

        logger.info(f"{igsn_suffix=}, {igsn_prefix=}")

        errmsg = deposition = None
        if deposition_id := data.get("depositionId"):
            logger.info(f"Looking for {deposition_id=}")
            deposition = self.load(deposition_id, force=True)
            errmsg = f"[updateRelations] Deposition {deposition_id} not found (entry {event.info['_id']})"
        elif igsn_suffix and igsn_prefix:
            logger.info(f"Looking for IGSN: {igsn_prefix}{igsn_suffix}")
            deposition = self.findOne({"igsn": f"{igsn_prefix}{igsn_suffix}"})
            errmsg = f"[updateRelations] Deposition {igsn_prefix}{igsn_suffix} not found (entry {event.info['_id']})"

        if not deposition:
            if errmsg:
                logger.error(errmsg)
            return

        try:
            api_url = getApiUrl()
        except GirderException:
            api_url = "/api/v1"

        relatedIdentifier = {
            "relationType": "HasMetadata",
            "relatedIdentifier": "/".join((api_url, "entry", str(event.info["_id"]))),
            "relatedIdentifierType": "URL",
            "relatedMetadataScheme": "/".join((api_url, "form", str(formId), "schema")),
        }

        logger.info(f"Updating relations for {deposition['igsn']}")
        self.collection.update_one(
            {"_id": deposition["_id"]},
            {"$addToSet": {"metadata.relatedIdentifiers": relatedIdentifier}},
        )

        logger.info(f"Updating relations for {deposition['igsn']}")
        self.collection.update_many(
            {"parentId": deposition["_id"]},
            {"$addToSet": {"metadata.relatedIdentifiers": relatedIdentifier}},
        )

        # Both writes above go straight to the collection and so never reach
        # save(); the registry has to be told separately or its copy of the
        # metadata silently falls behind.
        self.queue_registry_sync(
            [deposition["_id"]]
            + [
                child["_id"]
                for child in self.collection.find(
                    {"parentId": deposition["_id"]}, {"_id": 1}
                )
            ]
        )

    @staticmethod
    def queue_registry_sync(deposition_ids):
        """Queue a metadata push for depositions changed via raw collection writes.

        Imported lazily: this model is loaded by the girder-worker plugin too,
        and importing the task module at module scope would be circular.
        """
        from ..worker_plugin.igsn_registry import sync_after_relation_change

        sync_after_relation_change(deposition_ids)

    def validate(self, doc):
        try:
            self.schema_validator.validate(doc.get("metadata", {}))
        except jsonschema.ValidationError as e:
            raise ValidationException(f"Metadata validation failed: {e.message}") from e
        if not doc["metadata"].get("doi"):
            doc["metadata"][
                "doi"
            ] = f"{Setting().get(PluginSettings.IGSN_PREFIX)}/{doc['igsn']}"
        if not doc["metadata"].get("url"):
            if landing_page := self.landing_page(doc["igsn"]):
                doc["metadata"]["url"] = landing_page
        return doc

    @staticmethod
    def compute_identifier(metadata, root=True):
        return metadata.get("title", "")

    @staticmethod
    def landing_page(igsn):
        """This Girder's landing page for an IGSN, or None if it has no address.

        ``core.server_root`` is unset on plenty of instances, and
        ``os.path.join("", "#igsn", igsn)`` quietly yields ``"#igsn/IGSN"`` -- a
        bare fragment. That was harmless while nothing published; once the
        central registry started forwarding it to DataCite it became a 422
        ("URL is not valid"). Returning None instead lets the registry's own
        resolver be the landing page, which is the designed fallback.
        """
        server_root = (Setting().get(SettingKey.SERVER_ROOT) or "").strip()
        if not server_root.startswith(("http://", "https://")):
            if server_root:
                logger.warning(
                    "%s is %r, which is not an absolute URL; falling back to the "
                    "IGSN registry's resolver for %s",
                    SettingKey.SERVER_ROOT,
                    server_root,
                    igsn,
                )
            return None
        return "/".join((server_root.rstrip("/"), "#igsn", igsn))

    # -- central registry -------------------------------------------------- #
    #
    # In remote mode the service is the registry of record for DataCite
    # metadata, and the local deposition is Girder's working copy. Several code
    # paths mutate metadata with raw ``collection.update_*`` and so bypass
    # ``save()`` entirely; each of those needs an explicit push, which is what
    # ``sync_to_registry`` is for.

    def _push_to_registry(self, igsn, metadata, landing_page=None, external_ref=None):
        """Send metadata for ``igsn`` to the registry. No-op in local mode.

        Filters here rather than trusting callers: this and ``sync_to_registry``
        are the only two paths to the registry, so filtering at both makes it
        impossible to publish private metadata by forgetting to.
        """
        client = get_client()
        if client is None:
            return None
        try:
            return client.put_record(
                igsn,
                metadata=self.public_metadata(metadata),
                landing_page=landing_page,
                external_ref=external_ref,
            )
        except IGSNServiceError as exc:
            if exc.status_code == 404:
                # A caller supplied an IGSN the registry has never issued. Worth
                # shouting about -- it means Girder holds an identifier outside
                # the central namespace -- but not worth refusing the local
                # record, which reconcile will then report.
                logger.error(
                    "%s is not in the IGSN registry; storing it locally only", igsn
                )
                return None
            raise

    def sync_to_registry(self, deposition, force=False):
        """Push a deposition's current metadata to the registry.

        Swallows service errors by design: a metadata push that fails must not
        break the Girder operation that triggered it. Drift is repaired by the
        ``reconcile`` task, and the error is recorded on the deposition so it is
        visible. Identifier *allocation* is the opposite -- that must fail hard,
        and does.
        """
        client = get_client()
        if client is None:
            return None
        try:
            record = client.put_record(
                deposition["igsn"],
                # Only what an anonymous reader may see. A DataCite record is
                # world readable, so publishing the raw document would leak
                # links to non-public form entries.
                metadata=self.public_metadata(deposition),
                external_ref={
                    "system": "girder",
                    "id": str(deposition["_id"]),
                },
            )
        except IGSNServiceError:
            logger.exception(
                "Could not sync %s to the IGSN registry", deposition["igsn"]
            )
            self.collection.update_one(
                {"_id": deposition["_id"]},
                {"$set": {"serviceError": "metadata sync failed"}},
            )
            return None
        self.apply_registry_state(deposition["_id"], record)
        return record

    def apply_registry_state(self, deposition_id, record):
        """Mirror the registry's view of a record onto the local deposition.

        ``state`` stays the field the rest of the plugin already keys off (the
        delete guard in rest/deposition.py, and the hand-run publish scripts):
        it becomes "published" once DataCite has the record as findable, and
        stays "draft" otherwise.
        """
        if not record:
            return
        status = record.get("status")
        updates = {
            "serviceStatus": status,
            "serviceError": (record.get("datacite") or {}).get("last_error"),
            "state": "published" if status == "findable" else "draft",
            "submitted": status in ("registered", "findable"),
        }
        if record.get("published_at"):
            updates["publishedAt"] = record["published_at"]
        self.collection.update_one({"_id": deposition_id}, {"$set": updates})

    def fill_metadata(self, metadata, creator):
        if "types" not in metadata:
            metadata["types"] = {
                "resourceType": "material sample",
                "resourceTypeGeneral": "PhysicalObject",
            }
        if "publisher" not in metadata:
            metadata["publisher"] = Setting().get(PluginSettings.IGSN_PUBLISHER)
        if "dates" not in metadata:
            metadata["dates"] = [
                {
                    "date": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"),
                    "dateType": "Submitted",
                }
            ]

        if "publicationYear" not in metadata:
            metadata["publicationYear"] = str(datetime.datetime.now(datetime.UTC).year)

        for key in (
            "creators",
            "subjects",
            "contributors",
            "sizes",
            "formats",
            "rightsList",
            "descriptions",
            "geoLocations",
            "fundingReferences",
            "alternateIdentifiers",
            "relatedIdentifiers",
            "relatedItems",
        ):
            if key not in metadata:
                metadata[key] = []

        if not metadata["creators"]:
            metadata["creators"] = [
                {
                    "name": creator.get("lastName", "")
                    + ", "
                    + creator.get("firstName", ""),
                    "nameType": "Personal",
                    "givenName": creator.get("firstName", ""),
                    "familyName": creator.get("lastName", ""),
                }
            ]

        if "schemaVersion" not in metadata:
            metadata["schemaVersion"] = "http://datacite.org/schema/kernel-4"

    def create_deposition(
        self,
        metadata,
        creator,
        prefix=None,
        igsn=None,
        parent=None,
        track=False,
        access=None,
        public=False,
        save=True,
        batch=0,
    ):
        if igsn is None and prefix is None:
            raise ValidationException("Either IGSN or prefix must be provided")

        if not parent:
            parent = {"_id": None}

        now = datetime.datetime.now(datetime.UTC)
        metadata = metadata or {}
        self.fill_metadata(metadata, creator)

        # TODO: better check for valid prefix
        if not igsn:
            igsn = PrefixCounter().get_next(prefix)
        else:
            if Deposition().findOne({"igsn": igsn}):
                raise ValidationException(f"IGSN {igsn} already exists")

        landing_page = self.landing_page(igsn)
        metadata["doi"] = f"{Setting().get(PluginSettings.IGSN_PREFIX)}/{igsn}"
        if landing_page:
            metadata["url"] = landing_page

        # Push metadata whenever the registry is in play -- not only when this
        # call did the allocating. register_deposition (the form-entry path,
        # which is how most IGSNs are minted) allocates first and passes the
        # identifier in, so keying off "did I allocate?" meant that path never
        # sent its metadata at all: the registry kept a bare doi/url, and batch
        # children derived from it inherited nothing.
        #
        # Allocation only reserves the identifier; the metadata and landing page
        # need this second call because the landing URL contains the IGSN. It is
        # idempotent, so a retry is safe.
        registry_record = None
        if get_client() is not None:
            registry_record = self._push_to_registry(igsn, metadata, landing_page)

        deposition = {
            "created": now,
            "creatorId": creator["_id"],
            "igsn": igsn,
            "metadata": metadata,
            "parentId": parent["_id"],
            "state": "draft",
            "submitted": False,
            "updated": now,
            "sampleId": None,
            "track": track,
            "public": public,
            "publicFlags": [],
        }

        # Mirror the registry's view from the outset, so nothing keyed off
        # serviceStatus has to wait for a later sync to see the record exists.
        if registry_record and registry_record.get("status"):
            deposition["serviceStatus"] = registry_record["status"]

        if parent["_id"]:
            self.copyAccessPolicies(src=parent, dest=deposition, save=False)

        if access:
            deposition["access"] = copy.deepcopy(access)

        if creator is not None:
            self.setUserAccess(
                deposition, user=creator, level=AccessType.ADMIN, save=False
            )

        if deposition["track"]:
            sample = Sample().create(igsn, creator, access=deposition["access"])
            deposition["sampleId"] = sample["_id"]

        if save:
            deposition = self.save(deposition)
            events.trigger("deposition.created", {"ids": [deposition["_id"]]})

        if batch > 0:
            igsn_indices = [f"{i+1:03d}" for i in range(batch)]
            if local_identifier := self.local_identifier(metadata):
                # If a local identifier is provided, use it for all indices
                local_indices = [f"{local_identifier}-{i+1:03d}" for i in range(batch)]
            else:
                local_indices = [None] * batch
            indices = list(zip(igsn_indices, local_indices))
            self.create_batch(deposition, indices)
        return deposition

    def create_batch_from_entry(self, main_deposition, form_data):
        method = form_data.get("igsn", {}).get("batch", {}).get("method", "unknown")
        indices = batch_indices(method, main_deposition, form_data)
        if not indices:
            logger.error("Missing required fields for batch creation")
            return
        self.create_batch(main_deposition, indices)

    @staticmethod
    def local_identifier(metadata):
        """
        Generate a local identifier based on the metadata.
        This is used for batch processing to create unique identifiers.
        """
        if "alternateIdentifiers" in metadata:
            for alt_id in metadata["alternateIdentifiers"]:
                if alt_id.get("alternateIdentifierType").lower() == "local":
                    return alt_id.get("alternateIdentifier")
        return None

    def create_batch(self, main_deposition, indices, already_registered=False):
        # Register the children centrally first. If the registry rejects the
        # batch (a duplicate index, an unknown parent) nothing is written
        # locally either -- otherwise Girder would be left holding children the
        # registry has never heard of, which is exactly the divergence the
        # central service exists to prevent.
        #
        # ``already_registered`` is for callers that had to ask the registry for
        # the indices in the first place (see rest.deposition.next_batch_indices);
        # registering them twice would collide with itself.
        client = None if already_registered else get_client()
        registry_status = {}
        if client is not None:
            registered = client.allocate_children(
                main_deposition["igsn"],
                indices=[igsn_index for igsn_index, _ in indices],
                local_identifiers={
                    igsn_index: local_index
                    for igsn_index, local_index in indices
                    if local_index
                },
            )
            registry_status = {r["igsn"]: r.get("status") for r in registered}
        elif already_registered and get_client() is not None:
            # The caller registered them (rest.deposition.next_batch_indices), so
            # ask the registry what it now holds rather than guessing.
            registry_status = {
                f"{main_deposition['igsn']}-{igsn_index}": "reserved"
                for igsn_index, _ in indices
            }

        relatedIdentifier = {
            "relationType": "IsPartOf",
            "relatedIdentifier": main_deposition["igsn"],
            "relatedIdentifierType": "IGSN",
        }

        depositions = []
        igsn_prefix = Setting().get(PluginSettings.IGSN_PREFIX)
        for index in indices:
            metadata = copy.deepcopy(main_deposition["metadata"])
            metadata["relatedIdentifiers"].append(relatedIdentifier)
            # remove all hasPart relations from the child metadata to avoid circular references
            relatedIdentifiers = metadata.get("relatedIdentifiers", [])
            metadata["relatedIdentifiers"] = [
                relatedIdentifier
                for relatedIdentifier in relatedIdentifiers
                if relatedIdentifier["relationType"] != "HasPart"
            ]
            metadata.pop("url", None)
            metadata.pop("doi", None)
            titles = metadata.pop("titles")
            igsn_index, local_index = index
            logger.info(
                f"Creating deposition for {main_deposition['igsn']} with index {igsn_index} "
                f"and local index {local_index}"
            )
            child_igsn = f"{main_deposition['igsn']}-{igsn_index}"
            child_metadata = {
                "titles": [{"title": f"{titles[0]['title']} - {igsn_index}"}],
                "doi": f"{igsn_prefix}/{child_igsn}",
                **metadata.copy(),
            }
            # Omit `url` entirely when this instance has no absolute address,
            # rather than storing a bare "#igsn/..." fragment. See landing_page().
            if child_landing_page := self.landing_page(child_igsn):
                child_metadata["url"] = child_landing_page
            now = datetime.datetime.now(datetime.UTC)
            deposition = {
                "access": main_deposition["access"],
                "created": now,
                "creatorId": main_deposition["creatorId"],
                "igsn": child_igsn,
                "metadata": child_metadata,
                "parentId": main_deposition["_id"],
                "public": main_deposition.get("public"),
                "publicFlags": main_deposition.get("publicFlags", []),
                "sampleId": None,
                "state": "draft",
                "submitted": False,
                "updated": now,
                "track": main_deposition["track"],
            }
            # Mirror the registry's view, exactly as create_deposition does for a
            # parent. Without this children carry no serviceStatus, and anything
            # keyed off it -- notably the web client's Publish action -- treats
            # them as if the registry had never heard of them.
            if child_status := registry_status.get(child_igsn):
                deposition["serviceStatus"] = child_status

            if local_index:
                # Overwrite the alternate identifier
                deposition["metadata"]["alternateIdentifiers"] = [
                    {
                        "alternateIdentifier": local_index,
                        "alternateIdentifierType": "Local",
                    }
                ]
            depositions.append(deposition)

        if main_deposition["track"] and main_deposition["sampleId"]:
            main_sample = Sample().load(main_deposition["sampleId"], force=True)
            now = datetime.datetime.now(datetime.UTC)
            samples = [
                {
                    "access": main_sample["access"],
                    "created": now,
                    "creator": main_sample["creator"],
                    "description": main_sample["description"],
                    "eventTypes": main_sample["eventTypes"],
                    "events": [],
                    "name": f"{main_deposition['igsn']}-{igsn_index}",
                    "updated": now,
                }
                for igsn_index, _ in indices
            ]
            sample_result = Sample().collection.insert_many(samples)
            for deposition, sample_id in zip(depositions, sample_result.inserted_ids):
                deposition["sampleId"] = sample_id

        # HasPart for the main deposition
        has_parts = [
            {
                "relationType": "HasPart",
                "relatedIdentifier": _["igsn"],
                "relatedIdentifierType": "IGSN",
            }
            for _ in depositions
        ]
        self.collection.update_one(
            {"_id": main_deposition["_id"]},
            {"$addToSet": {"metadata.relatedIdentifiers": {"$each": has_parts}}},
        )
        new_depositions = self.collection.insert_many(depositions)
        events.trigger("deposition.created", {"ids": new_depositions.inserted_ids})
        return new_depositions

    def update_deposition(self, deposition, metadata, sampleId, user=None):
        try:
            sample = Sample().load(sampleId, user=user, level=AccessType.READ)
        except Exception:
            sample = None
        if sample:
            deposition["sampleId"] = sample["_id"]
            deposition["track"] = True
        else:
            deposition["sampleId"] = None
            deposition["track"] = False
        deposition["metadata"].update(metadata)
        deposition["updated"] = datetime.datetime.now(datetime.UTC)

        deposition = self.save(deposition)
        # The registry is the metadata of record, so an edit here has to reach
        # it. Doing this inline (rather than via a task) keeps the caller's
        # round-trip authoritative: if the registry rejects the metadata, the
        # editor finds out now. sync_to_registry swallows transport errors, so a
        # brief outage still leaves the local edit intact for reconcile.
        self.sync_to_registry(deposition)
        return self.load(deposition["_id"], force=True)

    def setAccessList(
        self,
        doc,
        access,
        save=True,
        recurse=False,
        user=None,
        progress=noProgress,
        setPublic=None,
        publicFlags=None,
        force=False,
    ):
        progress.update(increment=1, message=f"Updating deposition {doc['igsn']}")
        if setPublic is not None:
            self.setPublic(doc, setPublic, save=False)

        if publicFlags is not None:
            doc = self.setPublicFlags(
                doc, publicFlags, user=user, save=False, force=force
            )

        doc = super().setAccessList(doc, access, user=user, save=save, force=force)
        self._get_assets_folder(doc)

        if recurse:
            children = self.findWithPermissions(
                {
                    "parentId": doc["_id"],
                },
                user=user,
                level=AccessType.ADMIN,
                limit=0,
            )
            for child in children:
                self.setAccessList(
                    child,
                    access,
                    save=True,
                    recurse=True,
                    user=user,
                    progress=progress,
                    setPublic=setPublic,
                    publicFlags=publicFlags,
                    force=force,
                )
            if not doc.get("sampleId"):
                return doc
            if sample := Sample().load(
                doc.get("sampleId"), user=user, level=AccessType.ADMIN
            ):
                if setPublic is not None:
                    sample = Sample().setPublic(sample, setPublic, save=False)
                if publicFlags is not None:
                    sample = Sample().setPublicFlags(
                        sample, publicFlags, user=user, save=False, force=force
                    )
                Sample().setAccessList(
                    sample,
                    access,
                    save=True,
                    user=user,
                    force=force,
                )

        return doc

    def _get_assets_folder(self, deposition):
        collection = Collection().createCollection(
            COLLECTION_NAME,
            public=False,
            reuseExisting=True
        )
        folder = Folder().createFolder(
            collection,
            deposition["igsn"],
            parentType="collection",
            public=True,
            reuseExisting=True
        )
        current_access = Folder().getFullAccessList(folder)
        access = self.getFullAccessList(deposition)
        if current_access != access:
            folder = Folder().setAccessList(folder, access, save=True, user=None, force=True)

        return folder
