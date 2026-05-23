"""Unit tests for SCXML-LINT-C-2 (guard-condition combinational depth budget).

Per ``docs/concepts/SOS-08-C-CONCEPTS.md`` §5.3 + §15 2026-05-23
PCDN-SOS-08-C-004 resolution: reject any ``<transition cond="...">``
whose combinational depth exceeds the configured budget (default 8).

The rule's depth semantics treat each binary ``and``/``or`` token in
the chart-author source as one chained operator (N-ary BoolOp(n) → n-1
chain contribution). Boundary conditions therefore line up with
"number of conjuncts" rather than with Python's flattened-AST depth.
See the rule module's "Depth definition" docstring section.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from _support import parse, wrap
from rules import scxml_lint_c_2


def _clear_budget_env():
    """Remove the budget env var so tests start from a known default."""
    os.environ.pop(scxml_lint_c_2._BUDGET_ENV_VAR, None)


class TestScxmlLintC2(unittest.TestCase):
    """SCXML-LINT-C-2 — guard-condition combinational depth budget."""

    def setUp(self):
        # Ensure each test starts from the documented default (8) unless
        # the test sets its own budget. The env-var read happens inside
        # ``check()``, so this is the only synchronization point needed.
        _clear_budget_env()

    def tearDown(self):
        _clear_budget_env()

    def test_clean_chart_no_findings(self):
        """A chart with no ``cond``-bearing transitions produces nothing."""
        body = (
            '<state id="boot">'
            '<transition event="ready" target="running"/>'
            '</state>'
            '<state id="running"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_simple_compare_depth_one_passes(self):
        """``a == 1`` is depth 1 (one Compare) — well within budget."""
        body = (
            '<state id="branch">'
            '<transition cond="a == 1" target="hit"/>'
            '</state>'
            '<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_eight_conjuncts_at_boundary_passes(self):
        """8 conjuncts → depth 8 (7 ``and``s + 1 ``Compare``) — at budget."""
        cond = " and ".join(f"v{i} == {i}" for i in range(8))
        body = (
            f'<state id="branch">'
            f'<transition cond="{cond}" target="hit"/>'
            f'</state>'
            f'<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        # depth == budget passes (rule rejects depth > budget).
        self.assertEqual(findings, [])

    def test_nine_conjuncts_over_budget_fails(self):
        """9 conjuncts → depth 9 (8 ``and``s + 1 ``Compare``) — exceeds 8."""
        cond = " and ".join(f"v{i} == {i}" for i in range(9))
        body = (
            f'<state id="branch">'
            f'<transition cond="{cond}" target="hit"/>'
            f'</state>'
            f'<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.rule_id, "SCXML-LINT-C-2")
        self.assertEqual(f.severity, "error")
        # Chart-vocabulary contents.
        self.assertIn("branch", f.message)
        self.assertIn("hit", f.message)
        # Measured depth and budget surface in the message.
        self.assertIn("9", f.message)
        self.assertIn("8", f.message)
        self.assertIn("SOS-08-C", f.message)
        self.assertIn("PCDN-C-004", f.message)

    def test_env_var_budget_tightens_threshold(self):
        """Setting the budget env-var to 4 makes a depth-5 guard fail."""
        os.environ[scxml_lint_c_2._BUDGET_ENV_VAR] = "4"
        # depth = 5 → 4 ``and``s + 1 Compare. 5 conjuncts.
        cond = " and ".join(f"v{i} == {i}" for i in range(5))
        body = (
            f'<state id="branch">'
            f'<transition cond="{cond}" target="hit"/>'
            f'</state>'
            f'<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "error")
        # Budget value surfaces in the message.
        self.assertIn("4", findings[0].message)

    def test_env_var_budget_relaxes_threshold(self):
        """Setting budget to 16 makes a 12-conjunct guard pass."""
        os.environ[scxml_lint_c_2._BUDGET_ENV_VAR] = "16"
        cond = " and ".join(f"v{i} == {i}" for i in range(12))
        body = (
            f'<state id="branch">'
            f'<transition cond="{cond}" target="hit"/>'
            f'</state>'
            f'<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_malformed_budget_env_falls_back_to_default(self):
        """A non-integer budget env-var degrades to the default of 8."""
        os.environ[scxml_lint_c_2._BUDGET_ENV_VAR] = "not-a-number"
        # 9 conjuncts → depth 9 → exceeds the *default* of 8.
        cond = " and ".join(f"v{i} == {i}" for i in range(9))
        body = (
            f'<state id="branch">'
            f'<transition cond="{cond}" target="hit"/>'
            f'</state>'
            f'<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        self.assertIn("8", findings[0].message)

    def test_unparseable_guard_is_skipped(self):
        """An unparseable ``cond`` is left to other rules (no C-2 finding)."""
        body = (
            '<state id="branch">'
            # Trailing `and` with no rhs — syntactically invalid.
            '<transition cond="a and" target="hit"/>'
            '</state>'
            '<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_unary_not_chain_depth(self):
        """A chain of ``not`` operators counts each as one depth level."""
        os.environ[scxml_lint_c_2._BUDGET_ENV_VAR] = "3"
        # `not not not not a` → 4 UnaryOp + 0 leaf = 4 → exceeds 3.
        body = (
            '<state id="branch">'
            '<transition cond="not not not not a" target="hit"/>'
            '</state>'
            '<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)

    def test_mixed_binop_compare_bool_depth(self):
        """``(a + b) == 1 and c == 2`` → 1 ``and`` + 1 Compare + 1 BinOp = 3.

        At default budget 8 this passes.
        """
        body = (
            '<state id="branch">'
            '<transition cond="(a + b) == 1 and c == 2" target="hit"/>'
            '</state>'
            '<state id="hit"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_2.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
