"""SOS-08-D primary vector path — main.py dispatch integration tests.

@spec  docs/concepts/SOS-08-D-CONCEPTS.md §6.1 (emit directory layout)
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §6.2 (per-vector cocotb test
       function shape)
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §6.3 (per-DUT SVA bind file shape)
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §6.4 (simulator-invocation
       conventions — Makefile + pytest.ini)
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §15 (2026-05-23 ratification)

@invariants  INV-S-HDL-D-1 (dual artifact, one IR — cocotb + SVA
             co-emitted from the same chart pass)
@invariants  INV-S-HDL-D-2 (open-source-simulator coverage at v1 —
             Verilator + Icarus + GHDL)
@invariants  INV-S-HDL-D-3 (vector-IR read-only at emitter boundary)
@invariants  INV-S-HDL-D-4 (same SVA artifact feeds cocotb and formal flow)
@invariants  INV-S-HDL-D-5 (chart-vocabulary failure messages)
@invariants  INV-S-HDL-D-6 (per-vector test isolation by default)

@pcdn  PCDN-SOS-08-D-001 (resolved 2026-05-23): default sim = Verilator.
@pcdn  PCDN-SOS-08-D-002 (resolved 2026-05-23): emit cocotb's
       results.xml AND post-process to pure JUnit XML.
@pcdn  PCDN-SOS-08-D-003 (resolved 2026-05-23): one @cocotb.test per
       vector.
@pcdn  PCDN-SOS-08-D-004 (resolved 2026-05-23): per-DUT SVA bind file
       co-located with the cocotb test directory.
@pcdn  PCDN-SOS-08-D-005 (resolved 2026-05-23): Python 3.10+.
@pcdn  PCDN-SOS-08-D-006 (resolved 2026-05-23): one test_<dut>.py per
       DUT; shared `_cocotb_helpers.py`.
@pcdn  PCDN-SOS-08-D-007 (resolved 2026-05-23): emit BOTH Makefile AND
       pytest.ini.

These tests exercise the `tools/sos-codegen/main.py` dispatch for the
two new ``--target`` values (``cocotb``, ``sva``) wired in wave-1.
The walker modules `transliterate_cocotb.py` + `transliterate_sva_bind.py`
are owned by parallel fan-out agents; if either is transiently absent at
collection time, the affected tests skip with a clear reason (mirrors
the wave-2 HDL integration suite's `pytest.importorskip` pattern).

The test file is a STATIC deliverable — committed before the sibling
walker landings; the integration pass runs once the siblings land.
"""

from __future__ import annotations

import ast as pyast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Bootstrap: make the `sos-codegen` package directory importable when pytest
# runs from the repo root. Mirrors test_hdl_wave_2_integration.py.
# ---------------------------------------------------------------------------

TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


# `scjson` CLI is required by loader.load_chart. The wave-2 HDL
# integration suite gates on it; do the same here so a minimal CI image
# without the scjson package skips cleanly.
def _scjson_available() -> bool:
    try:
        res = subprocess.run(
            ["scjson", "--help"], capture_output=True, text=True, check=False
        )
        return res.returncode == 0
    except (FileNotFoundError, OSError):
        return False


# Sibling walker availability gates — wire-1 fan-out modules. If either
# is mid-flight at collection time the corresponding tests skip.
cocotb_walker = pytest.importorskip(
    "transliterate_cocotb",
    reason="transliterate_cocotb sibling-agent module not yet on disk; "
    "SOS-08-D integration tests skip until the wave-1 cocotb walker "
    "commit lands.",
)

sva_walker = pytest.importorskip(
    "transliterate_sva_bind",
    reason="transliterate_sva_bind sibling-agent module not yet on disk; "
    "SOS-08-D integration tests skip until the wave-1 SVA bind walker "
    "commit lands.",
)


pytestmark = [
    pytest.mark.skipif(
        not _scjson_available(),
        reason="`scjson` CLI not on PATH; SOS-08-D integration tests skip "
        "until the scjson Python package is installed.",
    ),
]


