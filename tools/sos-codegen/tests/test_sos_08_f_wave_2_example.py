# SPDX-License-Identifier: MIT
"""Structural tests for SOS-08-F wave-2 acceptance gate (e) worked example.

Validates that the ``examples/uvm_integration/`` tree closes acceptance
gates (e) end-to-end UVM 1.2 worked example and (f) injected-violation
chart-vocabulary check per ``SOS-08-F-CONCEPTS.md`` §12. These tests are
static structural checks — no simulator is invoked. The acceptance
gates themselves are about the example being authored + runnable on
any UVM 1.2-capable simulator; vendor binaries are customer-owned per
INV-S-HDL-F-2.

The tests assert:

* The expected file tree exists.
* The customer scaffolding imports ``sos_uvm_seq_pkg`` (§6.5 step 1).
* The sequencer is typed on ``sos_seq_item`` (§6.5 step 2).
* The driver implements a customer-side ``uvm_driver`` (§6.5 step 3 +
  INV-S-HDL-F-2).
* The test class instantiates a per-family SOS sequence, assigns
  ``vector_path``, and calls ``seq.start(...)`` (§6.5 step 4).
* The scoreboard renders chart-vocabulary failure messages in the
  ``[SOS-SEQ] state=...`` shape (§6.6 + INV-S-HDL-F-3).
* The example tree contains no ``assert property`` or ``bind``
  directive (INV-S-HDL-F-4 — SVA is sibling SOS-08-D / SOS-08-E).
* The vector files parse per the strict §6.4 JSONL row schema.
* The violation vector deviates from the golden vector in at least one
  row (the deviation seeds the (f) chart-vocabulary error).
* The golden vector's row order is structurally well-formed (no
  consecutive duplicate ``(family, event_id, payload_data)`` triples
  on the same sem that would force the kernel into ``resp_ok=0``).
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

# ---------------------------------------------------------------------------
# Repo-root resolution. The test file lives at
#   tools/sos-codegen/tests/test_sos_08_f_wave_2_example.py
# so the repo root is three levels up.
# ---------------------------------------------------------------------------


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "uvm_integration"
TB_DIR = EXAMPLE_ROOT / "tb"
RTL_DIR = EXAMPLE_ROOT / "rtl"
VEC_DIR = EXAMPLE_ROOT / "vectors"


EXPECTED_FILES = (
    "README.md",
    "Makefile",
    "rtl/sos_kernel_dut.sv",
    "tb/sos_uvm_seq_pkg.sv",
    "tb/sos_uvm_seq_pkg.svh",
    "tb/sos_kernel_if.sv",
    "tb/sos_kernel_agent.sv",
    "tb/sos_kernel_scoreboard.sv",
    "tb/sos_kernel_env.sv",
    "tb/sos_kernel_test.sv",
    "tb/sos_kernel_tb_top.sv",
    "vectors/sem_chart_bound.jsonl",
    "vectors/sem_chart_violation.jsonl",
)


# ---------------------------------------------------------------------------
# File-tree existence
# ---------------------------------------------------------------------------


class TestWave2ExampleTreeShape:
    """Acceptance gate (e) — file tree exists at the documented paths."""

    @pytest.mark.parametrize("relpath", EXPECTED_FILES)
    def test_file_exists(self, relpath):
        path = EXAMPLE_ROOT / relpath
        assert path.is_file(), f"missing example artifact: {relpath}"

    def test_no_unexpected_top_level_files(self):
        # Allow the documented set + dotfiles + work/ build artifact.
        expected_top = {
            "README.md",
            "Makefile",
            "rtl",
            "tb",
            "vectors",
        }
        actual = {
            p.name
            for p in EXAMPLE_ROOT.iterdir()
            if not p.name.startswith(".") and p.name != "work"
        }
        assert actual == expected_top, (
            f"unexpected example-tree top-level entries: {actual - expected_top}, "
            f"missing: {expected_top - actual}"
        )


# ---------------------------------------------------------------------------
# §6.5 five-step customer-integration contract
# ---------------------------------------------------------------------------


class TestWave2FiveStepIntegrationContract:
    """Acceptance gate (e) — five-step contract is wired in the example."""

    def test_step_1_package_import(self):
        """§6.5 step 1 — package import in customer scaffolding."""
        for fname in ("sos_kernel_agent.sv", "sos_kernel_env.sv",
                      "sos_kernel_test.sv", "sos_kernel_tb_top.sv"):
            src = (TB_DIR / fname).read_text()
            assert "import sos_uvm_seq_pkg::*;" in src, (
                f"{fname} missing `import sos_uvm_seq_pkg::*;`"
            )

    def test_step_2_sequencer_typedef(self):
        """§6.5 step 2 — uvm_sequencer typedef parameterised on sos_seq_item."""
        src = (TB_DIR / "sos_kernel_agent.sv").read_text()
        assert re.search(
            r"typedef\s+uvm_sequencer\s*#\s*\(\s*sos_seq_item\s*\)",
            src,
        ), "agent missing sequencer typedef parameterised on sos_seq_item"

    def test_step_3_customer_driver_class(self):
        """§6.5 step 3 + INV-S-HDL-F-2 — customer-side driver class."""
        src = (TB_DIR / "sos_kernel_agent.sv").read_text()
        assert re.search(
            r"class\s+sos_kernel_driver\s+extends\s+uvm_driver\s*#\s*\(\s*sos_seq_item\s*\)",
            src,
        ), "missing customer-side uvm_driver #(sos_seq_item) subclass"

    def test_step_4_sequence_start(self):
        """§6.5 step 4 — test class wires vector_path + invokes start()."""
        src = (TB_DIR / "sos_kernel_test.sv").read_text()
        assert "sos_sem_sequence" in src, "test must instantiate a per-family SOS sequence"
        assert re.search(
            r"sos_sem_sequence::type_id::create\b",
            src,
        ), "test must construct sequence via factory create()"
        assert re.search(
            r"\.vector_path\s*=", src,
        ), "test must assign sequence.vector_path"
        assert re.search(
            r"\.start\s*\(",
            src,
        ), "test must call seq.start(...) against the sequencer"

    def test_step_5_chart_vocab_failure_format(self):
        """§6.5 step 5 + §6.6 — scoreboard renders chart vocabulary
        in failure messages."""
        src = (TB_DIR / "sos_kernel_scoreboard.sv").read_text()
        # The literal SOS-SEQ tag plus the chart-vocabulary field names
        # MUST appear inside the scoreboard's uvm_error format strings.
        assert "[SOS-SEQ]" in src
        assert "state=%s" in src
        assert "transition=%0d" in src
        assert "invariant=%0d" in src
        assert "family=%s" in src
        assert "event=%0d" in src
        # And it MUST be inside a uvm_error call (not just narrative).
        assert re.search(
            r"`uvm_error\s*\(\s*\"SBD\"\s*,",
            src,
        ), "chart-vocab error must be emitted via `uvm_error("


# ---------------------------------------------------------------------------
# INV-S-HDL-F-4 — no SVA emission anywhere in the example tree
# ---------------------------------------------------------------------------


class TestWave2InvF4NoSva:
    """INV-S-HDL-F-4 — example tree contains no SVA / bind directives."""

    @pytest.fixture
    def all_sv_text(self):
        bodies = []
        for path in EXAMPLE_ROOT.rglob("*.sv"):
            bodies.append((path, path.read_text()))
        return bodies

    def test_no_assert_property(self, all_sv_text):
        for path, src in all_sv_text:
            # Strip line comments to avoid false positives on commentary.
            stripped = re.sub(r"//.*$", "", src, flags=re.MULTILINE)
            assert not re.search(r"\bassert\s+property\b", stripped), (
                f"{path.relative_to(EXAMPLE_ROOT)} contains `assert property` "
                "— INV-S-HDL-F-4 reserves SVA for sibling SOS-08-D / SOS-08-E"
            )

    def test_no_bind_directive(self, all_sv_text):
        for path, src in all_sv_text:
            stripped = re.sub(r"//.*$", "", src, flags=re.MULTILINE)
            # Bind statements are `bind <module>` at statement position.
            assert not re.search(
                r"^\s*bind\s+\w+",
                stripped,
                flags=re.MULTILINE,
            ), (
                f"{path.relative_to(EXAMPLE_ROOT)} contains `bind ...` "
                "directive — INV-S-HDL-F-4 forbids SVA binding in this "
                "sub-phase"
            )


# ---------------------------------------------------------------------------
# Vector-IR schema conformance — §6.4 JSONL row schema
# ---------------------------------------------------------------------------


REQUIRED_VECTOR_KEYS = (
    "event_id",
    "payload_data",
    "chart_state",
    "transition_id",
    "invariant_id",
)


def _parse_vector(path: pathlib.Path):
    rows = []
    for ln_no, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"{path.name} line {ln_no} is not valid JSON: {exc}: {line!r}"
            )
        rows.append((ln_no, obj))
    return rows


class TestWave2VectorIrSchema:
    """§6.4 JSONL row schema conformance for both vectors."""

    @pytest.mark.parametrize(
        "vector_name",
        ("sem_chart_bound.jsonl", "sem_chart_violation.jsonl"),
    )
    def test_every_row_has_required_keys(self, vector_name):
        rows = _parse_vector(VEC_DIR / vector_name)
        assert rows, f"{vector_name} is empty — vectors must carry ≥1 event"
        for ln_no, row in rows:
            for key in REQUIRED_VECTOR_KEYS:
                assert key in row, (
                    f"{vector_name} line {ln_no} missing required key "
                    f"`{key}` per §6.4 schema"
                )

    @pytest.mark.parametrize(
        "vector_name",
        ("sem_chart_bound.jsonl", "sem_chart_violation.jsonl"),
    )
    def test_field_types_match_struct(self, vector_name):
        """Per §6.4 the row maps 1:1 to ``sos_chart_event_s`` —
        integers for ids and payload_data, string for chart_state."""
        rows = _parse_vector(VEC_DIR / vector_name)
        for ln_no, row in rows:
            assert isinstance(row["event_id"], int)
            assert isinstance(row["payload_data"], int)
            assert isinstance(row["chart_state"], str)
            assert isinstance(row["transition_id"], int)
            assert isinstance(row["invariant_id"], int)

    @pytest.mark.parametrize(
        "vector_name",
        ("sem_chart_bound.jsonl", "sem_chart_violation.jsonl"),
    )
    def test_chart_state_non_empty(self, vector_name):
        """INV-S-HDL-F-3 — every chart-vocabulary metadata field must
        carry usable identifier content (the scoreboard renders it)."""
        rows = _parse_vector(VEC_DIR / vector_name)
        for ln_no, row in rows:
            assert row["chart_state"], (
                f"{vector_name} line {ln_no} has empty chart_state"
            )


class TestWave2GateFInjectedViolation:
    """Acceptance gate (f) — violation vector deviates from golden in
    a way that the synthetic kernel detects + the scoreboard surfaces in
    chart vocabulary."""

    def test_violation_vector_has_double_take(self):
        """The mutated vector contains a sem.take(0) without an
        intervening sem.give(0). The synthetic DUT (NUM_SEMS=2)
        returns resp_ok=0 on the double-take."""
        rows = _parse_vector(VEC_DIR / "sem_chart_violation.jsonl")
        # event_id encoding: 0=create, 1=delete, 2=take, 3=give.
        SEM_TAKE = 2
        SEM_GIVE = 3
        held = set()
        saw_violation = False
        for ln_no, row in rows:
            ev = row["event_id"]
            sid = row["payload_data"]
            if ev == SEM_TAKE:
                if sid in held:
                    saw_violation = True
                    # The mutated row carries a distinct chart_state +
                    # invariant tag so the failure message renders the
                    # mutated vocabulary, not the golden one.
                    assert "illegal" in row["chart_state"].lower()
                    assert row["invariant_id"] != 7, (
                        "violation row should change invariant_id from "
                        "the golden value to make the chart-vocab "
                        "deviation visible in the uvm_error string"
                    )
                else:
                    held.add(sid)
            elif ev == SEM_GIVE:
                held.discard(sid)
        assert saw_violation, (
            "violation vector must include a double-take on the same "
            "sem to exercise gate (f) chart-vocab error path"
        )

    def test_golden_vector_is_clean(self):
        """The golden vector must NOT contain a double-take — the
        end-to-end golden run is expected to produce zero
        UVM_ERROR per (e)."""
        rows = _parse_vector(VEC_DIR / "sem_chart_bound.jsonl")
        SEM_TAKE = 2
        SEM_GIVE = 3
        SEM_CREATE = 0
        held = set()
        for ln_no, row in rows:
            ev = row["event_id"]
            sid = row["payload_data"]
            if ev == SEM_TAKE:
                assert sid not in held, (
                    f"golden vector line {ln_no}: double-take on sem "
                    f"{sid} — would force a UVM_ERROR on the (e) run"
                )
                held.add(sid)
            elif ev == SEM_GIVE:
                assert sid in held, (
                    f"golden vector line {ln_no}: give-without-take on "
                    f"sem {sid} — would force a UVM_ERROR on the (e) run"
                )
                held.discard(sid)
            elif ev == SEM_CREATE:
                pass  # creation does not affect held set.

    def test_violation_diff_from_golden(self):
        """The violation file must differ from the golden file — both
        carry chart_state strings that distinguish them in the failure
        message."""
        golden = (VEC_DIR / "sem_chart_bound.jsonl").read_text()
        violation = (VEC_DIR / "sem_chart_violation.jsonl").read_text()
        assert golden != violation


# ---------------------------------------------------------------------------
# sos_uvm_seq_pkg.sv — sample copy is consistent with the walker
# ---------------------------------------------------------------------------


class TestWave2SampleSosPkgMatchesWalker:
    """Sanity: the sample copy of ``sos_uvm_seq_pkg.sv`` in ``tb/``
    matches what the SOS-08-F walker currently emits for
    ``chart_name="rtos_kernel"``. ``make regen`` re-emits the file;
    this test catches drift if a developer hand-edits the sample."""

    def test_sample_pkg_byte_identical_to_walker_output(self):
        import sys
        sos_codegen = REPO_ROOT / "tools" / "sos-codegen"
        sys.path.insert(0, str(sos_codegen))
        try:
            from transliterate_hdl_uvm_seq import render_target  # noqa
        finally:
            sys.path.pop(0)
        files = render_target({}, {"chart_name": "rtos_kernel"})
        sample = (TB_DIR / "sos_uvm_seq_pkg.sv").read_text()
        expected = files["uvm/rtos_kernel/sos_uvm_seq_pkg.sv"]
        assert sample == expected, (
            "tb/sos_uvm_seq_pkg.sv has drifted from walker output; "
            "run `make regen` from examples/uvm_integration/ to refresh"
        )

    def test_sample_svh_byte_identical_to_walker_output(self):
        import sys
        sos_codegen = REPO_ROOT / "tools" / "sos-codegen"
        sys.path.insert(0, str(sos_codegen))
        try:
            from transliterate_hdl_uvm_seq import render_target  # noqa
        finally:
            sys.path.pop(0)
        files = render_target({}, {"chart_name": "rtos_kernel"})
        sample = (TB_DIR / "sos_uvm_seq_pkg.svh").read_text()
        expected = files["uvm/rtos_kernel/sos_uvm_seq_pkg.svh"]
        assert sample == expected, (
            "tb/sos_uvm_seq_pkg.svh has drifted from walker output; "
            "run `make regen` from examples/uvm_integration/ to refresh"
        )


# ---------------------------------------------------------------------------
# DUT alignment with sample vectors — semantic sanity
# ---------------------------------------------------------------------------


class TestWave2DutVectorAlignment:
    """The synthetic DUT detects the double-take pattern. The example's
    correctness hinges on this — these tests ensure the encoding
    contract is documented in BOTH the DUT and the vector files."""

    def test_dut_family_sem_encoding_is_3_d1(self):
        """The DUT uses ``localparam FAMILY_SEM = 3'd1;`` — matches
        ``SOS_FAMILY_SEM`` ordinal 1 in ``sos_event_family_e`` enum."""
        src = (RTL_DIR / "sos_kernel_dut.sv").read_text()
        assert re.search(
            r"FAMILY_SEM\s*=\s*3'd1\b", src,
        ), "DUT FAMILY_SEM ordinal must equal SOS_FAMILY_SEM (= 1)"

    def test_dut_sem_take_encoding_is_8_d2(self):
        """Acceptance gate (f) hinges on the DUT recognising
        ``event_id=2`` as sem.take — keep encoding pinned."""
        src = (RTL_DIR / "sos_kernel_dut.sv").read_text()
        assert re.search(r"SEM_TAKE\s*=\s*8'd2\b", src)
        assert re.search(r"SEM_GIVE\s*=\s*8'd3\b", src)
