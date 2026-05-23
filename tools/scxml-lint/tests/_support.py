"""Shared test fixtures for SOS-01 lint rule tests."""

from __future__ import annotations

import sys
from pathlib import Path

LINT_ROOT = Path(__file__).resolve().parent.parent
if str(LINT_ROOT) not in sys.path:
    sys.path.insert(0, str(LINT_ROOT))

from lxml import etree  # noqa: E402  (must follow path mutation)


def parse(xml_text: str):
    """Parse an SCXML fragment and return the lxml ``ElementTree``."""
    return etree.ElementTree(etree.fromstring(xml_text.encode("utf-8")))


SCXML_NS = 'xmlns="http://www.w3.org/2005/07/scxml"'


def wrap(body: str, root_attrs: str = "") -> str:
    """Wrap a fragment in a minimal canonical ``<scxml>`` root."""
    attrs = f'{SCXML_NS} version="1.0" datamodel="ecmascript" initial="boot"'
    if root_attrs:
        attrs = f"{attrs} {root_attrs}"
    return f'<?xml version="1.0"?>\n<scxml {attrs}>{body}</scxml>'
