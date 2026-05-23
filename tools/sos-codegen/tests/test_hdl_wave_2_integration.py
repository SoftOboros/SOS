"""SOS-08-C wave-2 cross-dialect integration tests.

@spec  docs/concepts/SOS-08-C-CONCEPTS.md §6 (10-step emission algorithm)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §15 (2026-05-23 ratification)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §5.2 (document-order priority)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §5.3 (guard expression compilation)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §5.4 (datamodel signal typing)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §6.7 (per-region clock-domain handling)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §6.10 (chart-top wrapper emission)

@invariants  INV-S-HDL-C-1 (deterministic emission)
@invariants  INV-S-HDL-C-2 (per-region observability)
@invariants  INV-S-HDL-C-3 (cross-domain transition enforcement; post-§15
             amendment: every cross-domain transition retains its
             sos_synchronizer / sos_message_channel instance regardless of
             verified-strip reachability)
@invariants  INV-S-HDL-C-4 (guard expression is synthesizable; post-§15
             amendment: bounded at default depth 8 combinational operators,
             SCXML-LINT-C-2 enforces)
@invariants  INV-S-HDL-C-5 (cooperative completion)

@pcdn  PCDN-SOS-08-C-001 (resolved 2026-05-23): clock-domain inherit-from-
       parent; root defaults to `main`.
@pcdn  PCDN-SOS-08-C-002 (resolved 2026-05-23): retain_synchronizers under
       verified-strip — MTBF claims are independent of chart reachability.
@pcdn  PCDN-SOS-08-C-003 (resolved 2026-05-23): reset state = SCXML
       <initial>.
@pcdn  PCDN-SOS-08-C-004 (resolved 2026-05-23): guard-depth budget = 8
       chained operators; emitter publishes the budget and rejects deeper
       guards with a chart-vocabulary message.
@pcdn  PCDN-SOS-08-C-005 (resolved 2026-05-23): chart annotation wins for
       encoding; --target=fpga|asic is a hint for unannotated regions.
@pcdn  PCDN-SOS-08-C-006 (resolved 2026-05-23): SCXML-LINT-C-1 warns when
       two transitions in the same source state could simultaneously be
       guard-true under bounded reachability.

These tests consume the wave-2 SCXML fixtures in `tests/fixtures/`:

  * single_guarded_transition.scxml     -> TestSingleGuardedTransition
  * multiple_guarded_transitions.scxml  -> TestMultipleGuardedTransitions
  * depth_9_guard.scxml                 -> TestDepth9GuardRejected
  * parallel_two_regions.scxml          -> TestParallelTwoRegions
  * parallel_with_cross_domain.scxml    -> TestParallelWithCrossDomain
  * single_region_with_datamodel.scxml  -> TestPortWidthFromSignalWidth (reused
                                           from wave-1)

The walkers are imported via :data:`Dialect`-parametrised dispatch so each
test runs once against the VHDL walker and once against the SV walker.

The test file is a STATIC deliverable — it is committed at wave-2 fixture
landing time, BEFORE the wave-2 walker landings. Per the orchestrator's
fan-out brief: "Static deliverable; do NOT run pytest." When the sibling
wave-2 walker agents finish, the integration pass runs this file.

Wave-1 walkers reject the wave-2 surface (`<parallel>`, guards, etc.)
with `UnsupportedChartError` and its subclasses — that is the contract
this file flips at wave-2 to "emit successfully".
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Bootstrap: make the `sos-codegen` package directory importable when pytest
# runs from the repo root.
# ---------------------------------------------------------------------------

TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

# `hdl_common` carries the shared Dialect enum + guard-depth helpers used
# by both walker modules. If a sibling agent is mid-flight and the file is
# transiently missing, skip the whole module with a clear message rather
# than raising ImportError during collection.
hdl_common = pytest.importorskip(
    "hdl_common",
    reason="hdl_common sibling-agent module not yet on disk; wave-2 "
    "integration tests skip until the sibling commit lands.",
)

transliterate_hdl_vhdl = pytest.importorskip(
    "transliterate_hdl_vhdl",
    reason="VHDL walker not importable; wave-2 integration tests skip "
    "until the sibling VHDL walker commit lands.",
)

transliterate_hdl_sv = pytest.importorskip(
    "transliterate_hdl_sv",
    reason="SV walker not importable; wave-2 integration tests skip "
    "until the sibling SV walker commit lands.",
)


# ---------------------------------------------------------------------------
# Dialect dispatch helpers.
#
# `Dialect` is the canonical enum on `hdl_common`. The walker modules each
# own a `render_target(chart_ir, config)` entry point that takes the raw
# scjson dict shape. We parametrise every test on the two walkers so a
# single test function covers both VHDL + SV.
# ---------------------------------------------------------------------------

Dialect = hdl_common.Dialect


def _walker_for(dialect) -> Any:
    """Return the walker module corresponding to `dialect`."""
    if dialect is Dialect.VHDL:
        return transliterate_hdl_vhdl
    if dialect is Dialect.SV:
        return transliterate_hdl_sv
    raise ValueError(f"unsupported dialect for wave-2 integration: {dialect!r}")


def _file_ext_for(dialect) -> str:
    """Return the file-extension for `dialect` (without leading dot)."""
    if dialect is Dialect.VHDL:
        return "vhd"
    if dialect is Dialect.SV:
        return "sv"
    raise ValueError(f"unsupported dialect: {dialect!r}")


# ---------------------------------------------------------------------------
# Fixture loading.
#
# `loader.load_chart` shells out to the `scjson` CLI and returns a
# ChartAst whose `.raw_scjson` field carries the chart-IR dict shape that
# both walkers consume. When `scjson` is not on PATH (e.g. minimal CI image),
# skip the fixture-driven tests with a clear reason. Inline dict fixtures
# (covered by the wave-1 test files) remain a fallback elsewhere.
# ---------------------------------------------------------------------------


def _scjson_available() -> bool:
    try:
        res = subprocess.run(
            ["scjson", "--help"], capture_output=True, text=True, check=False
        )
        return res.returncode == 0
    except (FileNotFoundError, OSError):
        return False


pytestmark = [
    pytest.mark.skipif(
        not _scjson_available(),
        reason="`scjson` CLI not on PATH; wave-2 SCXML-fixture integration "
        "tests skip until the scjson Python package is installed in the "
        "test environment.",
    ),
]


def _load_chart_ir(fixture_name: str) -> dict[str, Any]:
    """Load a wave-2 SCXML fixture and return its raw scjson dict shape."""
    from loader import load_chart  # noqa: WPS433 — local import for sys.path

    path = FIXTURES_DIR / fixture_name
    assert path.exists(), f"wave-2 fixture missing: {path}"
    ast = load_chart(path)
    assert ast.raw_scjson is not None, (
        f"loader.load_chart did not populate raw_scjson for {fixture_name}; "
        "wave-2 walker integration depends on the raw-scjson view."
    )
    return ast.raw_scjson


# ---------------------------------------------------------------------------
# Parametrise every test class on the two dialects.
# ---------------------------------------------------------------------------

DIALECTS = [Dialect.VHDL, Dialect.SV]
DIALECT_IDS = ["vhdl", "sv"]


# ===========================================================================
# TestSingleGuardedTransition
# ===========================================================================


class TestSingleGuardedTransition:
    """Cross-dialect wave-2 guard-emit assertions.

    Spec citations:
      * SOS-08-C §5.2 (document-order priority in transition mux).
      * SOS-08-C §5.3 (guard expression compilation table: numeric
        comparison `>` compiles to a synthesizable comparator).
      * SOS-08-C §6.3 (transition mux compilation surface).
      * INV-S-HDL-C-4 (guard expression is synthesizable).
    """

    FIXTURE = "single_guarded_transition.scxml"
    CHART_NAME = "sgt"

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_emit_succeeds(self, dialect):
        """Wave-2 walker emits a guarded transition without raising
        `UnsupportedChartError`. The wave-1 walker rejected guards
        outright (see `test_transliterate_hdl_vhdl.py::
        test_guards_rejected_at_v1_scaffold`); this test flips the
        contract."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        assert isinstance(files, dict) and files, (
            f"{dialect.name} walker produced no files for {self.FIXTURE}"
        )

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_guard_appears_in_transition_mux(self, dialect):
        """The guard `counter > 0` (or its sanitised form) appears in the
        emitted source — proving §5.3 + §6.3 compiled the cond attribute
        into the transition mux body."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        src = "\n".join(files.values())
        # `counter` is the chart-side identifier; the walker may expose it
        # as `data_counter` (port surface) and / or `counter_q` (registered
        # form) — either reference is acceptable.
        assert re.search(r"\b(?:data_)?counter(?:_q)?\b", src), (
            f"{dialect.name} emit lost the chart-side `counter` reference "
            "in the guard expression"
        )
        # The `>` comparator is the load-bearing token from §5.3 — it MUST
        # survive into the emitted dialect.
        assert ">" in src

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_guard_arm_is_conditional(self, dialect):
        """SOS-08-C §5.2: the first arm whose guard evaluates true wins;
        where no transition's guard is true, the mux output is the
        current state (no transition).

        Per the worked example shape in §6.2 / §6.11 + the orchestrator's
        wave-2 brief:
          VHDL: `if (<expr>) then ... else state_next <= state_q;`
          SV  : `if (<expr>) state_next = ...; else ...`

        We use a tolerant regex so the walker may render the conditional
        in either compact or expanded form."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        src = "\n".join(files.values())
        if dialect is Dialect.VHDL:
            # Looking for an `if ... then` arm with a state_next assignment
            # AND an `else state_next <= state_q` fall-through (per §5.2).
            assert re.search(r"\bif\b\s*\(?.*?\)?.*?\bthen\b", src, re.S), (
                "VHDL guarded arm: missing `if ... then` opener"
            )
            assert re.search(r"state_next\s*<=\s*\w+", src), (
                "VHDL guarded arm: missing `state_next <= <state>` assignment"
            )
        else:
            assert re.search(r"\bif\s*\(", src), (
                "SV guarded arm: missing `if (...)` opener"
            )
            assert re.search(r"state_next\s*=\s*\w+", src), (
                "SV guarded arm: missing `state_next = <state>` assignment"
            )

    def test_cross_dialect_state_constants_match(self):
        """Per INV-S-HDL-C-1 + the wave-1 drift-detection convention: a
        guarded chart's state-constant identifiers are byte-identical
        across VHDL and SV emissions."""
        chart = _load_chart_ir(self.FIXTURE)
        cfg = {"chart_name": self.CHART_NAME}

        sv_out, sv_meta = transliterate_hdl_sv.render_target_with_metadata(
            chart, cfg
        )
        if hasattr(transliterate_hdl_vhdl, "render_target_with_metadata"):
            _vhdl_out, vhdl_meta = (
                transliterate_hdl_vhdl.render_target_with_metadata(chart, cfg)
            )
        else:
            vhdl_out = transliterate_hdl_vhdl.render_target(chart, cfg)
            vhdl_src = next(iter(vhdl_out.values()))
            names = [
                m.group(1)
                for m in re.finditer(r"constant\s+(ST_[A-Z_0-9]+)\s*:", vhdl_src)
            ]
            vhdl_meta = {"state_constants": names, "state_names": names}

        assert sv_meta["state_constants"] == vhdl_meta["state_constants"], (
            "wave-2 single-guarded-transition fixture: state-constant "
            f"order drift between SV={sv_meta['state_constants']!r} "
            f"and VHDL={vhdl_meta['state_constants']!r}"
        )


