"""Unit tests for SCXML-LINT-002 (root element attributes)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse
from rules import rule_002_structure


_GOOD = (
    '<?xml version="1.0"?>\n'
    '<scxml xmlns="http://www.w3.org/2005/07/scxml" version="1.0" '
    'datamodel="ecmascript" initial="boot"><state id="boot"/></scxml>'
)
_BAD = (
    '<?xml version="1.0"?>\n'
    '<scxml xmlns="http://www.w3.org/2005/07/scxml" version="0.9" '
    'datamodel="null" initial="bogus"><state id="boot"/></scxml>'
)


class TestRule002(unittest.TestCase):
    """SCXML-LINT-002 — root element identity + attribute discipline."""

    def test_violation_triggers(self):
        """Bad version + datamodel + unknown initial all fire."""
        tree = parse(_BAD)
        findings = rule_002_structure.check(tree, Path("test.scxml"))
        self.assertGreaterEqual(len(findings), 3)
        rule_ids = {f.rule_id for f in findings}
        self.assertEqual(rule_ids, {"SCXML-LINT-002"})

    def test_no_violation(self):
        """Canonical root element produces no findings."""
        tree = parse(_GOOD)
        findings = rule_002_structure.check(tree, Path("test.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