# Fixture file paths.
FIXTURE_SCXML = FIXTURES_DIR / "single_region_simple.scxml"
FIXTURE_VECTOR = FIXTURES_DIR / "single_region_simple_vector.json"
CHART_NAME = "single_region_simple"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _run_main(target: str, out_dir: Path, chart: Path = FIXTURE_SCXML) -> int:
    """Drive `main.main([...])` directly with a captured argv list.

    Returns the exit code; raises if main.py is not importable.
    """
    import main as codegen_main  # noqa: WPS433 — late import per sys.path

    argv = [
        "--target", target,
        "--chart", str(chart),
        "--out", str(out_dir),
    ]
    return codegen_main.main(argv)


def _emit_via_walker(walker, chart_path: Path) -> dict[str, str]:
    """Directly invoke the sibling walker's `render_target` against the
    chart's raw scjson dict — bypasses main.py to give the test a
    second, independent view of the emit contract.
    """
    from loader import load_chart  # noqa: WPS433

    ast_obj = load_chart(chart_path)
    assert ast_obj.raw_scjson is not None, (
        f"loader.load_chart did not populate raw_scjson for {chart_path}"
    )
    files = walker.render_target(
        ast_obj.raw_scjson, {"chart_name": CHART_NAME}
    )
    assert isinstance(files, dict), (
        f"walker {walker.__name__}.render_target did not return a dict "
        f"(got {type(files).__name__}); sibling signature drift."
    )
    return files


def _find_file(files: dict[str, str], suffix: str) -> tuple[str, str] | None:
    """Return the (path, body) of the first file in `files` whose path
    ends with `suffix`, or None."""
    for fname, body in files.items():
        if fname.endswith(suffix):
            return fname, body
    return None


# ---------------------------------------------------------------------------
# §6.1 emit directory layout — cocotb target produces all 5 named files.
# ---------------------------------------------------------------------------


class TestCocotbTargetEmitsExpectedFiles:
    """SOS-08-D §6.1 — per-DUT cocotb test directory layout.

    The emit directory contains (at least):
        test_<chart>_fsm.py         (per PCDN-D-006 / §6.2)
        _cocotb_helpers.py          (per §6.2 / PCDN-D-006)
        Makefile                    (per §6.4 / PCDN-D-001)
        pytest.ini                  (per PCDN-D-007)
        README.md                   (per §6.1 + PCDN-D-005)
        vectors/<seed>.json|jsonl   (per PCDN-D-003 — seed example)
    """

    def test_cocotb_target_emits_expected_files(self, tmp_path):
        """Drive `main.main(['--target', 'cocotb', ...])`; assert the
        five named §6.1 files are present in the emit."""
        rc = _run_main("cocotb", tmp_path)
        assert rc == 0, f"main.main(--target=cocotb) returned {rc}"

        # Collect every emitted relative path under tmp_path.
        emitted = sorted(
            p.relative_to(tmp_path).as_posix()
            for p in tmp_path.rglob("*")
            if p.is_file()
        )
        emitted_str = "\n".join(emitted)

        # Per the orchestrator's wave-1 brief + §6.1, the cocotb walker
        # emits each artifact under `tests/<chart_name>/`. Tolerate the
        # `tests/<chart_name>/` prefix (sibling agents may vary nesting
        # depth slightly); the load-bearing assertion is that each of
        # the named files appears somewhere in the emit.
        for expected in (
            f"test_{CHART_NAME}_fsm.py",
            "_cocotb_helpers.py",
            "Makefile",
            "pytest.ini",
            "README.md",
        ):
            assert any(e.endswith(expected) for e in emitted), (
                f"SOS-08-D §6.1: cocotb emit missing `{expected}`; "
                f"emitted:\n{emitted_str}"
            )

        # Vectors directory: at least one JSON / JSONL example per
        # PCDN-D-003 (seed vector). Tolerate either suffix and either
        # top-level (`vectors/...`) or nested (`tests/<chart>/vectors/...`)
        # placement (sibling walkers vary on the prefix).
        assert any(
            ("vectors/" in e)
            and (e.endswith(".json") or e.endswith(".jsonl"))
            for e in emitted
        ), (
            f"SOS-08-D PCDN-D-003: cocotb emit missing a vectors/*.json"
            f"|jsonl seed example; emitted:\n{emitted_str}"
        )


# ---------------------------------------------------------------------------
# §6.3 SVA bind file emission — sva target produces the assertion + bind pair.
# ---------------------------------------------------------------------------