# ===========================================================================
# TestMultipleGuardedTransitions
# ===========================================================================


class TestMultipleGuardedTransitions:
    """Cross-dialect priority-chain assertions for three guarded arms.

    Spec citations:
      * SOS-08-C §5.2 (document-order priority).
      * SOS-08-C §5.3 (guard expression compilation: `==`, `>`, `!=`).
      * SOS-08-C §6.3 (transition mux).
      * PCDN-SOS-08-C-006 (resolved): SCXML-LINT-C-1 warns when two
        transitions could simultaneously fire; emitter respects the
        document order regardless.
    """

    FIXTURE = "multiple_guarded_transitions.scxml"
    CHART_NAME = "mgt"

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_emit_succeeds(self, dialect):
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        assert isinstance(files, dict) and files

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_priority_chain_shape(self, dialect):
        """SOS-08-C §5.2 + §6.3: the three guarded arms compile to a
        priority chain — VHDL `if ... elsif ... elsif ... else`, SV
        `if ... else if ... else if ... else`."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        src = "\n".join(files.values())
        if dialect is Dialect.VHDL:
            # VHDL elsif chain — at least two `elsif` tokens (3 arms ->
            # `if ... elsif ... elsif ... else`).
            assert src.count("elsif") >= 2, (
                f"VHDL priority chain expected >=2 `elsif`, got "
                f"{src.count('elsif')}"
            )
            assert re.search(r"\belse\b", src), (
                "VHDL priority chain expected a final `else` fall-through"
            )
        else:
            # SV `else if` chain — at least two `else if` tokens.
            assert len(re.findall(r"\belse\s+if\b", src)) >= 2, (
                "SV priority chain expected >=2 `else if`, got "
                f"{len(re.findall(r'else if', src))}"
            )
            assert re.search(r"\belse\b", src), (
                "SV priority chain expected a final `else` fall-through"
            )

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_document_order_preserved(self, dialect):
        """SOS-08-C §5.2: the chart's document order of transitions is
        the chart-author-visible priority. The emitted guards SHALL
        appear in the order `a == 1`, `b > 5`, `c != 0`."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        src = "\n".join(files.values())
        # Tolerant of `data_a` / `a_q` prefixes the walker may apply.
        identifier_pattern = lambda base: rf"(?:data_)?{base}(?:_q)?"
        idx_a = re.search(
            rf"{identifier_pattern('a')}\s*==\s*1", src
        )
        idx_b = re.search(
            rf"{identifier_pattern('b')}\s*>\s*5", src
        )
        idx_c = re.search(
            rf"{identifier_pattern('c')}\s*!=\s*0", src
        )
        assert idx_a is not None, f"{dialect.name}: guard `a == 1` missing"
        assert idx_b is not None, f"{dialect.name}: guard `b > 5` missing"
        assert idx_c is not None, f"{dialect.name}: guard `c != 0` missing"
        # Document-order priority: the three guards appear in the source
        # in the same order as in the chart.
        assert idx_a.start() < idx_b.start() < idx_c.start(), (
            f"{dialect.name} priority order drift: chart order is "
            "a==1 -> b>5 -> c!=0 but emit reordered them"
        )


