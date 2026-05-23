"""Shared helpers for SCXML lint rule modules.

Provides the canonical ``Finding`` dataclass, severity constants, and
small AST-walking helpers reused by multiple rule modules. Keeping these
in one place prevents the per-rule modules from drifting on shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

# Lint severity constants (mirrors SOS-01 §5.2 ``LintRuleSeverity``).
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# SCXML namespace per W3C SCXML 1.0.
SCXML_NS = "http://www.w3.org/2005/07/scxml"
SCXML_NS_PREFIX = f"{{{SCXML_NS}}}"


@dataclass(frozen=True)
class Finding:
    """One lint finding produced by a rule module.

    Attributes:
        rule_id: The ``SCXML-LINT-NNN`` rule id.
        severity: One of :data:`SEVERITY_ERROR`, :data:`SEVERITY_WARNING`,
            :data:`SEVERITY_INFO`.
        message: Human-readable diagnostic.
        path: Path to the file the finding is anchored on (typically the
            scxml file, but cross-doc rules MAY anchor on REFERENCE.md).
        line: 1-based source line. Use ``1`` when no specific line applies.
    """

    rule_id: str
    severity: str
    message: str
    path: str
    line: int = 1

    def as_github_annotation(self) -> str:
        """Render as a GitHub Actions workflow annotation line."""
        sev = self.severity if self.severity != SEVERITY_INFO else "notice"
        return f"::{sev} file={self.path},line={self.line}::{self.rule_id} {self.message}"


def localname(tag) -> str:
    """Strip an ``{namespace}localname`` prefix and return the local name.

    Non-string tags (lxml ``Comment`` / ``ProcessingInstruction`` callables)
    yield the empty string so call sites can skip them safely.
    """
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def iter_elements(root, name: str) -> Iterator:
    """Yield descendant elements whose local name equals ``name``.

    Skips ``Comment`` and ``ProcessingInstruction`` nodes; only real
    elements are visited.
    """
    for el in root.iter():
        if not isinstance(getattr(el, "tag", None), str):
            continue
        if localname(el.tag) == name:
            yield el


def preceding_comment(el) -> Optional[str]:
    """Return the text of the comment immediately preceding ``el`` if any.

    Uses lxml's ``getprevious()`` so it works on the parsed tree. Returns
    ``None`` if the previous sibling is not an XML comment (i.e. ``el`` is
    not preceded by ``<!-- ... -->``).
    """
    prev = el.getprevious()
    while prev is not None and not _is_meaningful(prev):
        prev = prev.getprevious()
    if prev is not None and _is_comment(prev):
        return (prev.text or "").strip()
    return None


def _is_comment(el) -> bool:
    """Return True if ``el`` is an lxml comment node."""
    # lxml comments have callable .tag (Comment); regular elements have str tag.
    return callable(getattr(el, "tag", None))


def _is_meaningful(el) -> bool:
    """Return False for ProcessingInstruction nodes that aren't comments."""
    if _is_comment(el):
        return True
    # An element with a real string tag is meaningful too.
    return isinstance(getattr(el, "tag", None), str)


def cdata_lines(script_el) -> list[str]:
    """Return the lines of a ``<script>`` element's text body."""
    body = script_el.text or ""
    return body.splitlines()


def nonblank_noncomment_count(lines: Iterable[str]) -> int:
    """Return the count of lines that are neither blank nor pure comments.

    A line is "blank" if ``strip() == ""``. A line is a "pure comment" if
    it starts with ``//`` or is wrapped in ``/* ... */`` on the same line.
    Inline trailing comments do not reduce the count.
    """
    n = 0
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s.startswith("//"):
            continue
        if s.startswith("/*") and s.endswith("*/"):
            continue
        n += 1
    return n
