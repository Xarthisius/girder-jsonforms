#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .rest.form import Form
from .rest.entry import FormEntry


def load(info):
    info["apiRoot"].form = Form()
    info["apiRoot"].entry = FormEntry()
