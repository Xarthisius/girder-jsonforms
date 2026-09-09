import pathlib
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
    PROJECTS_ENABLED = "jsonforms.projects_enabled"
    PROJECTS_COLLECTION_NAME = "jsonforms.projects_collection_name"
    MAIN_PROJECT = "jsonforms.main_project"
    # Centralized IGSN registry. When IGSN_SERVICE_URL is empty this instance
    # allocates identifiers from its own PrefixCounter, exactly as it always
    # has; setting it switches allocation and DataCite publication to the
    # shared service. Never add either of these to the public settings list in
    # __init__.py:add_public_settings -- the token must not reach the browser.
    IGSN_SERVICE_URL = "jsonforms.igsn_service_url"
    IGSN_SERVICE_TOKEN = "jsonforms.igsn_service_token"
    # Which of girder-wholetale's two ORCID providers ("orcid" or
    # "orcid_sandbox") this plugin reads from and writes research resources to.
    # Both can be enabled for login at the same time, so the one this plugin
    # uses has to be named explicitly.
    ORCID_PROVIDER = "jsonforms.orcid_provider"
    # Whether accepting a project registers it as an ORCID research resource.
    # Off by default: the write needs the "/activities/update" scope, which
    # only SandboxORCID requests, so this is opt-in on instances configured
    # against the sandbox. Separate from ORCID_PROVIDER because the two do not
    # move together -- reads work against production, writes do not.
    ORCID_RESEARCH_RESOURCES = "jsonforms.orcid_research_resources"
    # Path to an image file embedded in proposal workflow email as a CID
    # attachment (the branded header logo). Empty means a text-only header.
    # An attachment rather than an <img src="https://..."> on purpose: the
    # mail client must not have to fetch anything from us to render the
    # message. Raster only -- see the validator.
    MAIL_LOGO = "jsonforms.mail_logo"


SettingDefault.defaults.update(
    {
        PluginSettings.PROJECTS_COLLECTION_NAME: "Projects",
        PluginSettings.MAIN_PROJECT: "aimdl",
        PluginSettings.PROJECTS_ENABLED: True,
        # Empty means "allocate locally", preserving existing behavior.
        PluginSettings.IGSN_SERVICE_URL: "",
        PluginSettings.IGSN_SERVICE_TOKEN: "",
        # Production ORCID. Reads (creator autocomplete) work against it as
        # they are; research-resource writes do not, and the scope gate keeps
        # them off until "/activities/update" is added to ORCID._AUTH_SCOPES.
        # Sandbox instances set this to "orcid_sandbox".
        PluginSettings.ORCID_PROVIDER: "orcid",
        PluginSettings.ORCID_RESEARCH_RESOURCES: False,
        PluginSettings.MAIL_LOGO: "",
    }
)


#: Logos shipped inside the package. MAIL_LOGO may name one of these directly
#: (a bare filename, no directory separator) instead of a filesystem path, so
#: a deployment can use one without mounting an image into the container.
MAIL_ASSET_DIR = pathlib.Path(__file__).resolve().parent / "mail_assets"

#: Image types the email logo may use, mapped to their MIME subtype. SVG is
#: deliberately absent: Gmail and Outlook do not render it at all, by CID or
#: any other transport, so allowing it here would silently produce a broken
#: logo for most recipients. Rasterize instead (rsvg-convert, inkscape).
MAIL_LOGO_TYPES = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
}


@setting_utilities.validator({PluginSettings.PROJECTS_ENABLED})
def validate_projects_enabled(doc):
    if not isinstance(doc["value"], bool):
        raise ValidationException(
            "Setting must be a boolean.",
            "value",
        )


@setting_utilities.validator(PluginSettings.ORCID_RESEARCH_RESOURCES)
def validate_orcid_research_resources(doc):
    if not isinstance(doc["value"], bool):
        raise ValidationException(
            "Setting must be a boolean.",
            "value",
        )


@setting_utilities.validator(PluginSettings.ORCID_PROVIDER)
def validate_orcid_provider(doc):
    # Imported here: girder_jsonforms.lib.orcid imports this module.
    from .lib.orcid import orcid_provider_names

    names = orcid_provider_names()
    if doc["value"] not in names:
        raise ValidationException(
            "ORCID provider must be one of {}.".format(", ".join(names)),
            "value",
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
        PluginSettings.IGSN_SERVICE_TOKEN,
    }
)
def validate_igsn_client(doc):
    if not isinstance(doc["value"], str):
        raise ValidationException(
            "Setting must be a string.",
            "value",
        )


@setting_utilities.validator(PluginSettings.IGSN_SERVICE_URL)
def validate_igsn_service_url(doc):
    value = doc["value"]
    if not isinstance(value, str):
        raise ValidationException("Setting must be a string.", "value")
    value = value.strip()
    if value and not value.startswith(("http://", "https://")):
        raise ValidationException(
            "IGSN service URL must start with http:// or https://", "value"
        )
    # Normalize so callers can concatenate paths without worrying about it.
    doc["value"] = value.rstrip("/")


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


@setting_utilities.validator(PluginSettings.MAIL_LOGO)
def validate_mail_logo(doc):
    value = doc["value"]
    if not isinstance(value, str):
        raise ValidationException("Setting must be a string.", "value")
    value = value.strip()
    if value:
        suffix = pathlib.PurePath(value).suffix.lower()
        if suffix not in MAIL_LOGO_TYPES:
            raise ValidationException(
                "Email logo must be one of {}; SVG is not rendered by Gmail "
                "or Outlook, so rasterize it first.".format(
                    ", ".join(sorted(MAIL_LOGO_TYPES))
                ),
                "value",
            )
        # A bare filename names a bundled asset, which ships with the package
        # and so can be checked right here -- a typo is a permanent silent
        # fallback to no logo otherwise. A path is left unchecked on purpose:
        # the setting is routinely configured before the file is mounted into
        # the container, and lib/mail.py logs and degrades if it is missing.
        if "/" not in value and not (MAIL_ASSET_DIR / value).is_file():
            available = sorted(
                path.name
                for path in MAIL_ASSET_DIR.glob("*")
                if path.suffix.lower() in MAIL_LOGO_TYPES
            )
            raise ValidationException(
                "No bundled email logo named {!r}. Available: {}. Pass an "
                "absolute path to use a file outside the package.".format(
                    value, ", ".join(available) or "none"
                ),
                "value",
            )
    doc["value"] = value
