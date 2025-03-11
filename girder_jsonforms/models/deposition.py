import datetime
import itertools
import logging
import string
import pprint

from girder import events
from girder.api.rest import getApiUrl
from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.model_base import AccessControlledModel, Model
from girder.models.setting import Setting
from girder.models.user import User

from ..settings import PluginSettings

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
        inst = prefix[:2]
        institutions = Setting().get(PluginSettings.IGSN_INSTITUTIONS)
        if inst not in institutions.keys():
            raise ValidationException(f"Invalid institution {inst}")
        subinst = prefix[2]
        target_sub = [
            letter
            for letter, _ in zip(string.ascii_uppercase, institutions[inst]["labs"])
        ]
        if subinst not in target_sub:
            raise ValidationException(f"Invalid subinstitution {subinst}")

        materials = Setting().get(PluginSettings.IGSN_MATERIALS)
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
        return self.collection.find_one_and_update(counter, {"$inc": {"seq": 1}})

    def get_next(self, prefix):
        counter = self.get_counter(prefix)
        counter = self.increment(counter)
        return f"{counter['prefix']}{counter['seq']:05d}"


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
                "metadata",
                "parentId",
                "state",
                "submitted",
                "updated",
            ),
        )
        events.bind("model.entry.save", "jsonforms", self.register_deposition)
        events.bind("model.entry.save.created", "jsonforms", self.updateRelations)

    def register_deposition(self, event: events.Event) -> None:
        entry = event.info

        data = entry.get("data")
        if not data.get("igsn_request") or "_id" in entry:
            logger.info("No IGSN request or entry already exists")
            return

        prefix = data["igsn_prefix"]
        suffix = data["igsn_suffix"]
        if suffix:
            if self.findOne({"igsn": f"{prefix}{suffix}"}) is not None:
                logger.info("IGSN already exists")
                return

        igsn = PrefixCounter().get_next(prefix)
        suffix = igsn[len(prefix) :]
        creator = User().load(entry["creatorId"], force=True)
        igsn_metadata = data["igsn"]
        logger.info(f"Creating master IGSN {igsn}")
        master_metadata = {
            "titles": [{"title": igsn_metadata["title"]}],
        }
        self.fill_metadata(master_metadata)
        master_sample = self.create_deposition(
            master_metadata,
            creator,
            igsn=igsn,
        )
        logger.info(f"Creating batch for {igsn}")
        self.create_batch(
            master_sample,
            igsn_metadata,
        )

        data["igsn_suffix"] = suffix
        data[data["igsn_field"]] = f"{prefix}{suffix}"
        data["igsn_request"] = False
        event.addResponse(entry)

    def updateRelations(self, event: events.Event) -> None:
        formId = event.info.get("formId")
        data = event.info.get("data", {})
        igsn_suffix = data.get("igsn_suffix")
        igsn_prefix = data.get("igsn_prefix")

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

        relatedIdentifier = {
            "relationType": "HasMetadata",
            "relatedIdentifier": "/".join(
                (getApiUrl(), "entry", str(event.info["_id"]))
            ),
            "relatedIdentifierType": "URL",
            "relatedMetadataScheme": "/".join(
                (getApiUrl(), "form", str(formId), "schema")
            ),
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

    def validate(self, doc):
        return doc

    @staticmethod
    def compute_identifier(metadata, root=True):
        return metadata.get("title", "")

    def fill_metadata(self, metadata):
        if "types" not in metadata:
            metadata["types"] = {
                "schemaOrg": "CreativeWork",
                "resourceType": "material sample",
                "resourceTypeGeneral": "PhysicalObject",
            }
        if "publisher" not in metadata:
            metadata["publisher"] = {
                "name": Setting().get(PluginSettings.IGSN_PUBLISHER),
            }
        if "dates" not in metadata:
            metadata["dates"] = [
                {
                    "date": datetime.datetime.utcnow().isoformat(),
                    "dateType": "Submitted",
                }
            ]

        if "publicationYear" not in metadata:
            metadata["publicationYear"] = datetime.datetime.utcnow().year

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
            "identifiers",
            "relatedIdentifiers",
            "relatedItems",
        ):
            if key not in metadata:
                metadata[key] = []

        if "schemaVersion" not in metadata:
            metadata["schemaVersion"] = "http://datacite.org/schema/kernel-4"

        if "agency" not in metadata:
            metadata["agency"] = "datacite"

        if "clientId" not in metadata:
            metadata["clientId"] = Setting().get(PluginSettings.IGSN_CLIENT_ID)
        if "providerId" not in metadata:
            metadata["providerId"] = Setting().get(PluginSettings.IGSN_PROVIDER_ID)

    def create_deposition(
        self,
        metadata,
        creator,
        prefix=None,
        igsn=None,
        parent=None,
    ):
        if igsn is None and prefix is None:
            raise ValidationException("Either IGSN or prefix must be provided")

        if not parent:
            parent = {"_id": None}

        now = datetime.datetime.utcnow()
        metadata = metadata or {}
        self.fill_metadata(metadata)

        # TODO: better check for valid prefix
        if not igsn:
            igsn = PrefixCounter().get_next(prefix)

        deposition = {
            "created": now,
            "creatorId": creator["_id"],
            "igsn": igsn,
            "metadata": metadata,
            "parentId": parent["_id"],
            "state": "draft",
            "submitted": False,
            "updated": now,
        }

        return self.save(deposition)

    def create_batch(self, master_sample, igsn_metadata):
        if (
            not igsn_metadata.get("substrates")
            or not igsn_metadata.get("subRows")
            or not igsn_metadata.get("subCols")
        ):
            pprint.pprint(igsn_metadata)
            logger.error("Missing required fields for batch creation")
            return

        indices = [
            "S{}R{}C{}".format(*row)
            for row in itertools.product(
                igsn_metadata["substrates"],
                range(1, igsn_metadata["subRows"] + 1),
                range(1, igsn_metadata["subCols"] + 1),
            )
        ]

        relatedIdentifier = {
            "relationType": "IsPartOf",
            "relatedIdentifier": master_sample["igsn"],
            "relatedIdentifierType": "IGSN",
        }

        metadata = master_sample["metadata"].copy()
        metadata["relatedIdentifiers"].append(relatedIdentifier)
        titles = metadata.pop("titles")

        samples = [
            {
                "created": master_sample["created"],
                "creatorId": master_sample["creatorId"],
                "igsn": f"{master_sample['igsn']}/{index}",
                "metadata": {
                    "titles": [{"title": f"{titles[0]['title']} - {index}"}],
                    **metadata,
                },
                "parentId": master_sample["_id"],
                "state": "draft",
                "submitted": False,
                "updated": master_sample["updated"],
            }
            for index in indices
        ]
        pprint.pprint(samples[0])
        self.collection.insert_many(samples)

    def update_deposition(self, deposition, metadata):
        deposition["metadata"] = metadata
        deposition["updated"] = datetime.datetime.utcnow()

        return self.save(deposition)
