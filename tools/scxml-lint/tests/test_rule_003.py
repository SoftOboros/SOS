"""Unit tests for SCXML-LINT-003 (single top-level <datamodel>)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_003_datamodel_count


class TestRule003(unittest.TestCase):
    """SCXML-LINT-003 — exactly one top-level <datamodel>, no nesting."""

    def test_violation_nested(self):
        """A nested <datamodel> inside <state> fires."""
        body = (
            '<datamodel><data id="x" expr="0"/></datamodel>'
            '<state id="boot">'
            '<datamodel><data id="y" expr="1"/></datamodel>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = rule_003_datamodel_count.check(tree, Path("t.scxml"))
        self.assertTrue(any("nested" in f.message for f in findings))

    def test_violation_zero(self):
        """Missing <datamodel> fires."""
        tree = parse(wrap('<state id="boot"/>'))
        findings = rule_003_datamodel_count.check(tree, Path("t.scxml"))
        self.assertTrue(any("no top-level" in f.message for f in findings))

    def test_no_violation(self):
        """Exactly one top-level <datamodel> passes clean."""
        body = '<datamodel><data id="x" expr="0"/></datamodel><state id="boot"/>'
        tree = parse(wrap(body))
        findings = rule_003_datamodel_count.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
