import itertools
import logging

logger = logging.getLogger(__name__)


def batch_indices_weihs(main_deposition, form_data):
    if not form_data.get("igsn"):
        """
        If no igsn is provided in form_data, return an empty list.
        This is a required field for generating indices.
        """
        logger.warning("No igsn provided in form_data for batch_indices_weihs.")
        return []
    if (
        not form_data["igsn"].get("substrates")
        or not form_data["igsn"].get("subRows")
        or not form_data["igsn"].get("subCols")
    ):
        # Return empty list if no substrates or subRows/Cols are provided
        return []

    igsn_indices = [
        "S{}R{}C{}".format(*row)
        for row in itertools.product(
            form_data["igsn"]["substrates"],
            range(1, int(form_data["igsn"]["subRows"]) + 1),
            range(1, int(form_data["igsn"]["subCols"]) + 1),
        )
    ]

    local_indices = [None] * len(igsn_indices)  # Placeholder for local indices

    return list(zip(igsn_indices, local_indices))


def batch_indices_imqcam(main_deposition, form_data):
    if not form_data.get("buildGeometries"):
        logger.warning(
            "No build geometries provided in form_data for batch_indices_imqcam."
        )
        # Return empty list if no substrates or subRows/Cols are provided
        return []

    local_indices = []

    prefix = (
        f"{form_data['userParameters']['runDate'].replace('-', '')}_"
        f"{form_data['userParameters']['location']}_"
        f"{form_data['buildPlate']['material']}"
    )
    suffix = (
        "_".join(form_data["extraInfo"])
        if "extraInfo" in form_data and form_data["extraInfo"]
        else ""
    )
    if suffix:
        suffix = f"_{suffix}"

    for geometry in form_data["buildGeometries"]:
        """
        geometry should be a dict with 'buildGeometry', 'count'
        """
        logger.info(f"Processing geometry: {geometry}")
        build_geometry = geometry.get("geometryType")
        if not build_geometry:
            continue
        count = int(geometry.get("count", 1))
        # Generate igsn indices for this geometry
        for i in range(count):
            local_indices.append(f"{prefix}_{build_geometry}_{i + 1:03d}{suffix}")

    return list(
        zip([f"{i:03d}" for i in range(1, len(local_indices) + 1)], local_indices)
    )
