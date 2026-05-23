"""Unit tests for SCXML-LINT-007 (no non-deterministic primitives)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_007_determinism


class TestRule007(unittest.TestCase):
    """SCXML-LINT-007 — no Math.random / Date / console / eval / Function."""

    def test_violation_math_random(self):
        """A Math.random() call inside <script> fires."""
        body = (
            '<state id="boot"><onentry><script><![CDATA[\n'
            'if (Math.random() < 0.5) { x = 1; }\n'
            ']]></script></onentry></state>'
        )
        tree = parse(wrap(body))
        findings = rule_007_determinism.check(tree, Path("t.scxml"))
        self.assertTrue(any("Math.random" in f.message for f in findings))
        self.assertEqual(findings[0].rule_id, "SCXML-LINT-007")

    def test_no_violation_pure(self):
        """A pure body with arithmetic + comparisons passes clean."""
        body = (
            '<state id="boot"><onentry><script><![CDATA[\n'
            'var i = 0; if (i == 0) { i = i + 1; }\n'
            ']]></script></onentry></state>'
        )
        tree = parse(wrap(body))
        findings = rule_007_determinism.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
