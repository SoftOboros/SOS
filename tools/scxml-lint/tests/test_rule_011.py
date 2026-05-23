"""Unit tests for SCXML-LINT-011 (unguarded transitions documented)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_011_unguarded_documented


class TestRule011(unittest.TestCase):
    """SCXML-LINT-011 — unguarded transition needs guard-reasoning comment."""

    def test_violation_undocumented_unguarded(self):
        """An unguarded transition with body mutation but no comment fires."""
        body = (
            '<state id="boot">'
            '<transition event="task.create">'
            '<script>x = 1;</script>'
            '</transition>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = rule_011_unguarded_documented.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "SCXML-LINT-011")
        self.assertEqual(findings[0].severity, "warning")

    def test_no_violation_with_guard_comment(self):
        """An unguarded transition with an 'always processes' comment passes."""
        body = (
            '<state id="boot">'
            '<!-- always processes; bounds-check inside script -->'
            '<transition event="task.create">'
            '<script>x = 1;</script>'
            '</transition>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = rule_011_unguarded_documented.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_no_violation_with_cond(self):
        """A guarded transition is never flagged by -011."""
        body = (
            '<state id="boot">'
            '<transition event="task.create" cond="x == 0">'
            '<script>x = 1;</script>'
            '</transition>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = rule_011_unguarded_documented.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
