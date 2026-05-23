"""Unit tests for SCXML-LINT-012 (side-effect-free <cond>)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_012_cond_pure


class TestRule012(unittest.TestCase):
    """SCXML-LINT-012 — cond MUST be pure datamodel reads, no calls."""

    def test_violation_function_call_in_cond(self):
        """A function-call in cond fires."""
        body = (
            '<state id="boot">'
            '<transition event="task.create" cond="pick_next() != -1"/>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = rule_012_cond_pure.check(tree, Path("t.scxml"))
        self.assertTrue(any("pick_next" in f.message for f in findings))
        self.assertEqual(findings[0].rule_id, "SCXML-LINT-012")
        self.assertEqual(findings[0].severity, "error")

    def test_violation_assignment_in_cond(self):
        """An assignment in cond fires."""
        body = (
            '<state id="boot">'
            '<transition event="task.create" cond="x = 1"/>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = rule_012_cond_pure.check(tree, Path("t.scxml"))
        self.assertTrue(any("assignment" in f.message for f in findings))

    def test_no_violation_pure_comparison(self):
        """A pure comparison passes clean."""
        body = (
            '<state id="boot">'
            '<transition event="task.create" cond="sched_lock == 0"/>'
            '<transition event="task.delay" cond="sched_lock &gt; 0"/>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = rule_012_cond_pure.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
