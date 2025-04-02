import itertools


def batch_indices_weihs(main_deposition, form_data):
    if (
        not form_data.get("substrates")
        or not form_data.get("subRows")
        or not form_data.get("subCols")
    ):
        # Return empty list if no substrates or subRows/Cols are provided
        return []

    igsn_indices = [
        "S{}R{}C{}".format(*row)
        for row in itertools.product(
            form_data["substrates"],
            range(1, int(form_data["subRows"]) + 1),
            range(1, int(form_data["subCols"]) + 1),
        )
    ]

    local_indices = [None] * len(igsn_indices)  # Placeholder for local indices

    return list(zip(igsn_indices, local_indices))


def batch_indices_imqcam(main_deposition, form_data):
    if not form_data.get("buildGeometries"):
        # Return empty list if no substrates or subRows/Cols are provided
        return []

    local_indices = []

    for geometry in form_data["buildGeometries"]:
        """
        geometry should be a dict with 'buildGeometry', 'count'
        """
        build_geometry = geometry.get("buildGeometry")
        if not build_geometry:
            continue
        count = int(geometry.get("count", 1))
        # Generate igsn indices for this geometry
        for i in range(count):
            local_indices.append(f"{build_geometry}_{i + 1:03d}")

    return list(
        zip([f"{i:03d}" for i in range(1, len(local_indices) + 1)], local_indices)
    )
