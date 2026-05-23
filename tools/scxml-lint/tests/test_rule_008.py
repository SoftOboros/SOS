"""Unit tests for SCXML-LINT-008 (no async/await/Promise/generators)."""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import rule_008_async


class TestRule008(unittest.TestCase):
    """SCXML-LINT-008 — no async-flow constructs inside <script>."""

    def test_violation_async(self):
        """An `async function` inside <script> fires."""
        body = (
            '<state id="boot"><onentry><script><![CDATA[\n'
            'async function f() { await g(); }\n'
            ']]></script></onentry></state>'
        )
        tree = parse(wrap(body))
        findings = rule_008_async.check(tree, Path("t.scxml"))
        labels = {f.message for f in findings}
        self.assertTrue(any("async" in m for m in labels))
        self.assertTrue(any("await" in m for m in labels))

    def test_no_violation_sync(self):
        """A synchronous function declaration passes clean."""
        body = (
            '<state id="boot"><onentry><script><![CDATA[\n'
            'function f(x) { return x + 1; }\n'
            ']]></script></onentry></state>'
        )
        tree = parse(wrap(body))
        findings = rule_008_async.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
