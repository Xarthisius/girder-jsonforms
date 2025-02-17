import re

from girder.exceptions import ValidationException
from girder.utility import setting_utilities

INST_CODE = re.compile(r"^[A-Z]{2}$")


class PluginSettings:
    IGSN_INSTITUTIONS = "jsonforms.igsn_institutions"
    IGSN_MATERIALS = "jsonforms.igsn_materials"
    GOOGLE_DRIVE_ENABLED = "jsonforms.google_drive_enabled"


@setting_utilities.default(PluginSettings.IGSN_INSTITUTIONS)
def default_igsn_institutions():
    return {
        "JH": {
            "code": "JH",
            "name": "Johns Hopkins University",
            "labs": ["Hopkins Extreme Materials Institute", "Some other lab"],
        },
        "TM": {
            "code": "TM",
            "name": "Texas A&M University",
            "labs": ["MESAM", "Some other lab"],
        },
        "SB": {
            "code": "SB",
            "name": "University of California, Santa Barbara",
            "labs": [],
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
                "B": "commercially puremetals",
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
    if not isinstance(doc, dict):
        raise ValidationException("Institutions must be a JSON object.")
    for inst, inst_data in doc.items():
        if not INST_CODE.match(inst):
            raise ValidationException("Institutions must have a 2-letter code.")
        if not isinstance(inst_data, dict):
            raise ValidationException(f"Institution {inst} must be a JSON object.")
        if "name" not in inst_data or not isinstance(inst_data["name"], str):
            raise ValidationException(f"Institution {inst} must have a name.")
        if "labs" not in inst_data or not isinstance(inst_data["labs"], list):
            raise ValidationException(f"Institution {inst} must have labs.")
        if len(inst_data["labs"]) > 23:
            raise ValidationException(
                f"Institution {inst} has too many labs. (Max is 23)"
            )


@setting_utilities.validator(PluginSettings.IGSN_MATERIALS)
def validate_igsn_materials(doc):
    if not isinstance(doc, dict):
        raise ValidationException("Materials must be a JSON object.")
    for mat, mat_data in doc.items():
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
