"""Tests for SOS-13 `INV-S-CHART-N` invariants generator.

Per [SOS-13-CONCEPTS.md §8 + §8.1]
(../../../docs/concepts/SOS-13-CONCEPTS.md), the generator emits the
chart-derived invariant series into `invariants.rs` + `INVARIANTS.md`
plus a discharge registry mapping `<sos:discharged>` (§7.5) sites back
to the invariants they discharge. These tests pin:

  - the §7.5 frozen four-value `check` enumeration is enforced;
  - empty input → empty artifacts (still parseable);
  - one declared invariant → both files contain it;
  - one discharged invariant → registry maps the discharge to the
    invariant (prefix-match fallback) or to the explicit binding;
  - mixed status set round-trips through the generator;
  - markdown formatting follows the documented shape;
  - generated Rust is well-formed (balanced braces / quotes; no
    interior unescaped `"` in `&str` literals);
  - `cargo check` round-trip when cargo is on PATH (otherwise skipped
    cleanly).

INV-SOS-G is the cross-phase invariant this generator services — every
chart-derived invariant carries its originating chart path so SAFETY
comments can cite it later.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Local imports — mirror the sos-codegen flat-package layout used by
# tests/test_verified_strip.py.
TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from sos13_invariants import (  # noqa: E402
    BoundsAnalysisInput,
    CHECK_TO_VS_OPS,
    DischargeAnnotation,
    InvariantSpec,
    InvariantsArtifacts,
    RECOGNIZED_CHECKS,
    VALID_STATUSES,
    generate_invariants,
)


# -----------------------------------------------------------------
# Frozen-enum guards
# -----------------------------------------------------------------


def test_recognized_checks_matches_spec_v1_frozen_set() -> None:
    """SOS-13 §7.5 freezes the four `check` values."""
    assert RECOGNIZED_CHECKS == frozenset(
        {"bounds", "div-by-zero", "null", "overflow"}
    )


def test_check_to_vs_ops_keys_subset_of_recognized() -> None:
    """Every key in `CHECK_TO_VS_OPS` MUST be a recognized check."""
    assert set(CHECK_TO_VS_OPS.keys()) <= RECOGNIZED_CHECKS
    # `bounds` and `null` map to live VS-OPs (§7.1); the arithmetic
    # checks map to the empty tuple per §7.2.
    assert CHECK_TO_VS_OPS["bounds"] == ("VS-OP-1",)
    assert CHECK_TO_VS_OPS["null"] == ("VS-OP-2", "VS-OP-3")
    assert CHECK_TO_VS_OPS["div-by-zero"] == ()
    assert CHECK_TO_VS_OPS["overflow"] == ()


def test_valid_statuses_are_the_three_documented() -> None:
    assert VALID_STATUSES == frozenset({"derived", "declared", "discharged"})


def test_discharge_annotation_rejects_unknown_check() -> None:
    with pytest.raises(ValueError, match="frozen enumeration"):
        DischargeAnnotation(chart_state="any_state", check="oob")


def test_invariant_spec_rejects_invalid_status() -> None:
    with pytest.raises(ValueError, match="status must be one of"):
        InvariantSpec(
            text="boundedness OK",
            chart_site="boot.onentry",
            status="invented",
        )


def test_invariant_spec_rejects_empty_fields() -> None:
    with pytest.raises(ValueError, match="text MUST NOT be empty"):
        InvariantSpec(text="   ", chart_site="boot.onentry")
    with pytest.raises(ValueError, match="chart_site MUST NOT be empty"):
        InvariantSpec(text="boundedness OK", chart_site="")


# -----------------------------------------------------------------
# Empty-input case
# -----------------------------------------------------------------


def test_empty_input_produces_parseable_empty_artifacts() -> None:
    artifacts = generate_invariants(BoundsAnalysisInput(chart_id="empty"))
    assert isinstance(artifacts, InvariantsArtifacts)
    # Rust source contains no `INV_S_CHART_*` consts but still includes
    # the cite() function so downstream callers compile against a known
    # surface.
    assert "INV_S_CHART_" not in artifacts.rust_source
    assert "pub fn cite(id: &str) -> &'static str" in artifacts.rust_source
    # Markdown carries the "no invariants" sentinel.
    assert "_No chart-derived invariants for this build._" in artifacts.markdown
    # Registry is an empty dict, not None.
    assert artifacts.registry == {}


# -----------------------------------------------------------------
# Single-invariant cases
# -----------------------------------------------------------------


def _one_invariant_input() -> BoundsAnalysisInput:
    return BoundsAnalysisInput.from_lists(
        chart_id="rtos_kernel",
        invariants=[
            InvariantSpec(
                text="tid < MAX_TASKS at every script_* entry",
                chart_site="boot.onentry",
                status="derived",
                bound_evidence="tid bounded by ready-queue scan",
            )
        ],
    )


def test_single_declared_invariant_appears_in_both_files() -> None:
    artifacts = generate_invariants(_one_invariant_input())
    # Rust const + cite() dispatch.
    assert "pub const INV_S_CHART_1: &str = " in artifacts.rust_source
    assert "tid < MAX_TASKS" in artifacts.rust_source
    assert '"INV-S-CHART-1" => INV_S_CHART_1' in artifacts.rust_source
    # Markdown section.
    assert "## INV-S-CHART-1" in artifacts.markdown
    assert "tid < MAX_TASKS" in artifacts.markdown
    assert "`boot.onentry`" in artifacts.markdown
    assert "`derived`" in artifacts.markdown
    assert "tid bounded by ready-queue scan" in artifacts.markdown


def test_single_discharged_invariant_registers_correctly() -> None:
    """A `<sos:discharged check="bounds"/>` on `boot` should map to the
    sole invariant whose chart_site begins with `boot.`."""
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="rtos_kernel",
        invariants=[
            InvariantSpec(
                text="tid < MAX_TASKS at every script_* entry",
                chart_site="boot.onentry",
            )
        ],
        discharges=[
            DischargeAnnotation(chart_state="boot", check="bounds")
        ],
    )
    artifacts = generate_invariants(bounds)
    key = "boot:bounds"
    assert key in artifacts.registry
    assert artifacts.registry[key] == ["INV-S-CHART-1"]


def test_explicit_discharges_invariant_overrides_prefix_match() -> None:
    """An explicit `discharges_invariant` binding takes precedence over
    the chart-site-prefix fallback."""
    bounds = BoundsAnalysisInput.from_lists(
        invariants=[
            InvariantSpec(
                text="X", chart_site="alpha.onentry"
            ),
            InvariantSpec(
                text="Y", chart_site="beta.guard"
            ),
        ],
        discharges=[
            DischargeAnnotation(
                chart_state="alpha",
                check="null",
                discharges_invariant="INV-S-CHART-2",
            )
        ],
    )
    artifacts = generate_invariants(bounds)
    # Explicit binding to INV-S-CHART-2 — even though alpha's prefix
    # would otherwise pick INV-S-CHART-1.
    assert artifacts.registry == {"alpha:null": ["INV-S-CHART-2"]}


def test_discharge_without_matching_state_records_orphan() -> None:
    """A discharge whose chart_state matches no invariant still appears
    in the registry (with an empty invariant list) so reviewers can
    spot it."""
    bounds = BoundsAnalysisInput.from_lists(
        invariants=[
            InvariantSpec(text="X", chart_site="alpha.onentry")
        ],
        discharges=[
            DischargeAnnotation(chart_state="orphan_state", check="bounds")
        ],
    )
    artifacts = generate_invariants(bounds)
    assert "orphan_state:bounds" in artifacts.registry
    assert artifacts.registry["orphan_state:bounds"] == []


# -----------------------------------------------------------------
# Mixed-status / multi-row case
# -----------------------------------------------------------------


def _mixed_input() -> BoundsAnalysisInput:
    return BoundsAnalysisInput.from_lists(
        chart_id="rtos_kernel",
        invariants=[
            InvariantSpec(
                text="tid < MAX_TASKS",
                chart_site="boot.onentry",
                status="derived",
            ),
            InvariantSpec(
                text="ready[p] non-empty before pick_next",
                chart_site="sched_dispatch.guard",
                status="declared",
                bound_evidence="INV-S7 wait-queue ordering",
            ),
            InvariantSpec(
                text="TaskState ∈ {Ready,Running,Blocked} at dispatch",
                chart_site="sched_dispatch.onentry",
                status="discharged",
            ),
        ],
        discharges=[
            DischargeAnnotation(chart_state="boot", check="bounds"),
            DischargeAnnotation(chart_state="sched_dispatch", check="null"),
        ],
    )


def test_mixed_input_produces_three_consts_and_registry() -> None:
    artifacts = generate_invariants(_mixed_input())
    # All three constants emitted.
    for i in (1, 2, 3):
        assert f"INV_S_CHART_{i}" in artifacts.rust_source
        assert f"## INV-S-CHART-{i}" in artifacts.markdown
    # Registry contains both discharges, prefix-matched.
    assert artifacts.registry["boot:bounds"] == ["INV-S-CHART-1"]
    # sched_dispatch matches both INV-S-CHART-2 and INV-S-CHART-3 by
    # the prefix-fallback policy.
    assert artifacts.registry["sched_dispatch:null"] == [
        "INV-S-CHART-2",
        "INV-S-CHART-3",
    ]


def test_status_values_are_emitted_in_doc_comments_and_markdown() -> None:
    artifacts = generate_invariants(_mixed_input())
    assert "status: derived" in artifacts.rust_source
    assert "status: declared" in artifacts.rust_source
    assert "status: discharged" in artifacts.rust_source
    # Markdown lists each status in backticks.
    for status in ("derived", "declared", "discharged"):
        assert f"`{status}`" in artifacts.markdown


# -----------------------------------------------------------------
# Markdown formatting checks
# -----------------------------------------------------------------


def test_markdown_starts_with_title_heading() -> None:
    artifacts = generate_invariants(_mixed_input())
    first = artifacts.markdown.splitlines()[0]
    assert first.startswith("# "), f"expected title `# ...`, got {first!r}"
    assert "INV-S-CHART-N" in first


def test_markdown_invariant_count_matches_input() -> None:
    artifacts = generate_invariants(_mixed_input())
    # Each invariant gets its own `## INV-S-CHART-<N>` section.
    section_count = len(re.findall(r"^## INV-S-CHART-\d+$", artifacts.markdown, re.MULTILINE))
    assert section_count == 3
    # Header row reports the count too.
    assert "Invariant count:** 3" in artifacts.markdown


def test_markdown_registry_table_columns() -> None:
    artifacts = generate_invariants(_mixed_input())
    assert "| Chart state | Check | Discharges |" in artifacts.markdown
    # Each row formatted with backtick-quoted state + check.
    assert "| `boot` | `bounds` | INV-S-CHART-1 |" in artifacts.markdown


# -----------------------------------------------------------------
# Rust source-level well-formedness checks
# -----------------------------------------------------------------


def test_rust_source_has_balanced_braces() -> None:
    artifacts = generate_invariants(_mixed_input())
    # Strip comments first (Rust line + block); a naive scan would
    # double-count `{` inside doc text.
    src = re.sub(r"//[^\n]*", "", artifacts.rust_source)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    assert src.count("{") == src.count("}"), (
        f"unbalanced braces in generated Rust: "
        f"{src.count('{')} opens vs {src.count('}')} closes"
    )


def test_rust_source_escapes_embedded_quotes() -> None:
    """Test that a chart-site or text field with `"` inside is escaped
    in the emitted Rust constant string."""
    bounds = BoundsAnalysisInput.from_lists(
        invariants=[
            InvariantSpec(
                text='tid == "ready" implies state == Ready',
                chart_site="boot.onentry",
            )
        ],
    )
    artifacts = generate_invariants(bounds)
    # Every literal `"` inside the string body MUST appear as `\"`.
    # Confirm the constant line is well-formed by reconstructing it.
    line = [
        ln for ln in artifacts.rust_source.splitlines()
        if "INV_S_CHART_1: &str" in ln
    ][0]
    body = line.split(' = ', 1)[1].rstrip(";").strip()
    # Body should start and end with `"` and contain no unescaped `"`.
    assert body.startswith('"') and body.endswith('"')
    interior = body[1:-1]
    # Every `"` in the interior must be preceded by a backslash.
    for m in re.finditer(r'"', interior):
        idx = m.start()
        assert idx > 0 and interior[idx - 1] == "\\", (
            "unescaped quote inside Rust string literal"
        )


def test_rust_source_includes_cite_match_arms_for_every_invariant() -> None:
    artifacts = generate_invariants(_mixed_input())
    for i in (1, 2, 3):
        arm = f'"INV-S-CHART-{i}" => INV_S_CHART_{i},'
        assert arm in artifacts.rust_source


def test_rust_source_cite_fn_has_catchall_returning_empty_string() -> None:
    """The cite() lookup MUST NOT panic on unknown id (per generator
    docstring + SOS-13 §8 — keep verified-strip's panic surface
    removed even at the lookup site)."""
    artifacts = generate_invariants(_mixed_input())
    assert '_ => "",' in artifacts.rust_source


def test_rust_source_header_cites_sos13_and_inv_sos_g() -> None:
    artifacts = generate_invariants(_mixed_input())
    assert "SOS-13-CONCEPTS.md" in artifacts.rust_source
    assert "INV-SOS-G" in artifacts.rust_source
    assert "SOS-07-CONCEPTS.md" in artifacts.rust_source


# -----------------------------------------------------------------
# Type-safety guard
# -----------------------------------------------------------------


def test_generate_invariants_rejects_non_dataclass_input() -> None:
    with pytest.raises(TypeError, match="BoundsAnalysisInput"):
        generate_invariants({"invariants": []})  # type: ignore[arg-type]


# -----------------------------------------------------------------
# Optional: cargo check round-trip (skipped if cargo missing)
# -----------------------------------------------------------------


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not on PATH")
def test_generated_rust_passes_cargo_check(tmp_path: Path) -> None:
    """Smoke test: drop the generated `invariants.rs` into a scratch
    crate and run `cargo check`. SKIPs cleanly when cargo is missing,
    so worktree-only CI does not require a Rust toolchain.
    """
    artifacts = generate_invariants(_mixed_input())
    crate = tmp_path / "scratch"
    src = crate / "src"
    src.mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        textwrap.dedent(
            """
            [package]
            name = "scratch"
            version = "0.0.1"
            edition = "2021"

            [lib]
            path = "src/lib.rs"
            """
        ).strip()
        + "\n"
    )
    (src / "invariants.rs").write_text(artifacts.rust_source)
    (src / "lib.rs").write_text(
        "pub mod invariants;\n"
        "pub fn _smoke() -> &'static str {\n"
        "    invariants::cite(\"INV-S-CHART-1\")\n"
        "}\n"
    )
    result = subprocess.run(
        ["cargo", "check", "--quiet"],
        cwd=crate,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"cargo check failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