class TestSvaTargetEmitsBindFiles:
    """SOS-08-D §6.3 + PCDN-D-004 — the SVA target emits both the
    assertion module body (`<chart>_fsm_sva.sv`) and the bind directive
    (`<chart>_fsm_bind.sv`) per-DUT, co-located in the test directory.
    """

    def test_sva_target_emits_bind_files(self, tmp_path):
        """Drive `main.main(['--target', 'sva', ...])`; assert the two
        SVA files are present in the emit."""
        rc = _run_main("sva", tmp_path)
        assert rc == 0, f"main.main(--target=sva) returned {rc}"

        emitted = sorted(
            p.relative_to(tmp_path).as_posix()
            for p in tmp_path.rglob("*")
            if p.is_file()
        )
        emitted_str = "\n".join(emitted)

        assert any(e.endswith(f"{CHART_NAME}_fsm_sva.sv") for e in emitted), (
            f"SOS-08-D §6.3: SVA emit missing `{CHART_NAME}_fsm_sva.sv` "
            f"(assertion module body); emitted:\n{emitted_str}"
        )
        assert any(e.endswith(f"{CHART_NAME}_fsm_bind.sv") for e in emitted), (
            f"SOS-08-D PCDN-D-004: SVA emit missing "
            f"`{CHART_NAME}_fsm_bind.sv` (bind directive); "
            f"emitted:\n{emitted_str}"
        )


# ---------------------------------------------------------------------------
# §6.2 — the emitted cocotb test file is valid Python and imports helpers.
# ---------------------------------------------------------------------------


class TestCocotbEmitContent:
    """Static, parse-level checks on the cocotb-emitted Python source.

    These don't require pytest-cocotb or a simulator on PATH; they
    verify the emit is a syntactically valid Python module and that
    it imports the shared helpers module per §6.2 / PCDN-D-006.
    """

    def test_cocotb_test_file_is_valid_python(self):
        """The emitted `test_<chart>_fsm.py` MUST parse as valid Python
        (PCDN-D-005: Python 3.10+ minimum)."""
        files = _emit_via_walker(cocotb_walker, FIXTURE_SCXML)
        match = _find_file(files, f"test_{CHART_NAME}_fsm.py")
        assert match is not None, (
            f"cocotb walker emitted no `test_{CHART_NAME}_fsm.py`; "
            f"got files: {sorted(files)!r}"
        )
        _path, body = match
        try:
            pyast.parse(body)
        except SyntaxError as exc:
            pytest.fail(
                f"SOS-08-D §6.2: emitted cocotb test file is not valid "
                f"Python: {exc!r}\n--- first 400 chars ---\n{body[:400]}"
            )

    def test_cocotb_test_imports_helpers(self):
        """Per §6.2 / PCDN-D-006: shared helpers live in
        `_cocotb_helpers.py`; the per-DUT `test_<chart>_fsm.py` MUST
        import from them (one or more of `_reset_dut`, `_drive_event`,
        `_check_expected`, `load_jsonl`)."""
        files = _emit_via_walker(cocotb_walker, FIXTURE_SCXML)
        match = _find_file(files, f"test_{CHART_NAME}_fsm.py")
        assert match is not None
        _path, body = match
        # Tolerate `from _cocotb_helpers import …` AND
        # `import _cocotb_helpers` styles.
        assert (
            "_cocotb_helpers" in body
        ), (
            "SOS-08-D §6.2: emitted cocotb test file does not reference "
            "`_cocotb_helpers` (shared helper module per PCDN-D-006). "
            f"First 400 chars:\n{body[:400]}"
        )


# ---------------------------------------------------------------------------
# §6.3 — SVA bind file uses the `bind <chart>_fsm <chart>_fsm_sva u_...`
# directive form.
# ---------------------------------------------------------------------------


