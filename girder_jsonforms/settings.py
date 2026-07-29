import re

import jsonschema
from girder.exceptions import ValidationException
from girder.settings import SettingDefault
from girder.utility import setting_utilities

INST_CODE = re.compile(r"^[A-Z]{2}$")
COLLECTION_NAME = "IGSN Assets"
IGSN_REGEX = re.compile(r"^[A-Z]{6}[0-9]{5}[A-Z0-9\-]*$", re.IGNORECASE)


class PluginSettings:
    IGSN_INSTITUTIONS = "jsonforms.igsn_institutions"
    IGSN_MATERIALS = "jsonforms.igsn_materials"
    GOOGLE_DRIVE_ENABLED = "jsonforms.google_drive_enabled"
    IGSN_PUBLISHER = "jsonforms.igsn_publisher"
    IGSN_CLIENT_ID = "jsonforms.igsn_client_id"
    IGSN_PROVIDER_ID = "jsonforms.igsn_provider_id"
    IGSN_PREFIX = "jsonforms.igsn_prefix"
    AIMDL_COUNTS = "jsonforms.aimdl_counts"
    PROJECTS_COLLECTION_NAME = "jsonforms.projects_collection_name"
    MAIN_PROJECT = "jsonforms.main_project"


SettingDefault.defaults.update(
    {
        PluginSettings.PROJECTS_COLLECTION_NAME: "Projects",
        PluginSettings.MAIN_PROJECT: "aimdl",
    }
)


@setting_utilities.validator({PluginSettings.MAIN_PROJECT})
def validate_main_project(doc):
    if not isinstance(doc["value"], str):
        raise ValidationException(
            "Setting must be a string.",
            "value",
        )
    if doc["value"].lower() not in ["aimdl", "imqcam"]:
        raise ValidationException(
            "Project must be one of 'aimdl', or 'imqcam'", "value"
        )


@setting_utilities.validator(
    {
        PluginSettings.IGSN_CLIENT_ID,
        PluginSettings.IGSN_PROVIDER_ID,
        PluginSettings.IGSN_PREFIX,
        PluginSettings.PROJECTS_COLLECTION_NAME,
    }
)
def validate_igsn_client(doc):
    if not isinstance(doc["value"], str):
        raise ValidationException(
            "Setting must be a string.",
            "value",
        )


@setting_utilities.validator(PluginSettings.IGSN_PUBLISHER)
def validate_igsn_publisher(doc):
    schema = {
        "type": "object",
        "properties": {
            "lang": {"type": "string"},
            "name": {"type": "string"},
            "schemeUri": {"type": "string", "format": "uri"},
            "publisherIdentifier": {"type": "string"},
            "publisherIdentifierScheme": {"type": "string"},
        },
        "required": ["name"],
    }
    try:
        jsonschema.validate(instance=doc["value"], schema=schema)
    except jsonschema.ValidationError as e:
        raise ValidationException(f"Invalid publisher: {e.message}", "value")


@setting_utilities.default(PluginSettings.IGSN_PREFIX)
def default_igsn_prefix():
    """
    Default setting for IGSN prefix.
    """
    return "10.82581"  # HEMI IGSN  (10.83961 is HEMI IGSN test)


@setting_utilities.default(PluginSettings.IGSN_CLIENT_ID)
def default_igsn_client_id():
    """
    Default setting for IGSN client ID.
    """
    return "jhu.hemi-igsn"  # jhu.igsn-test for testing


@setting_utilities.default(PluginSettings.IGSN_PROVIDER_ID)
def default_igsn_provider_id():
    """
    Default setting for IGSN provider ID.
    """
    return "jhu"


@setting_utilities.default(PluginSettings.IGSN_PUBLISHER)
def default_igsn_publisher():
    """
    Default setting for IGSN publisher.
    """
    return {
        "lang": "en",
        "name": "Hopkins Extreme Materials Institute",
        "schemeUri": "https://ror.org/",
        "publisherIdentifier": "https://ror.org/02ed2th17",
        "publisherIdentifierScheme": "ROR",
    }


@setting_utilities.default(PluginSettings.IGSN_INSTITUTIONS)
def default_igsn_institutions():
    return {
        "AP": {
            "code": "AP",
            "name": "JHU Applied Physics Laboratory",
            "labs": {"L": "APL"},
        },
        "JH": {
            "code": "JH",
            "name": "Johns Hopkins University",
            "labs": {
                "A": "Hopkins Extreme Materials Institute",
                "B": "Weihs Group",
                "X": "Other",
            },
        },
        "TM": {
            "code": "TM",
            "name": "Texas A&M University",
            "labs": {"A": "MESAM", "X": "Other"},
        },
        "SB": {
            "code": "SB",
            "name": "University of California, Santa Barbara",
            "labs": {"X": "Other"},
        },
        "CM": {
            "code": "CM",
            "name": "Carnegie Mellon University",
            "labs": {"X": "Other"},
        },
        "NW": {
            "code": "NW",
            "name": "Northwestern University",
            "labs": {"X": "Other"},
        },
        "ML": {
            "code": "ML",
            "name": "University of Massachusetts, Lowell",
            "labs": {"X": "Other"},
        },
    }


