#!/usr/bin/env python3
"""SOS-01 SCXML lint runner.

Invocation:

    python tools/scxml-lint/main.py <scxml-file>

Exit codes (per SOS-01 §7.2):
    0  — no ``error``-severity findings (warnings / info MAY be present)
    1  — one or more ``error``-severity findings
    2  — invocation / IO error (e.g. file not found, lxml missing)

Output format: GitHub Actions workflow annotations on stdout, one per
finding (per SOS-01 §7.5). Errors render as ``::error file=...,line=N::``,
warnings as ``::warning ...``, info as ``::notice ...``.

Implemented rules at this commit (all 18 SOS-01 §6 rules):

* SCXML-LINT-001 — W3C XSD validation                (rules/schema.py)
* SCXML-LINT-002 — root <scxml> element attributes   (rules/rule_002_structure.py)
* SCXML-LINT-003 — single top-level <datamodel>      (rules/rule_003_datamodel_count.py)
* SCXML-LINT-004 — no nested <parallel>              (rules/rule_004_no_nested_parallel.py)
* SCXML-LINT-005 — script block <= 40 LOC            (rules/script_length.py)
* SCXML-LINT-006 — <onentry>/<onexit> <= 5 LOC       (rules/rule_006_onentry_size.py)
* SCXML-LINT-007 — no non-deterministic primitives   (rules/rule_007_determinism.py)
* SCXML-LINT-008 — no async / Promise / generators   (rules/rule_008_async.py)
* SCXML-LINT-009 — ECMAScript permitted subset       (rules/ecmascript_subset.py)
* SCXML-LINT-010 — event-data comment per transition (rules/comment_density.py)
* SCXML-LINT-011 — unguarded transitions documented  (rules/rule_011_unguarded_documented.py)
* SCXML-LINT-012 — side-effect-free <cond>           (rules/rule_012_cond_pure.py)
* SCXML-LINT-013 — event names from ExternalEventName(rules/event_vocabulary.py)
* SCXML-LINT-014 — target ids from StateId           (rules/event_vocabulary.py)
* SCXML-LINT-015 — state intent comments             (rules/comment_density.py)
* SCXML-LINT-016 — helper-function comments          (rules/rule_016_helper_comments.py)
* SCXML-LINT-017 — REFERENCE.md syscall coverage     (rules/reference_md_drift.py)
* SCXML-LINT-018 — REFERENCE.md task-state mirror    (rules/reference_md_drift.py)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

try:
    from lxml import etree
except ImportError as exc:  # pragma: no cover - environment-dependent.
    sys.stderr.write(
        "scxml-lint: lxml is required; install via `pip install -r "
        f"tools/scxml-lint/requirements.txt`. ({exc})\n"
    )
    sys.exit(2)

from rules._common import SEVERITY_ERROR, Finding
from rules import (
    comment_density,
    ecmascript_subset,
    event_vocabulary,
    reference_md_drift,
    rule_002_structure,
    rule_003_datamodel_count,
    rule_004_no_nested_parallel,
    rule_006_onentry_size,
    rule_007_determinism,
    rule_008_async,
    rule_011_unguarded_documented,
    rule_012_cond_pure,
    rule_016_helper_comments,
    schema,
    script_length,
)

# Path to the vendored W3C SCXML 1.0 XSD relative to the SOS subrepo root.
VENDORED_XSD = Path("docs/specs/scxml.xsd")

# Path to REFERENCE.md relative to the SOS subrepo root.
REFERENCE_MD = Path("docs/REFERENCE.md")


# ---------------------------------------------------------------------------
# Rule registry. All 18 SOS-01 §6 rules are implemented. Amendment 003
# (2026-05-19) landed the remaining 9 rules (-002, -003, -004, -006, -007,
# -008, -011, -012, -016) on top of Amendment 002's scaffold.
# ---------------------------------------------------------------------------


def run(scxml_path: Path, repo_root: Path) -> List[Finding]:
    """Run every implemented rule against ``scxml_path``.

    ``repo_root`` resolves the vendored XSD + REFERENCE.md paths.
    Returns the union of all findings in source-line order.
    """
    findings: List[Finding] = []

    xsd_path = (repo_root / VENDORED_XSD).resolve()
    reference_md_path = (repo_root / REFERENCE_MD).resolve()

    findings.extend(schema.check(scxml_path, xsd_path))

    try:
        tree = etree.parse(str(scxml_path))
    except (etree.XMLSyntaxError, OSError) as exc:
        # Strict parse failed (e.g. ``--`` inside an XML comment). Schema
        # rule already reported the issue; fall back to a recovering parser
        # so the rest of the §6 rules can still run against the document.
        try:
            recovery_parser = etree.XMLParser(recover=True)
            tree = etree.parse(str(scxml_path), recovery_parser)
        except (etree.XMLSyntaxError, OSError):
            sys.stderr.write(f"scxml-lint: parse failure prevents further checks: {exc}\n")
            return findings

    findings.extend(rule_002_structure.check(tree, scxml_path))
    findings.extend(rule_003_datamodel_count.check(tree, scxml_path))
    findings.extend(rule_004_no_nested_parallel.check(tree, scxml_path))
    findings.extend(script_length.check(tree, scxml_path))
    findings.extend(rule_006_onentry_size.check(tree, scxml_path))
    findings.extend(rule_007_determinism.check(tree, scxml_path))
    findings.extend(rule_008_async.check(tree, scxml_path))
    findings.extend(ecmascript_subset.check(tree, scxml_path))
    findings.extend(comment_density.check(tree, scxml_path))
    findings.extend(rule_011_unguarded_documented.check(tree, scxml_path))
    findings.extend(rule_012_cond_pure.check(tree, scxml_path))
    findings.extend(event_vocabulary.check(tree, scxml_path))
    findings.extend(rule_016_helper_comments.check(tree, scxml_path))
    findings.extend(
        reference_md_drift.check(
            scxml_path,
            reference_md_path if reference_md_path.exists() else None,
        )
    )

    findings.sort(key=lambda f: (f.path, f.line, f.rule_id))
    return findings


def main(argv: List[str]) -> int:
    """Entry point. ``argv`` is ``sys.argv[1:]``."""
    if len(argv) != 1:
        sys.stderr.write("usage: scxml-lint <scxml-file>\n")
        return 2

    scxml_path = Path(argv[0]).resolve()
    if not scxml_path.exists():
        sys.stderr.write(f"scxml-lint: {scxml_path} not found\n")
        return 2

    # The subrepo root is two levels above this script
    # (tools/scxml-lint/main.py → tools → repo root).
    repo_root = Path(__file__).resolve().parent.parent.parent

    findings = run(scxml_path, repo_root)
    for f in findings:
        print(f.as_github_annotation())

    has_error = any(f.severity == SEVERITY_ERROR for f in findings)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