class TestSvaEmitContent:
    """Static checks on the SVA bind file shape per §6.3."""

    def test_sva_bind_file_uses_module_type(self):
        """§6.3 / PCDN-D-004: the bind directive in
        `<chart>_fsm_bind.sv` SHALL reference the DUT module
        (`<chart>_fsm`) and the assertion module
        (`<chart>_fsm_sva`)."""
        files = _emit_via_walker(sva_walker, FIXTURE_SCXML)
        match = _find_file(files, f"{CHART_NAME}_fsm_bind.sv")
        assert match is not None, (
            f"SVA walker emitted no `{CHART_NAME}_fsm_bind.sv`; "
            f"got files: {sorted(files)!r}"
        )
        _path, body = match
        # §6.3 worked example: `bind <dut_module> <assertion_module> u_<id> ( ... )`.
        # We assert the three load-bearing tokens appear in order.
        assert "bind" in body, (
            f"SOS-08-D §6.3: bind file missing `bind` keyword. "
            f"First 400 chars:\n{body[:400]}"
        )
        assert f"{CHART_NAME}_fsm" in body, (
            f"SOS-08-D §6.3: bind file does not reference DUT module "
            f"`{CHART_NAME}_fsm`. First 400 chars:\n{body[:400]}"
        )
        assert f"{CHART_NAME}_fsm_sva" in body, (
            f"SOS-08-D §6.3: bind file does not reference assertion "
            f"module `{CHART_NAME}_fsm_sva`. "
            f"First 400 chars:\n{body[:400]}"
        )
        # The instance name convention per §6.3 worked example is
        # `u_<something>` (e.g. `u_sva`, `u_assertions`). The bind
        # directive's instance identifier MUST start with `u_`.
        import re
        assert re.search(
            rf"bind\s+{CHART_NAME}_fsm\s+{CHART_NAME}_fsm_sva\s+u_\w+",
            body,
        ), (
            "SOS-08-D §6.3: bind directive does not match the canonical "
            f"`bind {CHART_NAME}_fsm {CHART_NAME}_fsm_sva u_<id> (...)` "
            f"shape; first 400 chars:\n{body[:400]}"
        )


# ---------------------------------------------------------------------------
# PCDN-D-005 — README.md documents the Python 3.10 minimum.
# ---------------------------------------------------------------------------


class TestReadmeDocumentsPythonMinimum:
    """PCDN-SOS-08-D-005 (resolved): Python 3.10+ at v1; the per-DUT
    README.md SHALL document the minimum interpreter version."""

    def test_python_3_10_minimum_in_readme(self):
        files = _emit_via_walker(cocotb_walker, FIXTURE_SCXML)
        match = _find_file(files, "README.md")
        assert match is not None, (
            "cocotb walker emitted no `README.md`; PCDN-D-005 requires "
            "the per-DUT README to document the Python minimum."
        )
        _path, body = match
        assert "Python 3.10" in body, (
            "SOS-08-D PCDN-D-005: README.md does not name `Python 3.10` "
            "as the minimum interpreter version. "
            f"First 400 chars:\n{body[:400]}"
        )


# ---------------------------------------------------------------------------
# Cross-emission equivalence — cocotb test references the same state
# constants the HDL-SV walker emits for the FSM module (INV-S-HDL-D-1).
# ---------------------------------------------------------------------------


class TestCrossEmissionStateConstants:
    """INV-S-HDL-D-1 (dual artifact, one IR): the cocotb testbench and
    the SVA bind file are co-emitted from one bounded-reachability pass.
    By extension the cocotb test's chart-state references MUST line up
    with the FSM module's state-constant names (which the SOS-08-C
    HDL-SV walker emits from the same chart). This catches the most
    common cross-target drift: chart state `ACTIVE` renamed in one
    emitter and not the other.
    """

    def test_cocotb_test_file_uses_state_constants_matching_hdl_sv(self):
        # Run hdl-sv to get the canonical state-constant names.
        hdl_sv = pytest.importorskip(
            "transliterate_hdl_sv",
            reason="HDL-SV walker not importable; cross-emission test "
            "needs both walkers' outputs on the same fixture.",
        )
        from loader import load_chart  # noqa: WPS433

        chart_ast = load_chart(FIXTURE_SCXML)
        assert chart_ast.raw_scjson is not None

        hdl_files = hdl_sv.render_target(
            chart_ast.raw_scjson, {"chart_name": CHART_NAME}
        )
        hdl_src = "\n".join(hdl_files.values())

        # The chart's four states (IDLE/ACTIVE/DONE/ERROR) appear in
        # the HDL-SV emit either as state-constant identifiers
        # (e.g. `ST_IDLE`) or as raw chart-state names. We assert each
        # chart-state name appears somewhere in the HDL-SV emit (this
        # is the cross-target naming pin).
        chart_states = ("IDLE", "ACTIVE", "DONE", "ERROR")
        hdl_states_present = [s for s in chart_states if s in hdl_src]
        assert hdl_states_present == list(chart_states), (
            f"HDL-SV emit missing chart states "
            f"{set(chart_states) - set(hdl_states_present)!r}; "
            "cross-emission state-constant alignment with cocotb cannot "
            "be checked."
        )

        # Now the same chart-state names MUST appear somewhere in the
        # cocotb emit (the per-DUT test file, the shared helpers module,
        # the seed vector, or the README). The chart vocabulary is the
        # binding contract per INV-S-HDL-D-1 / INV-S-HDL-D-5; the cocotb
        # walker may surface state IDs in the helpers' `_STATE_ENCODING`
        # mapping rather than inlined in the test body, which is fine —
        # cross-target divergence on the SET of state IDs is what we are
        # guarding against.
        cocotb_files = _emit_via_walker(cocotb_walker, FIXTURE_SCXML)
        cocotb_blob = "\n".join(cocotb_files.values())
        for state in chart_states:
            assert state in cocotb_blob, (
                f"INV-S-HDL-D-1 drift: chart state `{state}` appears in "
                "HDL-SV emit but is missing from the entire cocotb emit. "
                "Cocotb + SVA / HDL-SV emits diverged on chart vocabulary; "
                "they MUST share one bounded-reachability IR."
            )


