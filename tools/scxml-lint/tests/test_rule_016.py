"""Unit tests for SCXML-LINT-016 (helper-block function comments)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_016_helper_comments


class TestRule016(unittest.TestCase):
    """SCXML-LINT-016 — helper functions need leading '//' comments."""

    def test_violation_undocumented_helper(self):
        """A helper function without a leading // comment fires."""
        body = (
            '<script><![CDATA[\n'
            'function readyq_init() { return 0; }\n'
            ']]></script>'
        )
        tree = parse(wrap(body))
        findings = rule_016_helper_comments.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "SCXML-LINT-016")
        self.assertIn("readyq_init", findings[0].message)

    def test_no_violation_documented_helper(self):
        """A helper preceded by a '//' comment passes."""
        body = (
            '<script><![CDATA[\n'
            '// Initialize the ready queue list.\n'
            'function readyq_init() { return 0; }\n'
            ']]></script>'
        )
        tree = parse(wrap(body))
        findings = rule_016_helper_comments.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
