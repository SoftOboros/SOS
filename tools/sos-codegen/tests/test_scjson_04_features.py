"""Smoke tests for scjson 0.4.0 feature surface accessibility.

Authority: `docs/concepts/SOS-09-CONCEPTS.md` §16 (2026-05-26 entry
"scjson 0.4.0 feature surface: roadmap acknowledgment") and
`docs/concepts/SOS-ROADMAP-07-PLUS.md` §12 (per-feature roadmap entries).

Scope (per roadmap framing):
    These tests CONFIRM that the scjson feature surface is reachable
    from the same Python binding `tools/sos-codegen/loader.py` uses.
    They do NOT exercise semantic emission of any of these features into
    a SOS backend — that work is roadmap-tracked under §12.1..§12.6.

Covered features:
    1. help_text (CONV-F comment promotion)              — §12.1, §12.2
    2. XInclude preserve-mode (other_element survival)   — §12.3
    3. ``<send>`` attributes (event/delay/target/namelist) — §12.4
    4. ``<invoke>`` attributes + finalize child           — §12.5

Lenience: each assertion checks for *presence* of the semantic content
in the round-tripped JSON (via ``in str(json.dumps(...))`` style
substring checks). Exact JSON shape may vary across scjson minor
versions; presence is the contract we depend on. If the binding loaded
by the environment doesn't expose a given feature, the test SKIPs with
a clear reason rather than failing — this lets the suite stay green on
older bindings while the roadmap integration work catches up.

See `tools/sos-codegen/tests/fixtures/sos_10/orchestrator_with_comments_and_send.scxml`
for a richer roadmap fixture chart exercising all four features in one
chart (intentionally NOT a production-valid SOS-10 chart — it's a
corpus for these smoke tests).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ---------------------------------------------------------------------------
# Version + capability detection.
#
# scjson exposes its version via importlib.metadata (the package's installed
# distribution metadata). The 0.4.0 feature surface is gated on three module
# attribute checks because version strings are unreliable across pre-release
# / fork builds:
#
#   - comment_promotion + help_text round-trip → ``scjson.comment_promotion``
#   - XInclude preserve-mode                   → ``SCXMLDocumentHandler.xinclude``
#   - <send>/<invoke> first-class              → presence in xml_to_json output
#
# Each test guards on what it actually needs, not on a single version sentinel.
# ---------------------------------------------------------------------------


def _scjson_version() -> str:
    """Return the installed scjson distribution version, or 'unknown'."""
    try:
        import importlib.metadata

        return importlib.metadata.version("scjson")
    except Exception:
        return "unknown"


def _scjson_has_comment_promotion() -> bool:
    try:
        import scjson.comment_promotion  # noqa: F401

        return True
    except Exception:
        return False


def _scjson_has_xinclude_attr() -> bool:
    try:
        from scjson.SCXMLDocumentHandler import SCXMLDocumentHandler

        return hasattr(SCXMLDocumentHandler(), "xinclude")
    except Exception:
        return False


def _get_handler():
    """Return a fresh ``SCXMLDocumentHandler``, or skip the test."""
    try:
        from scjson.SCXMLDocumentHandler import SCXMLDocumentHandler

        return SCXMLDocumentHandler()
    except Exception as exc:  # pragma: no cover - import-time skip
        pytest.skip(f"scjson SCXMLDocumentHandler unavailable: {exc!r}")


# ---------------------------------------------------------------------------
# §12.1 / §12.2 — help_text field round-trips (CONV-F comment promotion).
# ---------------------------------------------------------------------------


def test_help_text_field_round_trips() -> None:
    """An XML comment before a state should attach as the state's help text.

    Per CONV-F (comment promotion), a comment immediately preceding an
    element attaches to that element. We assert presence of the comment
    body in the round-tripped JSON without committing to a particular
    shape (``help_text`` field, ``__comment__`` attribute, etc.).
    """
    if not _scjson_has_comment_promotion():
        pytest.skip(
            f"scjson {_scjson_version()} missing comment_promotion module; "
            "CONV-F help_text smoke test deferred (SOS-ROADMAP-07-PLUS §12.1)"
        )

    handler = _get_handler()
    xml = (
        '<?xml version="1.0"?>'
        '<scxml xmlns="http://www.w3.org/2005/07/scxml" '
        'version="1.0" initial="s1">'
        "  <!-- This is help text for s1 -->"
        '  <state id="s1"/>'
        "</scxml>"
    )
    result_json = handler.xml_to_json(xml)
    # Tolerate either a string return or a dict-then-dumps shape.
    if isinstance(result_json, str):
        rendered = result_json
    else:  # pragma: no cover - belt+braces
        rendered = json.dumps(result_json)

    assert "This is help text for s1" in rendered, (
        "expected comment body to survive round-trip via help_text/comment "
        f"promotion; got: {rendered[:400]!r}"
    )


# ---------------------------------------------------------------------------
# §12.3 — XInclude preserve-mode (xi:include survives in other_element).
# ---------------------------------------------------------------------------


def test_xinclude_preserve_round_trip() -> None:
    """``<xi:include>`` should survive into the JSON when ``xinclude='preserve'``.

    scjson stores foreign-namespace nodes under ``other_element`` (same
    shape the SOS-10 annotation parser walks — ``sos10_annotations.py``).
    We assert the include's href survives somewhere in the JSON.
    """
    if not _scjson_has_xinclude_attr():
        pytest.skip(
            f"scjson {_scjson_version()} missing XInclude attribute on "
            "SCXMLDocumentHandler; xi:include preserve-mode smoke test "
            "deferred (SOS-ROADMAP-07-PLUS §12.3)"
        )

    handler = _get_handler()

    # Create a self-contained include target in a temp file so the test
    # is reproducible. We don't need scjson to RESOLVE the include —
    # preserve mode is the default and is what we're testing.
    include_body = (
        '<state id="included_state" xmlns="http://www.w3.org/2005/07/scxml"/>'
    )
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".scxml", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(include_body)
        tmp.close()
        include_path = tmp.name

        # xi:include href references the temp file; preserve mode means
        # scjson should NOT inline-resolve it, but keep the directive.
        xml = (
            '<?xml version="1.0"?>'
            '<scxml xmlns="http://www.w3.org/2005/07/scxml" '
            'xmlns:xi="http://www.w3.org/2001/XInclude" '
            'version="1.0" initial="s1">'
            '  <state id="s1">'
            f'    <xi:include href="{include_path}"/>'
            "  </state>"
            "</scxml>"
        )

        # Ensure preserve mode is in effect (it's the default, per CLI help).
        if hasattr(handler, "xinclude"):
            handler.xinclude = "preserve"

        result_json = handler.xml_to_json(xml)
        rendered = (
            result_json if isinstance(result_json, str) else json.dumps(result_json)
        )

        # The include directive itself — by href — must survive. Don't
        # require a specific JSON shape (other_element vs ___element vs
        # nested attributes); just presence.
        assert "XInclude" in rendered or "xi:include" in rendered or "include" in rendered, (
            f"expected xi:include to survive in JSON; got: {rendered[:400]!r}"
        )
        assert os.path.basename(include_path) in rendered, (
            f"expected include href to survive; got: {rendered[:400]!r}"
        )
    finally:
        try:
            os.unlink(include_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# §12.4 — <send> element attributes survive round-trip.
# ---------------------------------------------------------------------------


def test_send_element_attributes_survive() -> None:
    """A ``<send>`` element's first-class attributes must round-trip.

    Per SCXML 1.0 §6.4 and roadmap §12.4, ``<send>`` carries event,
    delay, target, and namelist attributes that are first-class
    (not foreign-namespace soup). All four MUST survive the
    xml_to_json round-trip.
    """
    handler = _get_handler()
    xml = (
        '<?xml version="1.0"?>'
        '<scxml xmlns="http://www.w3.org/2005/07/scxml" '
        'version="1.0" initial="s1">'
        '  <state id="s1">'
        '    <transition event="go" target="s1">'
        '      <send event="my_event" delay="100ms" '
        'target="#_internal" namelist="foo bar"/>'
        "    </transition>"
        "  </state>"
        "</scxml>"
    )
    result_json = handler.xml_to_json(xml)
    rendered = (
        result_json if isinstance(result_json, str) else json.dumps(result_json)
    )

    # Each first-class attribute must appear somewhere in the JSON.
    for needle, label in [
        ("my_event", "<send event>"),
        ("100ms", "<send delay>"),
        ("#_internal", "<send target>"),
        ("foo bar", "<send namelist>"),
    ]:
        assert needle in rendered, (
            f"{label} attribute did not survive xml_to_json; "
            f"rendered: {rendered[:600]!r}"
        )


# ---------------------------------------------------------------------------
# §12.5 — <invoke> element attributes + <finalize> child survive.
# ---------------------------------------------------------------------------


def test_invoke_element_attributes_survive() -> None:
    """An ``<invoke>`` element's attributes and ``<finalize>`` child must survive.

    Per SCXML 1.0 §6.5 and roadmap §12.5, ``<invoke>`` carries id, src,
    autoforward, and may contain a ``<finalize>`` block. All must
    survive the xml_to_json round-trip.
    """
    handler = _get_handler()
    xml = (
        '<?xml version="1.0"?>'
        '<scxml xmlns="http://www.w3.org/2005/07/scxml" '
        'version="1.0" initial="s1">'
        '  <state id="s1">'
        '    <invoke id="i1" src="some://uri" autoforward="true">'
        '      <finalize>'
        '        <log expr="\'finalized\'"/>'
        "      </finalize>"
        "    </invoke>"
        "  </state>"
        "</scxml>"
    )
    result_json = handler.xml_to_json(xml)
    rendered = (
        result_json if isinstance(result_json, str) else json.dumps(result_json)
    )

    # Attributes + finalize content must all survive.
    for needle, label in [
        ('"i1"', "<invoke id>"),
        ("some://uri", "<invoke src>"),
        ('"true"', "<invoke autoforward>"),
        ("finalize", "<finalize> child element"),
        ("finalized", "<log expr> body inside finalize"),
    ]:
        assert needle in rendered, (
            f"{label} did not survive xml_to_json; "
            f"rendered: {rendered[:600]!r}"
        )
