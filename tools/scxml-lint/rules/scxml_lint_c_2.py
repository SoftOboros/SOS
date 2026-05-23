"""SCXML-LINT-C-2 — guard-condition combinational depth budget.

Per ``docs/concepts/SOS-08-C-CONCEPTS.md`` §5.3 (guard expression
compilation), §6.3 (Step 3 — guard compilation), and §15 2026-05-23
PCDN-SOS-08-C-004 resolution: the SOS chart validator MUST reject any
``<transition cond="...">`` whose combinational depth exceeds the
configured budget (default: 8 operators chained). Surfaces the
synthesis-tool routing-congestion cliff in chart vocabulary per
INV-S-HDL-5 instead of letting the failure first appear at HDL
place-and-route.

This rule lands as a SOS-01 §15 amendment co-landing with the SOS-08-C
implementation; it is purely additive to the §6 rule registry.

Depth definition
----------------
"Combinational depth" is the number of operator nodes along the
longest path from the AST root to any leaf of the guard expression.
The following AST node kinds count toward depth:

* ``BoolOp`` (``and`` / ``or``) — Python's ``ast`` flattens N-way
  ``and``/``or`` into a single ``BoolOp`` with N ``values``. SOS
  treats this as ``N - 1`` chained operators along the path through
  the deepest operand (i.e. one ``and`` token per gap between
  operands). This matches the chart-author's source-level intuition
  that ``a and b and c`` is a 2-deep chain even though Python parses
  it as one N-ary node, and matches the depth-7-for-8-conjuncts
  expectation from PCDN-C-004's worked examples.
* ``Compare`` (``==``, ``<``, ``>``, ``<=``, ``>=``, ``!=``, etc.) —
  one node = depth 1. Chained comparisons (``a < b < c``) collapse
  into a single ``Compare`` node and count as depth 1.
* ``BinOp`` (``+``, ``-``, ``*``, ``/``, ``%``, ``//``, ``<<``, ``>>``,
  ``&``, ``|``, ``^``) — each ``BinOp`` is depth 1.
* ``UnaryOp`` (``not``, ``-``, ``+``, ``~``) — each ``UnaryOp`` is
  depth 1.

Leaf nodes (``Name``, ``Constant``, ``Attribute``, ``Subscript``,
``Call``) contribute depth 0. ``Call`` contributes depth 0 itself but
the maximum-depth walk recurses into its arguments — a call whose
deepest argument has depth 5 yields depth 5 for the call site, not 6.

Worked examples
~~~~~~~~~~~~~~~

* ``a`` → depth 0 (bare ``Name``, no operators).
* ``a == 1`` → depth 1 (one ``Compare``).
* ``a + b`` → depth 1 (one ``BinOp``).
* ``a and b`` → depth 1 (N-ary ``BoolOp`` n=2 → 1 ``and``).
* ``a == 1 and b == 2`` → depth 2 (1 ``and`` + 1 ``Compare``).
* ``a == 1 and b == 2 and ... and h == 8`` (8 conjuncts) → depth 8
  (BoolOp n=8 → 7 ``and``s, +1 ``Compare`` on the deepest operand).
* ``a == 1 and b == 2 and ... and i == 9`` (9 conjuncts) → depth 9.
* ``(a == 1 and b == 2) and (c == 3 and d == 4)`` → Python flattens
  this at the outer level into one BoolOp n=4 → 3 ``and``s, +1
  ``Compare`` → depth 4.

Why N-ary ``BoolOp`` counts as ``N - 1`` rather than ``1``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The PCDN-C-004 §5.3 budget is phrased as "operators chained" — i.e.
counted in the chart author's source syntax, not in the parser's
post-flatten AST shape. A chart author who writes ``a and b and c``
sees two ``and``s in source; the lint must agree, or the budget value
loses any chart-side meaning. The synthesis-backend question (one
wide N-input AND gate vs. a chained reduction tree) is a port-side
implementation detail; the chart-side budget is a source-level
contract. We deliberately accept that this means the rule rejects a
syntactically wide N-ary boolean even though some synthesis backends
could route it as one gate — that's the conservative side of the
INV-S-HDL-5 chart-vocabulary trade-off.

Configuration
-------------
The budget is read from the ``SCXML_LINT_GUARD_DEPTH_BUDGET``
environment variable (default ``"8"``). The CLI surface in
``main.py`` exposes a ``--guard-depth-budget N`` flag that sets the
environment variable before invoking the rule, so all integration
points share a single source of truth for the budget value.

Severity
--------
``error``. Chart-compile is rejected. Surfaces the synthesis cliff in
chart vocabulary per INV-S-HDL-5.

Failure message
---------------
Chart vocabulary: cites the transition's source-state ID, the
``target`` attribute, the measured depth, the active budget, and the
reference "SOS-08-C §5 / PCDN-C-004 — guard-condition combinational-
depth budget".
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import List, Optional

from ._common import (
    SEVERITY_ERROR,
    Finding,
    iter_elements,
    localname,
)

RULE_ID = "SCXML-LINT-C-2"

# Default per SOS-08-C §5.3 / PCDN-C-004. Override via the
# SCXML_LINT_GUARD_DEPTH_BUDGET environment variable (set either
# directly or via main.py's ``--guard-depth-budget N`` flag).
DEFAULT_BUDGET = 8

# Environment-variable name the rule consults at every ``check()`` call.
# Reading at call time (not at module import) lets tests and the CLI
# flip the budget between invocations without re-importing the rule.
_BUDGET_ENV_VAR = "SCXML_LINT_GUARD_DEPTH_BUDGET"

# Citation appended to every chart-vocabulary error message.
_SPEC_CITE = (
    "SOS-08-C §5 / PCDN-C-004 — guard-condition combinational-depth budget"
)


def _resolve_budget() -> int:
    """Return the active depth budget by consulting the environment.

    Falls back to :data:`DEFAULT_BUDGET` on missing / unparseable env
    values. A malformed budget is treated as the default rather than
    raising, so a CLI typo never breaks lint outright.
    """
    raw = os.environ.get(_BUDGET_ENV_VAR)
    if raw is None:
        return DEFAULT_BUDGET
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_BUDGET
    if val < 0:
        return DEFAULT_BUDGET
    return val


# AST node kinds that count as one level of combinational depth each.
_DEPTH_CONTRIBUTING_NODES = (
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
)


def _ast_depth(node) -> int:
    """Return the maximum combinational depth of ``node``.

    See module docstring "Depth definition" for the rules. Leaf nodes
    contribute 0; depth-contributing operators contribute 1 plus the
    max depth of their relevant children; transparent nodes
    (``Expression`` wrapper, ``Call`` site, ``Attribute``,
    ``Subscript``, etc.) pass through to the deepest child.
    """
    if node is None:
        return 0

    # Top-level Expression wrapper — recurse into ``.body``.
    if isinstance(node, ast.Expression):
        return _ast_depth(node.body)

    # Depth-contributing operator nodes.
    if isinstance(node, ast.BoolOp):
        # N-ary boolean: counts as (N - 1) chained ``and``/``or``
        # operators along the deepest path. See module docstring
        # "Why N-ary BoolOp counts as N-1" for justification.
        operand_count = len(node.values)
        chain_contribution = max(operand_count - 1, 0)
        deepest_operand = max((_ast_depth(v) for v in node.values), default=0)
        return chain_contribution + deepest_operand
    if isinstance(node, ast.BinOp):
        return 1 + max(_ast_depth(node.left), _ast_depth(node.right))
    if isinstance(node, ast.UnaryOp):
        return 1 + _ast_depth(node.operand)
    if isinstance(node, ast.Compare):
        # Chained comparisons (``a < b < c``) collapse into one node
        # with ``left`` + N comparators; still depth 1 + max child.
        children = [node.left, *node.comparators]
        return 1 + max((_ast_depth(c) for c in children), default=0)

    # Transparent / leaf-ish nodes: recurse into all child AST nodes
    # via ast.iter_child_nodes; if no children, depth is 0.
    child_depths = [_ast_depth(c) for c in ast.iter_child_nodes(node)]
    if not child_depths:
        return 0
    return max(child_depths)


def _parse_cond(cond: str) -> Optional[ast.AST]:
    """Parse ``cond`` as a Python expression; return the AST or ``None``.

    SCXML datamodel="ecmascript" guards live in the SOS-01 §5.1 subset
    which maps cleanly to Python expression syntax for depth counting
    (the operator set is a subset; we are not evaluating, only
    structurally walking). A parse failure here means the guard is
    not valid ECMAScript-subset and rule_012 / ecmascript_subset will
    surface that; for C-2 we silently skip unparseable guards so we
    don't double-report a syntax error as a depth violation.
    """
    try:
        return ast.parse(cond, mode="eval")
    except SyntaxError:
        return None


def _enclosing_state_id(tr) -> Optional[str]:
    """Return the ``id`` of the transition's enclosing state."""
    cur = tr.getparent()
    while cur is not None:
        tag = getattr(cur, "tag", None)
        if isinstance(tag, str):
            name = localname(tag)
            if name in ("state", "parallel", "final"):
                sid = cur.get("id")
                if sid:
                    return sid
        cur = cur.getparent()
    return None


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk every ``<transition cond="...">``; reject over-budget guards.

    One finding per offending transition. A transition whose ``cond``
    is unparseable as a Python expression is silently skipped here so
    the syntax-related rules (rule_012, ecmascript_subset) own that
    diagnostic without duplication.
    """
    findings: List[Finding] = []
    root = tree.getroot()
    path_str = str(scxml_path)
    budget = _resolve_budget()

    for tr in iter_elements(root, "transition"):
        cond = tr.get("cond")
        if not cond:
            continue
        node = _parse_cond(cond)
        if node is None:
            # Unparseable guard — let rule_012 / ecmascript_subset
            # surface the syntax error; don't double-report.
            continue
        depth = _ast_depth(node)
        if depth <= budget:
            continue

        sid = _enclosing_state_id(tr) or "(unnamed)"
        target = tr.get("target") or "(internal)"
        findings.append(Finding(
            RULE_ID,
            SEVERITY_ERROR,
            (
                f"transition in state '{sid}' to target '{target}' has guard "
                f"of combinational depth {depth}, exceeding the configured "
                f"budget of {budget}. {_SPEC_CITE}."
            ),
            path_str,
            tr.sourceline or 1,
        ))

    return findings
