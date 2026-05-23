"""Unit tests for SCXML-LINT-H-1 (no preemption-related markup).

Per ``docs/concepts/SOS-08-H-CONCEPTS.md`` §5 + §15 2026-05-23
PCDN-SOS-08-H-001 resolution: hard-reject preemption-related attributes
and elements at chart-validation time.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from _support import parse, wrap
from rules import scxml_lint_h_1


class TestScxmlLintH1(unittest.TestCase):
    """SCXML-LINT-H-1 — hard-reject preemption markup."""

    def test_clean_chart_passes(self):
        """A chart with no preemption markup produces no findings."""
        body = (
            '<state id="boot">'
            '<transition event="ready" target="running"/>'
            '</state>'
            '<parallel id="running">'
            '<state id="a"/><state id="b"/>'
            '</parallel>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_h_1.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_preemptible_attribute_fires(self):
        """``preemptible="true"`` on a state fires with chart-vocabulary message
        naming the attribute and the enclosing state id."""
        body = (
            '<state id="boot"/>'
            '<state id="worker" preemptible="true">'
            '<transition event="go" target="boot"/>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_h_1.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.rule_id, "SCXML-LINT-H-1")
        self.assertEqual(f.severity, "error")
        # Chart-vocabulary: attribute name and state id appear in message.
        self.assertIn("preemptible", f.message)
        self.assertIn("worker", f.message)
        # Cites the spec, not an XPath / implementation string.
        self.assertIn("SOS-08-H", f.message)

    def test_sos_preempt_element_fires(self):
        """A ``<sos:preempt>`` custom element fires."""
        body = (
            '<state id="boot">'
            '<onentry xmlns:sos="urn:softoboros:sos:v1">'
            '<sos:preempt target="worker"/>'
            '</onentry>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_h_1.check(tree, Path("t.scxml"))
        self.assertGreaterEqual(len(findings), 1)
        # At least one finding names the element local-name "preempt".
        msgs = " ".join(f.message for f in findings)
        self.assertIn("preempt", msgs)
        self.assertIn("boot", msgs)
        self.assertIn("SOS-08-H", msgs)
        for f in findings:
            self.assertEqual(f.rule_id, "SCXML-LINT-H-1")
            self.assertEqual(f.severity, "error")

    def test_datamodel_variable_named_preempt_passes(self):
        """A user datamodel variable whose ``id`` contains "preempt" is fine.

        Per the spec, only structural markup (chart attributes, executable-
        content elements) carries preemption semantics; datamodel names are
        user-owned vocabulary.
        """
        body = (
            '<datamodel>'
            '<data id="preempt_count" expr="0"/>'
            '<data id="last_preempt" expr="null"/>'
            '</datamodel>'
            '<state id="boot"/>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_h_1.check(tree, Path("t.scxml"))
        self.assertEqual(findings, [])

    def test_priority_preempt_attribute_fires(self):
        """``priority-preempt`` on a transition fires."""
        body = (
            '<state id="boot">'
            '<transition event="irq" target="boot" priority-preempt="high"/>'
            '</state>'
        )
        tree = parse(wrap(body))
        findings = scxml_lint_h_1.check(tree, Path("t.scxml"))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.rule_id, "SCXML-LINT-H-1")
        self.assertEqual(f.severity, "error")
        self.assertIn("priority-preempt", f.message)
        self.assertIn("boot", f.message)
        self.assertIn("SOS-08-H", f.message)


if __name__ == "__main__":
    unittest.main()
