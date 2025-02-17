import datetime
import string

from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.model_base import AccessControlledModel, Model
from girder.models.setting import Setting

from ..settings import PluginSettings


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
        if submaterial not in materials[material]["subcategories"].keys():
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
                "title",
                "updated",
            ),
        )

    def validate(self, doc):
        return doc

    @staticmethod
    def compute_identifier(metadata, root=True):
        return metadata.get("title", "")

    def create(
        self,
        metadata,
        creator,
        governor=None,
        governor_lab="X",
        material=None,
        material_subtype="X",
        parentId=None,
    ):
        if not governor or len(governor) != 2:
            raise ValidationException(f"Invalid {governor=}")
        if not material or len(material) != 2:
            raise ValidationException(f"Invalid {material=}")
        try:
            parent_deposition = self.load(parentId, user=creator, level=AccessType.WRITE, exc=True)
        except ValidationException:
            parent_deposition = {"_id": None}
        except Exception:
            raise

        now = datetime.datetime.utcnow()
        metadata = metadata or {}

        prefix = f"{governor}{governor_lab}{material}{material_subtype}"
        igsn = PrefixCounter().get_next(prefix)

        deposition = {
            "created": now,
            "creatorId": creator["_id"],
            "igsn": igsn,
            "metadata": metadata,
            "parentId": parent_deposition["_id"],
            "state": "draft",
            "submitted": False,
            "title": metadata.get("title", ""),
            "updated": now,
        }

        return self.save(deposition)

    def update(self, deposition, metadata):
        deposition["metadata"] = metadata
        deposition["title"] = metadata.get("title", "")
        deposition["updated"] = datetime.datetime.utcnow()

        return self.save(deposition)
