"""SCXML-LINT-001 — W3C SCXML 1.0 XSD schema validation.

The chart MUST validate against the vendored W3C SCXML 1.0 XSD at
``docs/specs/scxml.xsd``. Schema failure is a hard ``error`` per
SOS-01 §6.1 / INV-S-LINT-1.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from lxml import etree

from ._common import SEVERITY_ERROR, Finding

RULE_ID = "SCXML-LINT-001"


def check(scxml_path: Path, xsd_path: Path) -> List[Finding]:
    """Validate ``scxml_path`` against the W3C SCXML 1.0 XSD at ``xsd_path``.

    Returns a list of :class:`Finding` objects. Schema failures are
    surfaced individually so reviewers see every violation, not just the
    first one libxml2 reports.
    """
    findings: List[Finding] = []

    try:
        xsd_doc = etree.parse(str(xsd_path))
        schema = etree.XMLSchema(xsd_doc)
    except (etree.XMLSchemaParseError, OSError, etree.XMLSyntaxError) as exc:
        findings.append(
            Finding(
                rule_id=RULE_ID,
                severity=SEVERITY_ERROR,
                message=f"failed to load XSD at {xsd_path}: {exc}",
                path=str(xsd_path),
                line=1,
            )
        )
        return findings

    try:
        doc = etree.parse(str(scxml_path))
    except (etree.XMLSyntaxError, OSError) as exc:
        findings.append(
            Finding(
                rule_id=RULE_ID,
                severity=SEVERITY_ERROR,
                message=f"failed to parse SCXML: {exc}",
                path=str(scxml_path),
                line=getattr(exc, "lineno", 1) or 1,
            )
        )
        return findings

    if schema.validate(doc):
        return findings

    for err in schema.error_log:
        findings.append(
            Finding(
                rule_id=RULE_ID,
                severity=SEVERITY_ERROR,
                message=f"schema: {err.message}",
                path=str(scxml_path),
                line=err.line or 1,
            )
        )
    return findings