# ---------------------------------------------------------------------------
# Smoke test for the fixture vector JSON itself — guards against
# accidental damage to the seed vector.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PCDN-SOS-08-D-wave1-cli-unified — unified `--target sos-08-d` emits BOTH
# the cocotb testbench AND the SVA bind file in one invocation.
# ---------------------------------------------------------------------------


class TestUnifiedSos08DTarget:
    """PCDN-SOS-08-D-wave1-cli-unified (resolved 2026-05-23 §15
    walkthrough): the split ``--target cocotb`` / ``--target sva``
    forms iterate one artifact at a time; ``--target sos-08-d`` is the
    unified form that emits both artifact sets in one invocation.

    Per the brief, the two walkers' filename keys are file-disjoint
    under SOS-08-D §6.1 layout, so the merged dict's path set MUST
    equal the union of the two split-target path sets, byte-identical.
    """

    def test_unified_target_emits_both_cocotb_and_sva(self, tmp_path):
        """Drive `main.main(['--target', 'sos-08-d', ...])`; assert the
        emit contains cocotb-owned files AND SVA-owned files."""
        rc = _run_main("sos-08-d", tmp_path)
        assert rc == 0, f"main.main(--target=sos-08-d) returned {rc}"

        emitted = sorted(
            p.relative_to(tmp_path).as_posix()
            for p in tmp_path.rglob("*")
            if p.is_file()
        )
        emitted_str = "\n".join(emitted)

        # Cocotb-owned artifacts per §6.1 (cocotb walker owns these
        # filenames; the unified target MUST surface every one).
        for expected in (
            f"test_{CHART_NAME}_fsm.py",
            "_cocotb_helpers.py",
            "Makefile",
            "pytest.ini",
            "README.md",
        ):
            assert any(e.endswith(expected) for e in emitted), (
                f"PCDN-SOS-08-D-wave1-cli-unified: unified emit missing "
                f"cocotb artifact `{expected}`; emitted:\n{emitted_str}"
            )

        # SVA-owned artifacts per §6.3 / PCDN-D-004.
        for expected in (
            f"{CHART_NAME}_fsm_sva.sv",
            f"{CHART_NAME}_fsm_bind.sv",
        ):
            assert any(e.endswith(expected) for e in emitted), (
                f"PCDN-SOS-08-D-wave1-cli-unified: unified emit missing "
                f"SVA artifact `{expected}`; emitted:\n{emitted_str}"
            )

        # Vector seed (PCDN-D-003) — cocotb side contributes at least
        # one vectors/*.json|jsonl file.
        assert any(
            ("vectors/" in e)
            and (e.endswith(".json") or e.endswith(".jsonl"))
            for e in emitted
        ), (
            f"PCDN-SOS-08-D-wave1-cli-unified: unified emit missing a "
            f"vectors/*.json|jsonl seed example (PCDN-D-003); "
            f"emitted:\n{emitted_str}"
        )

    def test_unified_target_file_count_is_union(self, tmp_path):
        """The merged file count MUST equal cocotb count + SVA count
        (no key collisions; PCDN-SOS-08-D-wave1-cli-unified file-
        disjoint contract)."""
        cocotb_out = tmp_path / "cocotb"
        sva_out = tmp_path / "sva"
        unified_out = tmp_path / "unified"

        rc_c = _run_main("cocotb", cocotb_out)
        rc_s = _run_main("sva", sva_out)
        rc_u = _run_main("sos-08-d", unified_out)
        assert rc_c == 0 and rc_s == 0 and rc_u == 0, (
            f"split + unified returns: cocotb={rc_c}, sva={rc_s}, "
            f"sos-08-d={rc_u}"
        )

        def _count(root: Path) -> int:
            return sum(1 for p in root.rglob("*") if p.is_file())

        n_cocotb = _count(cocotb_out)
        n_sva = _count(sva_out)
        n_unified = _count(unified_out)
        assert n_unified == n_cocotb + n_sva, (
            f"PCDN-SOS-08-D-wave1-cli-unified file-disjoint contract: "
            f"unified count ({n_unified}) != cocotb ({n_cocotb}) + sva "
            f"({n_sva}). Sibling walker key-collision drift detected."
        )

    def test_unified_target_file_paths_match_split_targets(self, tmp_path):
        """The set of relative paths emitted by ``--target sos-08-d``
        MUST equal the union of the paths emitted by ``--target
        cocotb`` and ``--target sva`` (byte-identical paths). This
        pins the file-layout contract so that downstream simulator-
        invocation conventions (§6.4 Makefile + pytest.ini) keep
        working unchanged whether the operator iterated split-target
        or unified-target during emit."""
        cocotb_out = tmp_path / "cocotb"
        sva_out = tmp_path / "sva"
        unified_out = tmp_path / "unified"

        rc_c = _run_main("cocotb", cocotb_out)
        rc_s = _run_main("sva", sva_out)
        rc_u = _run_main("sos-08-d", unified_out)
        assert rc_c == 0 and rc_s == 0 and rc_u == 0

        def _paths(root: Path) -> set[str]:
            return {
                p.relative_to(root).as_posix()
                for p in root.rglob("*")
                if p.is_file()
            }

        cocotb_paths = _paths(cocotb_out)
        sva_paths = _paths(sva_out)
        unified_paths = _paths(unified_out)
        expected_union = cocotb_paths | sva_paths

        assert unified_paths == expected_union, (
            f"PCDN-SOS-08-D-wave1-cli-unified: unified path set diverges "
            f"from union of split targets.\n"
            f"  cocotb paths: {sorted(cocotb_paths)!r}\n"
            f"  sva paths:    {sorted(sva_paths)!r}\n"
            f"  union:        {sorted(expected_union)!r}\n"
            f"  unified:      {sorted(unified_paths)!r}\n"
            f"  missing from unified: "
            f"{sorted(expected_union - unified_paths)!r}\n"
            f"  extra in unified:    "
            f"{sorted(unified_paths - expected_union)!r}"
        )


# ---------------------------------------------------------------------------
# Smoke test for the fixture vector JSON itself — guards against
# accidental damage to the seed vector.
# ---------------------------------------------------------------------------


def test_fixture_vector_json_is_well_formed():
    """The companion vector fixture parses as JSON and carries the
    SOS-03 §7.1 / SOS-08-D §6.2 fields the cocotb test will assert
    against once the emitter consumes vectors at codegen time."""
    assert FIXTURE_VECTOR.exists(), (
        f"fixture vector missing: {FIXTURE_VECTOR}"
    )
    payload = json.loads(FIXTURE_VECTOR.read_text(encoding="utf-8"))
    assert payload["id"] == "000-reset"
    assert isinstance(payload["steps"], list) and payload["steps"], (
        "fixture vector must carry at least one step"
    )
    for step in payload["steps"]:
        # SOS-03 §7.1 + SOS-08-D §10 reconciliation extension fields.
        for required in ("cycle", "name", "chart_state"):
            assert required in step, (
                f"fixture vector step missing required field `{required}`: "
                f"{step!r}"
            )
