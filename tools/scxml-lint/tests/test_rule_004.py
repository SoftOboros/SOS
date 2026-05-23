"""Unit tests for SCXML-LINT-004 (no nested <parallel>)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_004_no_nested_parallel


class TestRule004(unittest.TestCase):
    """SCXML-LINT-004 — at most one <parallel>, never nested."""

    def test_violation_nested_parallel(self):
        """A <parallel> inside another <parallel> fires."""
        body = (
            '<parallel id="outer">'
            '<parallel id="inner">'
            '<state id="a"/><state id="b"/>'
            '</parallel>'
            '</parallel>'
        )
        tree = parse(wrap(body))
        findings = rule_004_no_nested_parallel.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "SCXML-LINT-004")
        self.assertIn("inner", findings[0].message)

    def test_no_violation_single_parallel(self):
        """One top-level <parallel> with state siblings passes."""
        body = '<parallel id="running"><state id="a"/><state id="b"/></parallel>'
        tree = parse(wrap(body))
        findings = rule_004_no_nested_parallel.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
