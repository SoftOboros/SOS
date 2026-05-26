"""Tests for the SOS-09-D Rust HAL channel-emit subset.

@spec  docs/concepts/SOS-09-D-CONCEPTS.md (🟢 RATIFIED 2026-05-26)
@spec  docs/concepts/SOS-09-A-CONCEPTS.md §5.2 — twelve-key annotation set.
@spec  docs/concepts/SOS-09-B-CONCEPTS.md §5 — SVD address-offset chain
       that SOS-09-D's RegisterBlock layout MUST match (INV-S-MEM-D-5).

Covers the §9 / §12 acceptance gates (b)..(k):

  (b) walker presence: `emit_rust_hal()` produces the file map.
  (c) RegisterBlock layout: offsets match SVD `<addressOffset>` chain.
  (d) newtype family completeness: at least one channel per `sos:kind`
      + at least one per side-effect / clear-on-read variant.
  (e) type-state-for-shared: a `compile_fail` doctest snippet exercising
      `Shared<T>` mis-use. (Validated via Rust-source pattern assertion
      when `cargo` is not available; the `trybuild`-style compile-fail
      crate is documented as a deferred ECP5 follow-up.)
  (f) `cargo check` clean: skipped with reason when `cargo` not on PATH.
  (g) `*_unchecked` discharge: at least one `_unchecked` accessor with
      a SAFETY comment naming INV-SOS-G + the channel's `sos:id`.
  (h) MPU-region constant export: per-channel `SOS_MPU_*_REGION` consts.
  (i) `sos:name`-determinism: two charts differing only in `sos:id`
      UUIDs produce byte-identical Rust symbol names (modulo doc
      comments — which are the documented variation surface).
  (j)/(k) invariant citation + umbrella INV-S-MEM-* satisfaction:
      verified by emitted `@spec` / `INV-S-MEM-D-*` references.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make sos-codegen modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos09_annotations import (  # noqa: E402
    BitField,
    BitLayout,
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)
from transliterate_rust import (  # noqa: E402
    _RUST_HAL_PRELUDE,
    _channel_screaming_name,
    _hal_channel_size_bytes,
    _register_block_name,
    _rust_width_type,
    _select_wrapper,
    emit_rust_hal,
    emit_rust_hal_from_chart,
    write_rust_hal_crate,
)
from transliterate_svd import (  # noqa: E402
    _channel_size_bytes as _svd_channel_size_bytes,
    emit_svd,
)


_FIXTURE_DIR = _TOOLS_DIR / "tests" / "fixtures" / "sos_09_d"
_FIXTURE_MAIN = _FIXTURE_DIR / "worked_example.scxml"
_FIXTURE_ALT_IDS = _FIXTURE_DIR / "worked_example_alt_ids.scxml"


# ---------------------------------------------------------------------------
# Direct ChannelAnnotation builders (mirror test_transliterate_svd shape).
# ---------------------------------------------------------------------------


def _uuid(n: int) -> str:
    return f"8b000000-0000-4000-8000-0000000000{n:02x}"


def _make_annotations_from_channels(
    channels: list[ChannelAnnotation],
) -> ChartAnnotations:
    return ChartAnnotations(channels=tuple(channels))


def _status_channel(name: str, *, width: int = 32,
                    clear_on_read: bool = False,
                    irq: str | None = None,
                    n: int = 1) -> ChannelAnnotation:
    bit_layout = None
    if clear_on_read:
        bit_layout = BitLayout(fields=(
            BitField(name="ready", start_bit=0, width=1, access="RO",
                     side_effect="clear-on-read", reset_value=0),
        ))
    return ChannelAnnotation(
        id=_uuid(n), name=name, kind="status", dir="hw→sw",
        width=width, bit_layout=bit_layout, irq=irq,
    )


def _command_channel(name: str, *, width: int = 32,
                     side_effect: bool = False, n: int = 2) -> ChannelAnnotation:
    bit_layout = None
    if side_effect:
        bit_layout = BitLayout(fields=(
            BitField(name="start", start_bit=0, width=1, access="WO",
                     side_effect="side-effect-on-write", reset_value=0),
        ))
    return ChannelAnnotation(
        id=_uuid(n), name=name, kind="command", dir="sw→hw",
        width=width, bit_layout=bit_layout,
    )


def _queue_channel(name: str, *, n: int = 3) -> ChannelAnnotation:
    return ChannelAnnotation(
        id=_uuid(n), name=name, kind="queue", dir="bidirectional",
        atomicity="atomic", width=32,
    )


def _shared_channel(name: str, *, n: int = 4,
                    zone: str = "privileged",
                    mpu_attr: str | None = None) -> ChannelAnnotation:
    return ChannelAnnotation(
        id=_uuid(n), name=name, kind="shared", dir="bidirectional",
        atomicity="mutex-required", width=32, mutex="shared_lock",
        zone=zone, mpu_attr=mpu_attr,
    )


# ---------------------------------------------------------------------------
# Gate (b): emitter presence + Cargo manifest shape
# ---------------------------------------------------------------------------


class TestGateB_EmitterPresence:
    """`emit_rust_hal()` produces a non-empty file map for a worked-example."""

    def test_emit_returns_cargo_and_lib(self) -> None:
        annotations = _make_annotations_from_channels([
            _status_channel("rx_status", clear_on_read=True, n=1),
            _command_channel("tx_command", side_effect=True, n=2),
            _status_channel("plain_status", irq="plain_irq", n=3),
            _command_channel("plain_command", n=4),
            _queue_channel("io_queue", n=5),
            _shared_channel("shared_block", n=6),
        ])
        files = emit_rust_hal(annotations, crate_name="sos09d_smoke")
        assert "Cargo.toml" in files
        assert "src/lib.rs" in files
        assert "[package]" in files["Cargo.toml"]
        assert "name = 'sos09d_smoke'" in files["Cargo.toml"] or \
               'name = "sos09d_smoke"' in files["Cargo.toml"]
        # cortex_m feature default-on (PCDN-D-004 (b))
        assert "default = [\"cortex_m\"]" in files["Cargo.toml"]
        # vcell + cortex-m optional (PCDN-D-001 + D-004)
        assert "vcell" in files["Cargo.toml"]
        assert 'cortex-m = { version' in files["Cargo.toml"]

    def test_lib_rs_is_no_std(self) -> None:
        annotations = _make_annotations_from_channels([
            _status_channel("rx_status", n=1),
        ])
        files = emit_rust_hal(annotations, crate_name="sos09d_nostd")
        assert "#![no_std]" in files["src/lib.rs"]

    def test_emit_from_chart_path(self) -> None:
        """`emit_rust_hal_from_chart` round-trips the worked-example fixture."""
        files = emit_rust_hal_from_chart(
            _FIXTURE_MAIN, crate_name="sos09d_fixture",
        )
        assert "Cargo.toml" in files and "src/lib.rs" in files
        assert "RegisterBlock" in files["src/lib.rs"]


# ---------------------------------------------------------------------------
# Gate (c): RegisterBlock layout matches SVD <addressOffset> chain
# ---------------------------------------------------------------------------


class TestGateC_LayoutMatchesSVD:
    """INV-S-MEM-D-5: emitted offsets match the SVD chain bit-for-bit."""

    @pytest.fixture
    def annotations(self) -> ChartAnnotations:
        return _make_annotations_from_channels([
            _status_channel("rx_status", clear_on_read=True, n=1),
            _command_channel("tx_command", side_effect=True, n=2),
            _status_channel("plain_status", n=3),
            _queue_channel("io_queue", n=5),
            _shared_channel("shared_block", n=6),
        ])

    def test_hal_size_matches_svd_size(self, annotations: ChartAnnotations) -> None:
        for ch in annotations.channels:
            assert _hal_channel_size_bytes(ch.width) == _svd_channel_size_bytes(ch.width), (
                f"HAL byte size for sos:width={ch.width} drifted from SVD"
            )

    def test_register_block_field_offset_chain(
        self, annotations: ChartAnnotations,
    ) -> None:
        files = emit_rust_hal(annotations, crate_name="sos09d_layout")
        lib = files["src/lib.rs"]
        # Each emitted offset_of! assert names the expected offset.
        cursor = 0
        for ch in annotations.channels:
            expected_off = cursor
            cursor += _hal_channel_size_bytes(ch.width)
            assert (
                f"core::mem::offset_of!(RegisterBlock, {ch.name}) == 0x{expected_off:X}usize"
                in lib
            ), (
                f"INV-S-MEM-D-5: missing offset_of! assertion for "
                f"{ch.name} @ 0x{expected_off:X}"
            )

    def test_layout_matches_svd_emit(self, annotations: ChartAnnotations) -> None:
        """Emit SVD + HAL from the same annotations; their byte chains match."""
        svd = emit_svd(annotations, device_name="sos09d_layout")
        files = emit_rust_hal(annotations, crate_name="sos09d_layout")
        lib = files["src/lib.rs"]
        # Extract every <name>X</name>...<addressOffset>Y</addressOffset>
        # pair from the SVD. Then check the corresponding Rust offset_of!
        # assertion is present.
        svd_pairs = re.findall(
            r"<name>([a-zA-Z_][a-zA-Z0-9_]*)</name>\s*"
            r"<description>[^<]*</description>\s*"
            r"<addressOffset>0x([0-9A-Fa-f]+)</addressOffset>",
            svd,
        )
        # Filter to channel names (peripheral name appears too).
        channel_names = {ch.name for ch in annotations.channels}
        channel_pairs = [(n, int(o, 16)) for n, o in svd_pairs if n in channel_names]
        assert len(channel_pairs) == len(annotations.channels), (
            "Expected one SVD register per channel; got "
            f"{channel_pairs}"
        )
        for name, offset in channel_pairs:
            assert (
                f"core::mem::offset_of!(RegisterBlock, {name}) == 0x{offset:X}usize"
                in lib
            ), f"INV-S-MEM-D-5 drift: {name} SVD offset 0x{offset:X} not in HAL"


# ---------------------------------------------------------------------------
# Gate (d): newtype family completeness
# ---------------------------------------------------------------------------


class TestGateD_NewtypeFamilyCompleteness:
    """One newtype per `sos:kind` + per side-effect / clear-on-read variant."""

    def test_wrapper_selection_per_kind(self) -> None:
        cases = [
            (_status_channel("a", n=1),                    "Status"),
            (_status_channel("b", clear_on_read=True, n=2), "ClearOnRead"),
            (_command_channel("c", n=3),                   "Command"),
            (_command_channel("d", side_effect=True, n=4), "FireOnWrite"),
            (_queue_channel("e", n=5),                     "Queue"),
            (_shared_channel("f", n=6),                    "Shared"),
        ]
        for ch, expected_wrapper in cases:
            assert _select_wrapper(ch) == expected_wrapper, (
                f"wrong wrapper for kind={ch.kind} name={ch.name}: "
                f"expected {expected_wrapper}, got {_select_wrapper(ch)}"
            )

    def test_all_six_wrappers_in_prelude(self) -> None:
        for wrapper in (
            "pub enum ContentionError",
            "pub struct Status<T: Copy>",
            "pub struct Command<T: Copy>",
            "pub struct ClearOnRead<T: Copy>",
            "pub struct FireOnWrite<T: Copy>",
            "pub struct Queue<T: Copy>",
            "pub struct Shared<T: Copy>",
            "pub struct Claimed<'a, T: Copy>",
        ):
            assert wrapper in _RUST_HAL_PRELUDE, (
                f"§5.2 wrapper missing from prelude: {wrapper}"
            )

    def test_status_has_read_no_fire(self) -> None:
        """INV-S-MEM-D-3 specialised: Status has `read`, not `fire`."""
        prelude = _RUST_HAL_PRELUDE
        status_impl = prelude.split("impl<T: Copy> Status<T>")[1].split("}")[0]
        assert "pub fn read(" in status_impl
        assert " fire(" not in status_impl

    def test_command_has_fire_no_read(self) -> None:
        """INV-S-MEM-D-3: Command exposes only `fire`."""
        prelude = _RUST_HAL_PRELUDE
        command_impl = prelude.split("impl<T: Copy> Command<T>")[1].split("}")[0]
        assert "pub fn fire(" in command_impl
        assert " pub fn read(" not in command_impl

    def test_clear_on_read_has_consume_no_read(self) -> None:
        """INV-S-MEM-D-2: ClearOnRead exposes `consume` (&mut), no `read`."""
        prelude = _RUST_HAL_PRELUDE
        cor_impl = prelude.split("impl<T: Copy> ClearOnRead<T>")[1].split("}")[0]
        assert "pub fn consume(" in cor_impl
        assert "&mut self" in cor_impl
        # The wrapper exposes NO read method.
        assert " pub fn read(" not in cor_impl

    def test_all_wrappers_emitted_for_worked_example(self) -> None:
        annotations = _make_annotations_from_channels([
            _status_channel("rx_status", clear_on_read=True, n=1),
            _command_channel("tx_command", side_effect=True, n=2),
            _status_channel("plain_status", n=3),
            _command_channel("plain_command", n=4),
            _queue_channel("io_queue", n=5),
            _shared_channel("shared_block", n=6),
        ])
        files = emit_rust_hal(annotations, crate_name="sos09d_d")
        lib = files["src/lib.rs"]
        # Field declarations on the RegisterBlock pick the right wrapper.
        assert "pub rx_status: ClearOnRead<u32>" in lib
        assert "pub tx_command: FireOnWrite<u32>" in lib
        assert "pub plain_status: Status<u32>" in lib
        assert "pub plain_command: Command<u32>" in lib
        assert "pub io_queue: Queue<u32>" in lib
        assert "pub shared_block: Shared<u32>" in lib


# ---------------------------------------------------------------------------
# Gate (e): type-state-for-shared
# ---------------------------------------------------------------------------


class TestGateE_TypeStateForShared:
    """`Shared<T>` exposes only `claim()` + `try_claim()`; the typed region
    is reachable only through `Claimed<'_, T>`. §5.3."""

    def test_shared_has_claim_returning_result(self) -> None:
        prelude = _RUST_HAL_PRELUDE
        shared_impl = prelude.split("impl<T: Copy> Shared<T>")[1].split("\n}\n")[0]
        # claim() -> Result<Claimed<'_, T>, ContentionError>
        assert (
            "pub fn claim(&mut self) -> Result<Claimed<'_, T>, ContentionError>"
            in shared_impl
        )
        # try_claim() -> Option<Claimed<'_, T>>
        assert "pub fn try_claim(&mut self) -> Option<Claimed<'_, T>>" in shared_impl

    def test_shared_does_not_expose_read_or_write(self) -> None:
        """The typed region is reachable only through Claimed."""
        prelude = _RUST_HAL_PRELUDE
        shared_impl = prelude.split("impl<T: Copy> Shared<T>")[1].split("\n}\n")[0]
        # No `read` or `write` accessor on Shared itself.
        assert " pub fn read(" not in shared_impl
        assert " pub fn write(" not in shared_impl

    def test_claimed_has_read_write_modify(self) -> None:
        prelude = _RUST_HAL_PRELUDE
        claimed_impl = prelude.split("impl<'a, T: Copy> Claimed<'a, T>")[1].split("\n}\n")[0]
        assert "pub fn read(" in claimed_impl
        assert "pub fn write(" in claimed_impl
        assert "pub fn modify<F: FnOnce(&mut T)>" in claimed_impl

    def test_claimed_drop_implemented(self) -> None:
        prelude = _RUST_HAL_PRELUDE
        assert "impl<'a, T: Copy> Drop for Claimed<'a, T>" in prelude
        assert "fn drop(&mut self)" in prelude

    def test_contention_error_non_exhaustive_single_variant(self) -> None:
        """PCDN-D-003 (b): `#[non_exhaustive] enum ContentionError`."""
        prelude = _RUST_HAL_PRELUDE
        # Find the ContentionError block.
        block = prelude.split("pub enum ContentionError")[1].split("}")[0]
        assert "#[non_exhaustive]" in prelude.split("pub enum ContentionError")[0][-200:]
        assert "LockHeldElsewhere" in block

    def test_compile_fail_doctest_pattern_present(self) -> None:
        """The emitter encodes the type-state guarantee in the prelude shape;
        a separate `trybuild` crate is a deferred ECP5 follow-up.

        v1 verification: assert the structural shape that MAKES the
        compile-fail expectation true — `Shared` has no direct `write`,
        `Claimed` carries a `&'a mut Shared<T>`, `claim()` returns the
        guard. The borrow-checker reads `let mut s = Shared { ... }; s.claim()?;
        s.write(...)` as "no method `write` on `Shared<u32>`", which is
        exactly the §9 (c) gate.
        """
        # The negative-compile pattern: Shared has no `write` method.
        prelude = _RUST_HAL_PRELUDE
        # This is the load-bearing structural guarantee for the
        # compile-fail expectation.
        assert "impl<T: Copy> Shared<T> {" in prelude
        shared_block = prelude.split("impl<T: Copy> Shared<T> {")[1].split("\n}\n")[0]
        # Only claim / try_claim are public on Shared.
        public_methods = re.findall(r"pub fn (\w+)\s*\(", shared_block)
        assert set(public_methods) == {"claim", "try_claim"}, (
            f"Shared<T> public methods drifted from §5.3: {public_methods}"
        )


# ---------------------------------------------------------------------------
# Gate (f): cargo check clean (skip if cargo not on PATH)
# ---------------------------------------------------------------------------


class TestGateF_CargoCheck:
    """Emitted crates pass `cargo check --no-default-features
    --target thumbv7em-none-eabihf`. SKIP if cargo not on PATH."""

    @pytest.fixture
    def emitted_crate(self, tmp_path: Path) -> Path:
        annotations = parse_chart_annotations_from_fixture(_FIXTURE_MAIN)
        out = tmp_path / "crate"
        write_rust_hal_crate(
            annotations, crate_name="sos09d_check",
            output_dir=out, base_address=0x40000000,
        )
        return out

    def test_cargo_check_clean(self, emitted_crate: Path) -> None:
        cargo = shutil.which("cargo")
        if cargo is None:
            pytest.skip("cargo not on PATH; gate (f) skipped (INV-S-MEM-D-4 deferred)")
        # First try `cargo check --no-default-features --target ...`
        proc = subprocess.run(
            [cargo, "check", "--no-default-features",
             "--target", "thumbv7em-none-eabihf"],
            cwd=emitted_crate,
            capture_output=True, text=True,
            timeout=240,
            env={
                **__import__("os").environ,
                "RUSTFLAGS": "",
                "CARGO_TARGET_DIR": str(emitted_crate / "target"),
            },
        )
        if proc.returncode != 0:
            # Surface stderr so the failure is auditable.
            pytest.fail(
                "cargo check failed (INV-S-MEM-D-4 / gate (f)):\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )


def parse_chart_annotations_from_fixture(path: Path) -> ChartAnnotations:
    """Mirror of test_transliterate_svd's fixture-loader.

    Uses the `loader` module (SOS-08-A) to materialise the chart, then
    `parse_chart_annotations` (SOS-09-A) to build the annotation model.
    """
    from loader import load_chart
    ast = load_chart(path)
    assert ast.raw_scjson is not None, f"loader returned no raw_scjson for {path}"
    return parse_chart_annotations(ast.raw_scjson)


# ---------------------------------------------------------------------------
# Gate (g): *_unchecked discharge with SAFETY comment
# ---------------------------------------------------------------------------


class TestGateG_UncheckedDischarge:
    """At least one `_unchecked` accessor is emitted with a SAFETY
    comment naming the discharging chart invariant (INV-SOS-G + sos:id)."""

    def test_at_least_one_unchecked_emitted(self) -> None:
        annotations = _make_annotations_from_channels([
            _status_channel("rx_status", n=1),
            _command_channel("tx_command", n=2),
        ])
        files = emit_rust_hal(annotations, crate_name="sos09d_g")
        lib = files["src/lib.rs"]
        # Either a `*_read_unchecked` or `*_consume_unchecked` MUST exist.
        assert (
            "rx_status_read_unchecked" in lib
        ), "gate (g): expected `_unchecked` accessor for status channel"

    def test_unchecked_is_unsafe_fn(self) -> None:
        annotations = _make_annotations_from_channels([
            _status_channel("rx_status", n=1),
        ])
        files = emit_rust_hal(annotations, crate_name="sos09d_g")
        lib = files["src/lib.rs"]
        # PCDN-SOS-09-D-005 accepted option (a): `unsafe fn`.
        assert (
            re.search(
                r"pub unsafe fn rx_status_read_unchecked\(",
                lib,
            )
        ), "gate (g): `_unchecked` accessor MUST be `unsafe fn` per PCDN-D-005 (a)"

    def test_safety_comment_names_inv_sos_g_and_sos_id(self) -> None:
        annotations = _make_annotations_from_channels([
            _status_channel("rx_status", n=1),
        ])
        files = emit_rust_hal(annotations, crate_name="sos09d_g")
        lib = files["src/lib.rs"]
        # The SAFETY comment names INV-SOS-G + the channel's sos:id.
        assert "SAFETY: discharged by chart invariant" in lib
        assert "INV-SOS-G" in lib
        assert _uuid(1) in lib

    def test_no_status_channels_documents_reduced_conformance(self) -> None:
        """Gate (g) second-tier conformance (§12): a chart with no status
        channels documents the absence of `_unchecked` accessors."""
        annotations = _make_annotations_from_channels([
            _command_channel("only_command", n=10),
            _queue_channel("only_queue", n=11),
        ])
        files = emit_rust_hal(annotations, crate_name="sos09d_no_status")
        lib = files["src/lib.rs"]
        # No actual `unsafe fn *_unchecked` accessor is emitted (only the
        # banner / header comment block survives).
        assert "pub unsafe fn" not in lib, (
            "gate (g) reduced conformance: no `_unchecked` accessor"
            " should be emitted when chart has no status channels"
        )
        # The reduced-conformance marker is present.
        assert "reduced conformance" in lib or "second tier" in lib


# ---------------------------------------------------------------------------
# Gate (h): MPU-region constant export
# ---------------------------------------------------------------------------


class TestGateH_MPUConstantExport:
    """Per channel with `sos:zone` (non-default) or `sos:mpu_attr`, emit
    a `pub const SOS_MPU_<NAME>_REGION: sos_mpu_region_t = ...;`."""

    def test_mpu_const_for_explicit_zone(self) -> None:
        ch = _shared_channel(
            "shared_block", n=6, zone="unprivileged",
        )
        annotations = _make_annotations_from_channels([ch])
        files = emit_rust_hal(annotations, crate_name="sos09d_h_zone")
        lib = files["src/lib.rs"]
        assert "pub const SOS_MPU_SHARED_BLOCK_REGION: sos_mpu_region_t" in lib

    def test_mpu_const_for_mpu_attr(self) -> None:
        ch = _status_channel("plain_status", n=3, irq="plain_irq")
        ch = ChannelAnnotation(
            id=ch.id, name=ch.name, kind=ch.kind, dir=ch.dir,
            width=ch.width, zone=ch.zone, atomicity=ch.atomicity,
            mpu_attr="device_ngnrne", irq=ch.irq,
        )
        annotations = _make_annotations_from_channels([ch])
        files = emit_rust_hal(annotations, crate_name="sos09d_h_attr")
        lib = files["src/lib.rs"]
        assert "pub const SOS_MPU_PLAIN_STATUS_REGION: sos_mpu_region_t" in lib
        # Encoding: device_ngnrne → attr=2.
        assert re.search(
            r"SOS_MPU_PLAIN_STATUS_REGION.*?attr: 2,",
            lib, re.DOTALL,
        )

    def test_no_mpu_const_for_default_zone_only(self) -> None:
        ch = _status_channel("plain_status", n=3)  # zone defaults to privileged
        annotations = _make_annotations_from_channels([ch])
        files = emit_rust_hal(annotations, crate_name="sos09d_h_default")
        lib = files["src/lib.rs"]
        assert "SOS_MPU_PLAIN_STATUS_REGION" not in lib

    def test_const_name_is_screaming_snake_case(self) -> None:
        for ch_name, expected in (
            ("rx_status",    "RX_STATUS"),
            ("plain_status", "PLAIN_STATUS"),
            ("io_queue",     "IO_QUEUE"),
        ):
            ch = _shared_channel(ch_name, n=10, zone="unprivileged")
            assert _channel_screaming_name(ch) == expected

    def test_mpu_const_carries_base_addr_size(self) -> None:
        ch = _shared_channel("shared_block", n=6, zone="unprivileged")
        annotations = _make_annotations_from_channels([ch])
        files = emit_rust_hal(annotations, crate_name="sos09d_h_addr",
                              base_address=0x40000000)
        lib = files["src/lib.rs"]
        # base_addr is base + cumulative-offset (0 for the only channel).
        assert "base_addr: 0x40000000" in lib
        assert "size: 4" in lib  # 32-bit → 4 bytes


# ---------------------------------------------------------------------------
# Gate (i): sos:name-determinism
# ---------------------------------------------------------------------------


class TestGateI_NameDeterminism:
    """Two charts differing only in `sos:id` UUIDs produce byte-identical
    Rust symbol names (modulo the documented sos:id-bearing comments)."""

    def test_two_runs_byte_identical(self) -> None:
        annotations = _make_annotations_from_channels([
            _status_channel("rx_status", n=1),
            _command_channel("tx_command", n=2),
        ])
        files1 = emit_rust_hal(annotations, crate_name="sos09d_i")
        files2 = emit_rust_hal(annotations, crate_name="sos09d_i")
        for path in files1:
            assert files1[path] == files2[path], (
                f"determinism drift on re-emit: {path}"
            )

    def test_uuid_variation_does_not_change_symbol_names(self) -> None:
        """Two charts with the same `sos:name` set but different UUIDs
        produce identical symbol surface (modulo sos:id in comments)."""
        main = emit_rust_hal_from_chart(_FIXTURE_MAIN, crate_name="sos09d_i_a")
        alt = emit_rust_hal_from_chart(_FIXTURE_ALT_IDS, crate_name="sos09d_i_b")
        # Symbol surface: collect all `pub <kind> <name>` declarations.
        def _symbols(src: str) -> set[str]:
            return set(re.findall(
                r"^pub (?:fn|unsafe fn|const|struct|enum|use|mod) ([A-Za-z_][A-Za-z0-9_]*)",
                src, re.MULTILINE,
            )) | set(re.findall(
                r"^\s+pub ([A-Za-z_][A-Za-z0-9_]*):",
                src, re.MULTILINE,
            ))
        sym_main = _symbols(main["src/lib.rs"])
        sym_alt = _symbols(alt["src/lib.rs"])
        # The crate-name appears in Cargo.toml only; for lib.rs, the
        # SOS-09-D symbol surface MUST be identical.
        assert sym_main == sym_alt, (
            f"sos:name-determinism drift: {sym_main.symmetric_difference(sym_alt)}"
        )

    def test_diff_isolated_to_documented_variation_surface(self) -> None:
        """Per gate (i), the only inter-chart diff is `sos:id` appearing
        in `// SAFETY:` comments + per-channel doc comments. Strip those
        and the lib.rs files are byte-identical."""
        main = emit_rust_hal_from_chart(_FIXTURE_MAIN, crate_name="sos09d_i_a")
        alt = emit_rust_hal_from_chart(_FIXTURE_ALT_IDS, crate_name="sos09d_i_b")

        def _strip_uuid_variation(src: str) -> str:
            # Replace any RFC 4122 UUID with a placeholder. Two charts'
            # SAFETY + doc comments diff only on the UUID literal.
            return re.sub(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                "<UUID>", src,
            )
        assert _strip_uuid_variation(main["src/lib.rs"]) == \
               _strip_uuid_variation(alt["src/lib.rs"]), (
            "gate (i): lib.rs diff exceeds the documented sos:id variation surface"
        )


# ---------------------------------------------------------------------------
# Gates (j) + (k): invariant citation + umbrella INV-S-MEM-* satisfaction
# ---------------------------------------------------------------------------


class TestGatesJK_InvariantCitation:
    """The emit-path source cites INV-S-MEM-D-1..6 + the umbrella + SOS-09-A/B/G."""

    def test_emit_path_cites_invariants(self) -> None:
        """transliterate_rust.py source carries `@spec` + INV-S-MEM-D-*
        citation block per gate (j)."""
        src_path = _TOOLS_DIR / "transliterate_rust.py"
        src = src_path.read_text(encoding="utf-8")
        for inv in ("INV-S-MEM-D-1", "INV-S-MEM-D-2", "INV-S-MEM-D-3",
                    "INV-S-MEM-D-4", "INV-S-MEM-D-5", "INV-S-MEM-D-6"):
            assert inv in src, f"gate (j): {inv} not cited in transliterate_rust.py"

    def test_emit_path_cites_concepts_doc(self) -> None:
        src_path = _TOOLS_DIR / "transliterate_rust.py"
        src = src_path.read_text(encoding="utf-8")
        assert "SOS-09-D-CONCEPTS.md" in src, (
            "gate (j): SOS-09-D concepts doc not cited"
        )

    def test_emitted_lib_carries_invariant_block(self) -> None:
        """Per gate (k), the emitted crate carries the umbrella + D-*
        invariant block at its lib.rs head."""
        annotations = _make_annotations_from_channels([_status_channel("rx", n=1)])
        files = emit_rust_hal(annotations, crate_name="sos09d_jk")
        lib = files["src/lib.rs"]
        for inv in ("INV-S-MEM-D-1", "INV-S-MEM-D-4", "INV-S-MEM-D-5",
                    "INV-S-MEM-D-6"):
            assert inv in lib, f"gate (k): {inv} not cited in lib.rs"


# ---------------------------------------------------------------------------
# Sanity: width-type mapping + group identity
# ---------------------------------------------------------------------------


class TestWidthTypeMapping:
    @pytest.mark.parametrize(
        "width,expected",
        [(1, "u8"), (8, "u8"), (9, "u16"), (16, "u16"),
         (17, "u32"), (32, "u32"), (33, "u64"), (64, "u64")],
    )
    def test_rust_width_type_table(self, width: int, expected: str) -> None:
        assert _rust_width_type(width) == expected

    def test_rust_width_type_rejects_oversize(self) -> None:
        with pytest.raises(ValueError):
            _rust_width_type(65)


class TestRegisterBlockNaming:
    def test_default_group_emits_bare_register_block(self) -> None:
        assert _register_block_name("default") == "RegisterBlock"

    def test_named_group_emits_pascal_suffix(self) -> None:
        assert _register_block_name("dma_channel") == "RegisterBlockDmaChannel"