@setting_utilities.default(PluginSettings.IGSN_MATERIALS)
def default_igsn_materials():
    return {
        "BO": {"name": "biological"},
        "BM": {"name": "biomaterials"},
        "CR": {
            "name": "ceramics",
            "subcategories": {
                "A": "carbides",
                "B": "cements",
                "C": "nitrides",
                "D": "oxides",
                "E": "perovskites",
                "F": "silicates",
            },
        },
        "MA": {
            "name": "metals and alloys",
            "subcategories": {
                "A": "Al-containing",
                "B": "commercially pure metals",
                "C": "Cu-containing",
                "D": "Fe-containing",
                "E": "intermetallics",
                "F": "Mg-containing",
                "G": "Ni-containing",
                "H": "rare earth",
                "I": "refractories",
                "J": "steels",
                "K": "superalloys",
                "L": "Ti-containing",
            },
        },
        "ME": {"name": "metamaterials"},
        "MO": {"name": "molecular fluids"},
        "OC": {
            "name": "organic compounds",
            "subcategories": {
                "A": "alcohols",
                "B": "aldehydes",
                "C": "alkanes",
                "D": "alkenes",
                "E": "alkynes",
                "F": "amines",
                "G": "carboxylic acids",
                "H": "cyclic compounds",
                "I": "cycloalkanes",
                "J": "esters",
                "K": "ketones",
                "L": "nitriles",
            },
        },
        "OG": {"name": "organometallics"},
        "PL": {
            "name": "polymers",
            "subcategories": {
                "A": "copolymers",
                "B": "elastomers",
                "C": "homopolymers",
                "D": "liquid crystals",
                "E": "polymer blends",
                "F": "rubbers",
                "G": "thermoplastics",
                "H": "thermosets",
            },
        },
        "SM": {
            "name": "semiconductors",
            "subcategories": {
                "A": "extrinsic",
                "B": "II-VI",
                "C": "III-V",
                "D": "intrinsic",
                "E": "n-type",
                "F": "p-type",
            },
        },
    }


@setting_utilities.validator(PluginSettings.IGSN_INSTITUTIONS)
def validate_igsn_institutions(doc):
    if not isinstance(doc["value"], dict):
        raise ValidationException("Institutions must be a JSON object.")
    for inst, inst_data in doc["value"].items():
        if not INST_CODE.match(inst):
            raise ValidationException("Institutions must have a 2-letter code.")
        if not isinstance(inst_data, dict):
            raise ValidationException(f"Institution {inst} must be a JSON object.")
        if "name" not in inst_data or not isinstance(inst_data["name"], str):
            raise ValidationException(f"Institution {inst} must have a name.")
        if "labs" not in inst_data or not isinstance(inst_data["labs"], dict):
            raise ValidationException(f"Institution {inst} must have labs.")


@setting_utilities.validator(PluginSettings.IGSN_MATERIALS)
def validate_igsn_materials(doc):
    if not isinstance(doc["value"], dict):
        raise ValidationException("Materials must be a JSON object.")
    for mat, mat_data in doc["value"].items():
        if not INST_CODE.match(mat):
            raise ValidationException("Materials must have a 2-letter code.")
        if not isinstance(mat_data, dict):
            raise ValidationException(f"Material {mat} must be a JSON object.")
        if "name" not in mat_data or not isinstance(mat_data["name"], str):
            raise ValidationException(f"Material {mat} must have a name.")
        if "subcategories" in mat_data:
            if not isinstance(mat_data["subcategories"], dict):
                raise ValidationException(
                    f"Material {mat} subcategories must be a JSON object."
                )
            for subcat, subcat_name in mat_data["subcategories"].items():
                if len(subcat) != 1 or not subcat.isalpha():
                    raise ValidationException(
                        f"Material {mat} subcategory {subcat} must be a single letter."
                    )
                if not isinstance(subcat_name, str):
                    raise ValidationException(
                        f"Material {mat} subcategory {subcat} must have a name."
                    )


@setting_utilities.default(PluginSettings.GOOGLE_DRIVE_ENABLED)
def default_google_drive_enabled():
    """
    Default setting for enabling Google Drive integration.
    """
    return False


@setting_utilities.default(PluginSettings.AIMDL_COUNTS)
def default_aimdl_counts():
    """
    Default setting for enabling AIMDL counts.
    """
    return False


@setting_utilities.validator(PluginSettings.GOOGLE_DRIVE_ENABLED)
def validate_google_drive_enabled(doc):
    """
    Validate the Google Drive integration setting.
    """
    if not isinstance(doc["value"], bool):
        raise ValidationException(
            "Google Drive integration must be a boolean.",
            "value",
        )


@setting_utilities.validator(PluginSettings.AIMDL_COUNTS)
def validate_aimdl_counts(doc):
    if not isinstance(doc["value"], bool):
        raise ValidationException(
            "AIMDL Counts must be a boolean.",
            "value",
        )
