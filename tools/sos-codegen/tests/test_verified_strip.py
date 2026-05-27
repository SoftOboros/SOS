"""SOS-13 verified-strip profile tests.

Per [SOS-13-CONCEPTS.md §15 2026-05-23 ratification]
(../../../docs/concepts/SOS-13-CONCEPTS.md):
 - PCDN-SOS-13-001 — BOTH whole-port + per-region opt-in.
 - PCDN-SOS-13-002 — JSONL audit log shape.
 - PCDN-SOS-13-003 — `dev-keep` is default; verified-strip is opt-in.
 - PCDN-SOS-13-005 — mandatory 6/6 vector pass at bench time (gated by
   a separate harness; this test suite does NOT enforce 6/6).

These tests concretize [INV-SOS-G](../../../docs/concepts/SOS-07-CONCEPTS.md):
no elimination is silent — every strip operation MUST emit a SAFETY
comment + an audit-log record. Missing chart discharge annotation MUST
fall back to safe-default emission.

Marker `verified_strip` lets the bench harness select these tests
(`pytest -m verified_strip`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Local imports — the sos-codegen tree is a flat package, mirroring
# the layout used by main.py's `sys.path.insert` shim.
TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from transliterate_rust import (  # noqa: E402
    VerifiedStripConfig,
    apply_verified_strip,
    load_discharge_annotations,
    transliterate_to_rust,
)
from verified_audit import (  # noqa: E402
    AuditEntry,
    AUDIT_SCHEMA_VERSION,
    read_audit_log,
    write_audit_log,
)
import main as codegen_main  # noqa: E402

pytestmark = pytest.mark.verified_strip


FIXTURE_CHART = TESTS_DIR / "fixtures" / "discharged_bounds_chart.scxml"


# ---------------------------------------------------------------
# Defaults — verified-strip OFF preserves byte-identical emission.
# ---------------------------------------------------------------


def test_default_no_strip_no_audit():
    """Per PCDN-SOS-13-003: default behaviour is dev-keep. Without a
    `VerifiedStripConfig`, no stripping happens, no audit entries are
    produced, and the emitted Rust matches the prior surface."""
    src = "tcb[i] = 1;"
    result = transliterate_to_rust(src, event_name=None)
    assert "unsafe" not in result.rust_source
    assert "SAFETY" not in result.rust_source
    assert result.verified_strip_audit == []
    # The bounds-checked safe-default index access survives.
    assert "[i as usize]" in result.rust_source


def test_inactive_config_no_strip():
    """A `VerifiedStripConfig` with neither global flag nor matching
    region opt-in MUST be a no-op even if a discharge is declared."""
    cfg = VerifiedStripConfig(
        enabled_globally=False,
        enabled_regions=frozenset(),
        region_id="boot_bounded",
        discharges=("bounds",),
    )
    assert cfg.is_active() is False
    src = "tcb[i] = 1;"
    result = transliterate_to_rust(
        src,
        event_name=None,
        verified_strip=cfg,
        state_id="boot_bounded",
        chart_site="script_boot_bounded_onentry_0",
    )
    assert "unsafe" not in result.rust_source
    assert result.verified_strip_audit == []


# ---------------------------------------------------------------
# Global --verified-strip with a chart-discharged annotation.
# ---------------------------------------------------------------


def test_global_strip_with_bounds_discharge_emits_unsafe():
    """Global --verified-strip + a `bounds` discharge MUST replace
    the safe-default index access with `unsafe { ... get_unchecked(...) }`
    and emit one audit entry per replacement."""
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        enabled_regions=frozenset(),
        region_id="boot_bounded",
        discharges=("bounds",),
    )
    src = "tcb[i] = 1;"
    result = transliterate_to_rust(
        src,
        event_name=None,
        verified_strip=cfg,
        state_id="boot_bounded",
        chart_site="script_boot_bounded_onentry_0",
    )
    assert "unsafe {" in result.rust_source
    assert "get_unchecked" in result.rust_source
    assert "// SAFETY:" in result.rust_source
    assert "INV-SOS-G" in result.rust_source
    assert len(result.verified_strip_audit) == 1
    entry = result.verified_strip_audit[0]
    assert entry["operation"] == "bounds_check_strip"
    assert entry["chart_state"] == "boot_bounded"
    assert entry["discharge_source"] == '<sos:discharged check="bounds"/>'
    assert "SAFETY" not in entry["safety_citation"]  # citation is the body, no prefix


def test_global_strip_without_discharge_falls_back_safe():
    """Global --verified-strip with NO chart annotation: no stripping
    occurs (INV-SOS-G — eliminate only with citation). The audit log
    stays empty for this site."""
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        enabled_regions=frozenset(),
        region_id="boot_unbounded",
        discharges=(),  # no chart annotation on this site
    )
    assert cfg.is_active() is False
    src = "tcb[i] = 1;"
    result = transliterate_to_rust(
        src,
        event_name=None,
        verified_strip=cfg,
        state_id="boot_unbounded",
        chart_site="script_boot_unbounded_onentry_0",
    )
    assert "unsafe" not in result.rust_source
    assert "[i as usize]" in result.rust_source
    assert result.verified_strip_audit == []


# ---------------------------------------------------------------
# Per-region opt-in.
# ---------------------------------------------------------------


def test_per_region_opt_in_only_strips_named_region():
    """`--verified-region <id>` strips that region's discharged ops
    even when the global flag is off. Other regions stay safe-default."""
    src = "tcb[i] = 1;"
    # The opted-in region with a discharge gets stripped.
    cfg_in = VerifiedStripConfig(
        enabled_globally=False,
        enabled_regions=frozenset({"boot_bounded"}),
        region_id="boot_bounded",
        discharges=("bounds",),
    )
    assert cfg_in.is_active() is True
    r_in = transliterate_to_rust(
        src,
        verified_strip=cfg_in,
        state_id="boot_bounded",
        chart_site="script_boot_bounded_onentry_0",
    )
    assert "unsafe {" in r_in.rust_source
    assert len(r_in.verified_strip_audit) == 1

    # A different region — NOT in the opt-in set — stays safe-default
    # even though it also carries a discharge.
    cfg_out = VerifiedStripConfig(
        enabled_globally=False,
        enabled_regions=frozenset({"boot_bounded"}),
        region_id="other_state",
        discharges=("bounds",),
    )
    assert cfg_out.is_active() is False
    r_out = transliterate_to_rust(
        src,
        verified_strip=cfg_out,
        state_id="other_state",
        chart_site="script_other_state_onentry_0",
    )
    assert "unsafe" not in r_out.rust_source
    assert r_out.verified_strip_audit == []


# ---------------------------------------------------------------
# Audit log JSONL — round-trip + parseability.
# ---------------------------------------------------------------


def test_audit_log_jsonl_round_trip(tmp_path: Path):
    """JSONL records survive write → read round-trip; each line is
    independently parseable. Required by PCDN-SOS-13-002 (one
    elimination per line, streamable, diff-friendly)."""
    entries = [
        AuditEntry(
            region_id="boot_bounded",
            chart_state="boot_bounded",
            operation="bounds_check_strip",
            discharge_source='<sos:discharged check="bounds"/>',
            emitted_line=42,
            safety_citation="INV-SOS-G — bounds discharged on boot_bounded",
        ),
        AuditEntry(
            region_id="sched_dispatch",
            chart_state="sched_dispatch",
            operation="null_check_strip",
            discharge_source='<sos:discharged check="null"/>',
            emitted_line=99,
            safety_citation="INV-SOS-G — null discharged on sched_dispatch",
        ),
    ]
    log = tmp_path / "verified_audit.jsonl"
    n = write_audit_log(log, entries)
    assert n == 2
    raw = log.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 2
    for line in raw:
        # Each line is independently valid JSON.
        d = json.loads(line)
        assert d["schema_version"] == AUDIT_SCHEMA_VERSION
        assert "operation" in d
        assert "chart_state" in d
    # The reader returns the same records (in order).
    records = read_audit_log(log)
    assert len(records) == 2
    assert records[0]["schema_version"] == AUDIT_SCHEMA_VERSION
    assert records[0]["operation"] == "bounds_check_strip"
    assert records[1]["operation"] == "null_check_strip"


# ---------------------------------------------------------------
# Discharge-annotation parsing from SCXML XML.
# ---------------------------------------------------------------


def test_load_discharge_annotations_from_fixture():
    """The loader reads `<sos:discharged check="..."/>` children of a
    state and maps them to the owning state-id."""
    discharges = load_discharge_annotations(FIXTURE_CHART)
    assert "boot_bounded" in discharges
    assert "bounds" in discharges["boot_bounded"]
    # The other state carries no annotation; it MUST NOT appear in the
    # mapping.
    assert "boot_unbounded" not in discharges


# ---------------------------------------------------------------
# Golden-file test — fixture chart drives a known SAFETY comment.
# ---------------------------------------------------------------


def test_fixture_chart_yields_safety_citation():
    """End-to-end smoke: load the fixture chart's discharge map, run
    the transliterator on the discharged state's onentry script, and
    confirm the emitted Rust contains the expected SAFETY comment."""
    discharges = load_discharge_annotations(FIXTURE_CHART)
    assert discharges.get("boot_bounded") == ["bounds"]

    cfg = VerifiedStripConfig(
        enabled_globally=True,
        enabled_regions=frozenset(),
        region_id="boot_bounded",
        discharges=tuple(discharges["boot_bounded"]),
    )
    # Mirror the script body present in the fixture's <onentry>.
    src = "tcb[i] = 1;"
    result = transliterate_to_rust(
        src,
        verified_strip=cfg,
        state_id="boot_bounded",
        chart_site="script_boot_bounded_onentry_0",
    )
    # Golden: a specific SAFETY-comment substring identifies the
    # citation surface a reviewer would scan for.
    expected_safety = (
        '// SAFETY: INV-SOS-G — bounds discharged at chart '
        '<sos:discharged check="bounds"/> on boot_bounded'
    )
    assert expected_safety in result.rust_source
    # Audit entry shape matches the JSONL contract.
    assert len(result.verified_strip_audit) == 1
    entry = result.verified_strip_audit[0]
    assert entry["chart_state"] == "boot_bounded"
    assert entry["region_id"] == "boot_bounded"
    assert entry["operation"] == "bounds_check_strip"
    assert entry["discharge_source"] == '<sos:discharged check="bounds"/>'
    # `emitted_line` is a non-zero integer pointing at a real line.
    assert isinstance(entry["emitted_line"], int)
    assert entry["emitted_line"] >= 1


# ---------------------------------------------------------------
# apply_verified_strip — direct post-pass behaviour.
# ---------------------------------------------------------------


def test_apply_verified_strip_idempotent_on_inactive_config():
    """Direct call to `apply_verified_strip` with an inactive config
    returns the source unchanged + empty audit list. Used by callers
    that bypass `transliterate_to_rust`."""
    cfg = VerifiedStripConfig()  # all defaults — inactive
    src = "dm.tcb[i as usize] = 1;"
    out, audit = apply_verified_strip(src, cfg, "boot", "chart_site")
    assert out == src
    assert audit == []


def test_apply_verified_strip_active_replaces_indexed_access():
    """With an active config + `bounds` discharge, the post-pass
    replaces every `<recv>[<idx> as usize]` occurrence."""
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        region_id="boot",
        discharges=("bounds",),
    )
    src = "let x = dm.tcb[i as usize].state;"
    out, audit = apply_verified_strip(src, cfg, "boot", "chart_site")
    assert "unsafe {" in out
    assert "get_unchecked" in out
    assert "// SAFETY:" in out
    assert len(audit) == 1
    assert audit[0]["operation"] == "bounds_check_strip"


# ---------------------------------------------------------------
# CLI profile surface — SOS-13 §12(a), §12(h).
# ---------------------------------------------------------------


def test_cli_profile_defaults_to_dev_keep():
    """`--profile` defaults to `dev-keep` per SOS-13 §5.2 / §12(a)."""
    args = codegen_main.parse_args([
        "--target", "rust",
        "--dry-run",
        "--chart", str(FIXTURE_CHART),
    ])
    assert args.profile == "dev-keep"
    assert args.verified_audit == Path("verified-strip-audit.jsonl")


def test_cli_profile_verified_strip_is_rust_only(capsys):
    """`--target c --profile verified-strip` is rejected at v1 per
    SOS-13 §5.4 / §12(h)."""
    args = codegen_main.parse_args([
        "--target", "c",
        "--dry-run",
        "--chart", str(FIXTURE_CHART),
        "--profile", "verified-strip",
    ])
    with pytest.raises(SystemExit) as excinfo:
        codegen_main.validate_args(args)
    assert excinfo.value.code == 3
    assert "Rust-only" in capsys.readouterr().err


def test_cli_profile_verified_strip_emits_audit(tmp_path: Path):
    """Driving `main()` with the ratified `--profile verified-strip`
    path writes a JSONL audit file when a discharged site strips a
    bounds check."""
    audit_path = tmp_path / "verified-strip-audit.jsonl"
    rc = codegen_main.main([
        "--target", "rust",
        "--dry-run",
        "--chart", str(FIXTURE_CHART),
        "--profile", "verified-strip",
        "--verified-audit", str(audit_path),
    ])
    assert rc == 0
    records = read_audit_log(audit_path)
    assert len(records) == 1
    assert records[0]["schema_version"] == AUDIT_SCHEMA_VERSION
    assert records[0]["operation"] == "bounds_check_strip"
    assert records[0]["chart_state"] == "boot_bounded"
