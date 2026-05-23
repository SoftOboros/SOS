"""Unit tests for SCXML-LINT-C-1 (document-order priority warning).

Per ``docs/concepts/SOS-08-C-CONCEPTS.md`` §5.2 + §15 2026-05-23
PCDN-SOS-08-C-006 resolution: warn when two transitions in the same
source state could simultaneously evaluate true. v1 scaffold flags the
unambiguous unguarded-pair sub-case; guarded-overlap detection is
wave-2+.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import scxml_lint_c_1


class TestScxmlLintC1(unittest.TestCase):
    """SCXML-LINT-C-1 — document-order priority warning."""

    def test_clean_chart_no_warnings(self):
        """A chart whose every state has ≤1 transition produces nothing."""
        body = (
            '<state id="boot">'
            '<transition event="ready" target="running"/>'
            '</state>'
            '<state id="running">'
            '<transition event="stop" target="boot"/>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_two_unguarded_eventless_transitions_warn(self):
        """Two eventless, unguarded transitions on one state fire one warning."""
        body = (
            '<state id="dispatch">'
            '<transition target="a"/>'
            '<transition target="b"/>'
            '</state>'
            '<state id="a"/>'
            '<state id="b"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.rule_id, "SCXML-LINT-C-1")
        self.assertEqual(f.severity, "warning")
        # Chart-vocabulary contents: state id + spec citation.
        self.assertIn("dispatch", f.message)
        self.assertIn("SOS-08-C", f.message)
        # Both transition shapes named.
        self.assertIn("'a'", f.message)
        self.assertIn("'b'", f.message)

    def test_two_unguarded_same_event_transitions_warn(self):
        """Two transitions on one state sharing an ``event`` value fire."""
        body = (
            '<state id="boot">'
            '<transition event="tick" target="a"/>'
            '<transition event="tick" target="b"/>'
            '</state>'
            '<state id="a"/>'
            '<state id="b"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.rule_id, "SCXML-LINT-C-1")
        self.assertEqual(f.severity, "warning")
        self.assertIn("boot", f.message)
        self.assertIn("tick", f.message)
        self.assertIn("SOS-08-C", f.message)

    def test_three_unguarded_transitions_warn_once(self):
        """Three unguarded transitions: one warning naming the first pair.

        Multiple-pair states surface one finding per state so chart
        authors see one diagnostic per offending state rather than
        N-choose-2 redundant warnings. Fixing the first pair re-runs
        the linter and surfaces the next.
        """
        body = (
            '<state id="dispatch">'
            '<transition target="a"/>'
            '<transition target="b"/>'
            '<transition target="c"/>'
            '</state>'
            '<state id="a"/>'
            '<state id="b"/>'
            '<state id="c"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        # First pair (i=0, j=1) named.
        self.assertIn("'a'", f.message)
        self.assertIn("'b'", f.message)

    def test_two_guarded_transitions_no_warning_v1(self):
        """Two transitions both carrying ``cond`` are NOT flagged at v1.

        Guard-condition overlap analysis is wave-2+; the v1 scaffold
        deliberately produces false negatives here in exchange for zero
        false positives within the unguarded sub-case.
        """
        body = (
            '<state id="branch">'
            '<transition cond="x &gt; 0" target="positive"/>'
            '<transition cond="x &lt; 0" target="negative"/>'
            '</state>'
            '<state id="positive"/>'
            '<state id="negative"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_guarded_plus_unguarded_no_warning(self):
        """A guarded + unguarded pair is NOT flagged.

        The unguarded transition acts as a default-fall-through; this
        is a well-formed SCXML pattern and document-order priority is
        the intended behaviour.
        """
        body = (
            '<state id="branch">'
            '<transition cond="x &gt; 0" target="positive"/>'
            '<transition target="default"/>'
            '</state>'
            '<state id="positive"/>'
            '<state id="default"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_different_event_names_no_warning(self):
        """Two unguarded transitions with different ``event`` names are fine."""
        body = (
            '<state id="boot">'
            '<transition event="ready" target="a"/>'
            '<transition event="error" target="b"/>'
            '</state>'
            '<state id="a"/>'
            '<state id="b"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_failure_message_contains_state_id_and_spec_cite(self):
        """Failure message names the state ID and cites SOS-08-C §5."""
        body = (
            '<state id="contested">'
            '<transition target="a"/>'
            '<transition target="b"/>'
            '</state>'
            '<state id="a"/>'
            '<state id="b"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        msg = findings[0].message
        self.assertIn("contested", msg)
        self.assertIn("SOS-08-C", msg)
        self.assertIn("§5", msg)

    def test_transitions_in_distinct_states_no_warning(self):
        """Two transitions in *different* states don't combine into a pair.

        Document-order priority is per-source-state; cross-state pairs
        don't form an overlap in the §5.2 sense.
        """
        body = (
            '<state id="a">'
            '<transition target="b"/>'
            '</state>'
            '<state id="b">'
            '<transition target="a"/>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_c_1.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
