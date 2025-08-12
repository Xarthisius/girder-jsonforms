import copy
import datetime
import json
import logging
from pathlib import Path

from girder import events
from girder.api.rest import getApiUrl
from girder.constants import AccessType
from girder.exceptions import GirderException, ValidationException
from girder.models.model_base import AccessControlledModel, Model
from girder.models.setting import Setting
from girder.models.user import User
from girder.utility.model_importer import ModelImporter
from girder.utility.progress import noProgress
from girder_sample_tracker.models.sample import Sample
from pymongo import ReturnDocument
import jsonschema

from ..lib.project_helpers import batch_indices
from ..settings import PluginSettings
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
        inst = prefix[:2]
        institutions = Setting().get(PluginSettings.IGSN_INSTITUTIONS)
        if inst not in institutions.keys():
            raise ValidationException(f"Invalid institution {inst}")
        subinst = prefix[2]
        if subinst not in institutions[inst]["labs"]:
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
        return self.collection.find_one_and_update(
            counter, {"$inc": {"seq": 1}}, return_document=ReturnDocument.AFTER
        )

    def get_next(self, prefix):
        counter = self.get_counter(prefix)
        counter = self.increment(counter)
        return f"{counter['prefix']}{counter['seq']:05d}"


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
                "metadata",
                "parentId",
                "public",
                "publicFlags",
                "state",
                "submitted",
                "updated",
                "sampleId",
                "track",
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
        filtered_identifiers = []
        if not isinstance(deposition.get("metadata"), dict):
            return deposition
        for identifier in deposition["metadata"].get("relatedIdentifiers", []):
            if (
                identifier["relationType"] == "HasMetadata"
                and "entry" in identifier["relatedIdentifier"]
            ):
                entryId = identifier["relatedIdentifier"].split("/")[-1]
                try:
                    ModelImporter.model("entry", "jsonforms").load(
                        entryId, user=user, level=AccessType.READ, exc=True
                    )
                except Exception:
                    continue
            filtered_identifiers.append(identifier)

        deposition["metadata"]["relatedIdentifiers"] = filtered_identifiers

        if deposition.get("sampleId"):
            try:
                Sample().load(
                    deposition["sampleId"], user=user, level=AccessType.READ, exc=True
                )
            except Exception:
                deposition["sampleId"] = None
        return deposition

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

    def validate(self, doc):
        try:
            self.schema_validator.validate(doc.get("metadata", {}))
        except jsonschema.ValidationError as e:
            raise ValidationException(f"Metadata validation failed: {e.message}") from e
        return doc

    @staticmethod
    def compute_identifier(metadata, root=True):
        return metadata.get("title", "")

    def fill_metadata(self, metadata, creator):
        if "types" not in metadata:
            metadata["types"] = {
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
                    "date": datetime.datetime.now(datetime.UTC).isoformat(),
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
                    "name": creator.get("lastName", "") + ", " + creator.get("firstName", ""),
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

        if batch > 0:
            igsn_indices = [f"{i+1:02d}" for i in range(batch)]
            if local_identifier := self.local_identifier(metadata):
                # If a local identifier is provided, use it for all indices
                local_indices = [f"{local_identifier}-{i+1:02d}" for i in range(batch)]
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

    def create_batch(self, main_deposition, indices):
        relatedIdentifier = {
            "relationType": "IsPartOf",
            "relatedIdentifier": main_deposition["igsn"],
            "relatedIdentifierType": "IGSN",
        }

        depositions = []
        for index in indices:
            metadata = copy.deepcopy(main_deposition["metadata"])
            metadata["relatedIdentifiers"].append(relatedIdentifier)
            titles = metadata.pop("titles")
            igsn_index, local_index = index
            logger.info(
                f"Creating deposition for {main_deposition['igsn']} with index {igsn_index} "
                f"and local index {local_index}"
            )
            deposition = {
                "access": main_deposition["access"],
                "created": main_deposition["created"],
                "creatorId": main_deposition["creatorId"],
                "igsn": f"{main_deposition['igsn']}-{igsn_index}",
                "metadata": {
                    "titles": [{"title": f"{titles[0]['title']} - {igsn_index}"}],
                    **metadata.copy(),
                },
                "parentId": main_deposition["_id"],
                "public": main_deposition.get("public"),
                "publicFlags": main_deposition.get("publicFlags", []),
                "sampleId": None,
                "state": "draft",
                "submitted": False,
                "updated": main_deposition["updated"],
                "track": main_deposition["track"],
            }
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
            samples = [
                {
                    "access": main_sample["access"],
                    "created": main_sample["created"],
                    "creator": main_sample["creator"],
                    "description": main_sample["description"],
                    "eventTypes": main_sample["eventTypes"],
                    "events": [],
                    "name": f"{main_deposition['igsn']}-{igsn_index}",
                    "updated": main_sample["updated"],
                }
                for igsn_index, _ in indices
            ]
            sample_result = Sample().collection.insert_many(samples)
            for deposition, sample_id in zip(depositions, sample_result.inserted_ids):
                deposition["sampleId"] = sample_id

        return self.collection.insert_many(depositions)

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

        return self.save(deposition)

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