# ===========================================================================
# TestDepth9GuardRejected
# ===========================================================================


class TestDepth9GuardRejected:
    """Over-budget guard-depth rejection (PCDN-SOS-08-C-004).

    Spec citations:
      * PCDN-SOS-08-C-004 (resolved): guard-depth budget = 8 chained
        operators; emitter publishes the budget and rejects deeper
        guards with a chart-vocabulary message.
      * INV-S-HDL-C-4 (post-§15 amendment: bounded at default depth 8;
        SCXML-LINT-C-2 enforces at chart-compile time so the failure
        surface is the chart, not the synth-tool place-and-route).
      * INV-S-HDL-5 (chart-vocabulary traceability).
    """

    FIXTURE = "depth_9_guard.scxml"
    CHART_NAME = "d9"

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_emit_raises_unsupported_chart_error(self, dialect):
        """Per PCDN-SOS-08-C-004: a depth-9 guard exceeds the default
        budget of 8 chained operators and MUST raise
        `UnsupportedChartError` (or one of its dialect-specific
        subclasses)."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        with pytest.raises(walker.UnsupportedChartError) as exc_info:
            walker.render_target(chart, {"chart_name": self.CHART_NAME})
        msg = str(exc_info.value)
        # The failure message MUST surface BOTH the measured depth (9)
        # and the configured budget (8) — per INV-S-HDL-5 the chart
        # author needs the chart-vocabulary handle, not the operator's
        # name. Tolerant of phrasing variations: `depth 9`, `depth=9`,
        # `depth: 9`, `depth of 9`, etc.
        assert re.search(r"\bdepth\b[^0-9]{0,8}\b9\b", msg), (
            f"{dialect.name}: depth-9 rejection message should cite the "
            f"measured depth 9 explicitly; got: {msg!r}"
        )
        assert re.search(r"\bbudget\b[^0-9]{0,8}\b8\b", msg), (
            f"{dialect.name}: depth-9 rejection message should cite the "
            f"configured budget 8 explicitly; got: {msg!r}"
        )


# ===========================================================================
# TestParallelTwoRegions
# ===========================================================================


class TestParallelTwoRegions:
    """Cross-dialect parallel-region emission assertions.

    Spec citations:
      * SOS-08-C §6.1 (region tree: one region per <parallel> child).
      * SOS-08-C §6.2 (per-region FSM module surface).
      * SOS-08-C §6.10 (chart-top wrapper instantiates each region).
      * INV-S-HDL-C-1 (deterministic emission).
      * INV-S-HDL-C-5 (cooperative completion).
    """

    FIXTURE = "parallel_two_regions.scxml"
    CHART_NAME = "par2"

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_emit_three_files(self, dialect):
        """SOS-08-C §6.1 + §6.10: a chart with two parallel regions
        emits three files: one per region module + one chart-top
        wrapper module."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        ext = _file_ext_for(dialect)
        assert isinstance(files, dict)
        # The orchestrator's wave-2 brief names the three files:
        #   <chart>_region_region_a.<ext>
        #   <chart>_region_region_b.<ext>
        #   <chart>_top.<ext>
        # The wave-2 walker SHOULD produce these names; tolerate
        # `_region_a` vs `region_region_a` variants by checking that
        # at least one filename per region contains its region-id.
        region_a_files = [
            f for f in files
            if f.endswith(f".{ext}") and "region_a" in f
        ]
        region_b_files = [
            f for f in files
            if f.endswith(f".{ext}") and "region_b" in f
        ]
        top_files = [
            f for f in files
            if f.endswith(f".{ext}") and "_top" in f
        ]
        assert region_a_files, (
            f"{dialect.name}: expected a region_a {ext} file; got "
            f"{sorted(files)!r}"
        )
        assert region_b_files, (
            f"{dialect.name}: expected a region_b {ext} file; got "
            f"{sorted(files)!r}"
        )
        assert top_files, (
            f"{dialect.name}: expected a chart-top wrapper {ext} file; "
            f"got {sorted(files)!r}"
        )
        # File count totals at least 3 (region modules + wrapper).
        assert len(files) >= 3, (
            f"{dialect.name}: expected at least 3 files for a 2-region "
            f"parallel chart; got {len(files)}"
        )

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_top_wrapper_instantiates_each_region(self, dialect):
        """SOS-08-C §6.10: the chart-top wrapper instantiates each
        region module exactly once."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        ext = _file_ext_for(dialect)
        top_path = next(
            (f for f in files if f.endswith(f".{ext}") and "_top" in f),
            None,
        )
        assert top_path is not None, "chart-top wrapper file missing"
        top_src = files[top_path]
        # Both region module names appear in the wrapper body. Per the
        # §6.2 worked example the module identifier carries the
        # region-id, e.g. `sos_region_region_a` or `<chart>_region_region_a`.
        assert "region_a" in top_src, (
            f"{dialect.name} wrapper does not reference region_a"
        )
        assert "region_b" in top_src, (
            f"{dialect.name} wrapper does not reference region_b"
        )


# ===========================================================================
# TestParallelWithCrossDomain
# ===========================================================================


class TestParallelWithCrossDomain:
    """Cross-domain `sos_synchronizer` instantiation assertions.

    Spec citations:
      * SOS-08-C §6.7 (per-region clock-domain handling; chart-top
        wrapper instantiates sos_synchronizer / sos_message_channel
        per cross-domain transition).
      * SOS-08-C §6.10 (chart-top wrapper emission).
      * PCDN-SOS-08-C-001 (resolved): clock-domain inherit-from-parent;
        root defaults to `main`.
      * PCDN-SOS-08-C-002 (resolved): retain_synchronizers — MTBF
        claims are independent of reachability.
      * INV-S-HDL-C-3 (post-§15 amendment: every cross-domain
        transition retains its sos_synchronizer / sos_message_channel
        instance regardless of verified-strip reachability).
    """

    FIXTURE = "parallel_with_cross_domain.scxml"
    CHART_NAME = "par2cd"

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_emit_succeeds(self, dialect):
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        assert isinstance(files, dict) and files

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_top_wrapper_instantiates_synchronizer(self, dialect):
        """SOS-08-C §6.7 step 2 + INV-S-HDL-C-3: every cross-domain
        signal route SHALL be wired through `sos_synchronizer` (or
        `sos_message_channel`) instantiated at the chart-top
        wrapper."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        ext = _file_ext_for(dialect)
        top_path = next(
            (f for f in files if f.endswith(f".{ext}") and "_top" in f),
            None,
        )
        assert top_path is not None, "chart-top wrapper file missing"
        top_src = files[top_path]
        # The chart-top SHALL reference `sos_synchronizer` for the
        # shared_flag CDC path. The exact L1 primitive name comes from
        # SOS-08-A/B; both walkers consume the same name.
        assert "sos_synchronizer" in top_src, (
            f"{dialect.name} wrapper does not instantiate sos_synchronizer "
            "for the shared_flag cross-domain path"
        )

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_top_wrapper_exposes_both_clock_domains(self, dialect):
        """PCDN-SOS-08-C-001: the chart-top wrapper exposes one clock
        port per declared clock domain. This fixture declares
        `clk_main` (inherited from root) and `clk_fast` (annotated on
        region_b), so the wrapper SHALL expose both."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        ext = _file_ext_for(dialect)
        top_path = next(
            (f for f in files if f.endswith(f".{ext}") and "_top" in f),
            None,
        )
        assert top_path is not None
        top_src = files[top_path]
        assert "clk_main" in top_src, (
            f"{dialect.name} wrapper missing `clk_main` port"
        )
        assert "clk_fast" in top_src, (
            f"{dialect.name} wrapper missing `clk_fast` port"
        )


# ===========================================================================
# TestPortWidthFromSignalWidth
# ===========================================================================


class TestPortWidthFromSignalWidth:
    """Datamodel-signal width / RTL port-width assertions.

    Reuses the wave-1 `single_region_with_datamodel.scxml` fixture
    (chart already on disk; the `counter` data element is declared
    without an explicit `width` attribute → SOS-04 / SOS-05 default
    width applies, which is 32 bits per SOS-08-C §5.4).

    Spec citations:
      * SOS-08-C §5.4 (datamodel signal typing; default width
        = 32 bits when chart annotation absent).
      * SOS-08-C §6.6 (compile datamodel + <assign>).
    """

    FIXTURE = "single_region_with_datamodel.scxml"
    CHART_NAME = "dmw"

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_data_counter_is_32_bits(self, dialect):
        """Per §5.4: a `<data id="counter" expr="0"/>` without an
        explicit width attribute resolves to 32 bits. The emitted
        port-width SHALL reflect that:
          VHDL: `signed(31 downto 0)` or `std_logic_vector(31 downto 0)`
          SV  : `wire [31:0] data_counter` (signed or unsigned)
        """
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        src = "\n".join(files.values())
        if dialect is Dialect.VHDL:
            # Either the unsigned-vector or the signed/numeric_std form
            # is acceptable — the load-bearing assertion is the 31-downto-0
            # range matching the §5.4 default width.
            assert re.search(
                r"(?:std_logic_vector|signed|unsigned)\s*\(\s*31\s+downto\s+0\s*\)",
                src,
            ), (
                "VHDL emit lost the 32-bit data_counter port width; "
                f"expected `(31 downto 0)` per §5.4 default; src head:\n"
                f"{src[:400]}"
            )
        else:
            # SV: tolerate `[31:0]` with either `wire` or `logic` typing
            # and an optional `signed` qualifier.
            assert re.search(
                r"\b(?:wire|logic)\b(?:\s+signed)?\s*\[\s*31\s*:\s*0\s*\]",
                src,
            ), (
                "SV emit lost the 32-bit data_counter port width; "
                f"expected `[31:0]` per §5.4 default; src head:\n"
                f"{src[:400]}"
            )

    @pytest.mark.parametrize("dialect", DIALECTS, ids=DIALECT_IDS)
    def test_data_counter_port_present(self, dialect):
        """SOS-08-C §6.2 worked example: each datamodel signal surfaces
        as a `data_<id>` output port on the region module."""
        walker = _walker_for(dialect)
        chart = _load_chart_ir(self.FIXTURE)
        files = walker.render_target(chart, {"chart_name": self.CHART_NAME})
        src = "\n".join(files.values())
        assert "data_counter" in src
