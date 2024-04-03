#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json

from girder import events
from girder.constants import AccessType
from girder.models.item import Item

from .rest.entry import FormEntry
from .rest.form import Form


def annotate_uploads(event):
    info = event.info
    if "reference" not in info:
        return

    try:
        reference = json.loads(info["reference"])
    except (ValueError, TypeError):
        return

    if "sampleId" in reference:
        parent = Item().load(
            info["file"]["itemId"], level=AccessType.WRITE, user=info["currentUser"]
        )
        reference.pop("file")
        Item().setMetadata(parent, reference)


def load(info):
    info["apiRoot"].form = Form()
    info["apiRoot"].entry = FormEntry()
    events.bind("data.process", "jsonforms", annotate_uploads)
