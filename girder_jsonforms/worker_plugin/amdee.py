import collections
import json
import logging
import xml.etree.ElementTree as ET
from io import BytesIO

import numpy as np
import pandas as pd
from girder.constants import AccessType
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.upload import Upload
from girder.utility.progress import ProgressContext
from girder_jobs.constants import JobStatus
from girder_jobs.models.job import Job
from girder_worker.app import app

from ..models.entry import FormEntry as Entry

logger = logging.getLogger(__name__)
vega_schema = json.dumps(
    {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "width": "container",
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "title": "Angle 2𝜃", "type": "quantitative"},
            "y": {"field": "y", "title": "Intensity", "type": "quantitative"},
        },
    }
)


@app.task(queue="local")
def run(user, form, deposition, folder, progress=False):
    job = Job().createJob(
        title="AmdEE Task", type="amdee_ingest", public=False, user=user
    )

    job = Job().updateJob(
        job, log="Starting to run AmdEE task\n", status=JobStatus.RUNNING
    )

    result = None
    try:
        print("Starting AmdEE task... (print)")
        with ProgressContext(progress, user=user, title="Ingesting AmdEE data") as ctx:
            result = _xrd_ingest(user, form, deposition, folder, ctx)
        Job().updateJob(job, log="Finished AmdEE task...\n", status=JobStatus.SUCCESS)
    except Exception as exc:
        print(f"Error during task execution: {exc} (print)")
        import traceback
        print(traceback.format_exc())
        Job().updateJob(
            job, log=f"\nError during task execution: {exc}", status=JobStatus.ERROR
        )
    return result


def _xrd_ingest(user, form, deposition, folder, progress):
    root_folder = Folder().load(form["folderId"], user=user, level=AccessType.WRITE)
    dest_folder = Folder().createFolder(
        root_folder,
        deposition["igsn"],
        parentType="folder",
        public=root_folder["public"],
        reuseExisting=True,
    )

    for path, file in Folder().fileList(folder, user=user, data=False):
        if not file["name"].endswith(".xrdml"):
            continue

        source_item = Item().load(file["itemId"], user=user, level=AccessType.WRITE)
        source_item = Item().move(source_item, dest_folder)
        # Process the XRDML file
        with File().open(file) as xml_file:
            if json_data := parse_xrdml_to_json(xml_file):
                entry = create_entry(form, deposition, user, json_data, file)
                # Get raw data as text file
                raw_buffer = raw_counts(json_data)
                size = raw_buffer.getbuffer().nbytes
                raw_buffer.seek(0)
                fname = f"{deposition['igsn']}_xrd.csv"
                fobj = Upload().uploadFromFile(
                    raw_buffer,
                    size,
                    fname,
                    parentType="folder",
                    parent=dest_folder,
                    user=user,
                    mimeType="application/csv",
                )
                parsed_item = Item().load(fobj["itemId"], force=True)

                Item().setMetadata(
                    parsed_item,
                    {
                        "igsn": deposition["igsn"],
                        "targetPath": deposition["igsn"],
                        "vega": vega_schema,
                        "entryId": str(entry["_id"]),
                    },
                )

                Item().setMetadata(
                    source_item,
                    {
                        "igsn": deposition["igsn"],
                        "targetPath": deposition["igsn"],
                        "entryId": str(entry["_id"]),
                    },
                )

                print(f"Processed {path}")
            else:
                print(f"Failed to process {path}")


def create_entry(form, deposition, user, data, file):
    metadata = data["xrdMeasurements"]["xrdMeasurement"]["usedWavelength"]
    doc = {
        "depositionId": str(deposition["_id"]),
        "assignedIGSN": deposition["igsn"],
        "kAlpha1": float(metadata["kAlpha1"]["#text"]),
        "kAlpha2": float(metadata["kAlpha2"]["#text"]),
        "kBeta": float(metadata["kBeta"]["#text"]),
        "ratioKAlpha2KAlpha1": float(metadata["ratioKAlpha2KAlpha1"]["#text"]),
        "upload": {"file": str(file["_id"]), "targetPath": ""},
    }
    return Entry().create_entry(form, doc, None, None, user)


def raw_counts(data):
    data_points = data["xrdMeasurements"]["xrdMeasurement"]["scan"]["dataPoints"]
    raw_data = np.array(data_points["counts"]["#text"].split(" "), dtype=np.int32)

    axes = {}
    for axis in data_points["positions"]:
        axis_name = axis["@attributes"]["axis"]
        axes[axis_name] = (
            float(axis["startPosition"]["#text"]),
            float(axis["endPosition"]["#text"]),
        )

    x_axis = np.linspace(axes["2Theta"][0], axes["2Theta"][1], len(raw_data))
    # write x_axis, raw_data to csv in memory
    csv_buffer = BytesIO()
    pd.DataFrame({"x_axis": x_axis, "raw_data": raw_data}).to_csv(
        csv_buffer, index=False
    )
    csv_buffer.seek(0)
    return csv_buffer


def xml_to_dict(element):
    """
    Recursively converts an XML element and its children into a dictionary.
    Handles attributes and text content.
    """
    # Use collections.defaultdict to handle multiple children with the same tag
    # by storing them in a list.
    d = collections.defaultdict(list)

    # Process attributes
    if element.attrib:
        d["@attributes"] = element.attrib

    # Process text content
    if element.text and element.text.strip():
        d["#text"] = element.text.strip()

    # Process child elements
    for child in element:
        # Recursively call xml_to_dict for each child
        child_dict = xml_to_dict(child)
        # Store child elements under their tag name
        tag = child.tag
        # remove {namespace} if present
        tag = tag.split("}")[-1]  # This removes the namespace if present
        d[tag].append(child_dict)

    # If a tag only has one child, unwrap it from the list for cleaner JSON
    for key, value in d.items():
        if isinstance(value, list) and len(value) == 1:
            d[key] = value[0]

    return d


def parse_xrdml_to_json(xml_file_object):
    """
    Parses an XRDML XML file and converts its content to a JSON string.

    Args:
        xml_file_object (object): The file object pointing to the XRDML XML file.

    Returns:
        str: A JSON string representing the XML data, or None if an error occurs.
    """
    try:
        # Parse the XML file
        tree = ET.parse(xml_file_object)
        root = tree.getroot()

        # Convert the root element to a dictionary
        # We wrap the root element's dictionry in another dictionary
        # with the root tag as the key, to match typical JSON output for XML.
        json_data = {root.tag.split("}")[-1]: xml_to_dict(root)}

        # Convert the dictionary to a JSON string with indentation for readability
        # return json.dumps(json_data, indent=4)
        return json_data

    except FileNotFoundError:
        print(f"Error: The file '{xml_file_object}' was not found.")
        return None
    except ET.ParseError as e:
        print(f"Error parsing XML file: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None
