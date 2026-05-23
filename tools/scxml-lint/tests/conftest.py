"""Pytest config — add the lint-runner root to ``sys.path``.

The rule modules use the package layout ``rules.<module>``; tests import
``from rules import rule_NNN_xxx`` and need the lint-runner directory on
the path. This conftest is loaded by both ``pytest`` and (via
``unittest`` discovery) plain ``python -m unittest``.
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
LINT_ROOT = TESTS_DIR.parent
for p in (LINT_ROOT, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
