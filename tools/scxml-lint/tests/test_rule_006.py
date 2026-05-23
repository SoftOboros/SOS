"""Unit tests for SCXML-LINT-006 (<onentry>/<onexit> script ≤ 5 lines)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_006_onentry_size


class TestRule006(unittest.TestCase):
    """SCXML-LINT-006 — inline <onentry>/<onexit> scripts <= 5 LOC."""

    def test_violation_oversize_onentry(self):
        """An <onentry><script> of 8 lines fires the warning."""
        body = (
            '<state id="boot"><onentry><script><![CDATA[\n'
            'a();\nb();\nc();\nd();\ne();\nf();\ng();\nh();\n'
            ']]></script></onentry></state>'
        )
        tree = parse(wrap(body))
        findings = rule_006_onentry_size.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "SCXML-LINT-006")
        self.assertEqual(findings[0].severity, "warning")

    def test_no_violation_small_onentry(self):
        """An <onentry><script> of 3 lines passes clean."""
        body = (
            '<state id="boot"><onentry><script><![CDATA[\n'
            'a();\nb();\nc();\n'
            ']]></script></onentry></state>'
        )
        tree = parse(wrap(body))
        findings = rule_006_onentry_size.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
