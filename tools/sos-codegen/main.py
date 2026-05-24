#!/usr/bin/env python3
"""SOS-06-A reference codegen tool — chart → scripts.rs / scripts.c.

Specified by docs/concepts/SOS-06-CONCEPTS.md (methodology) and
docs/concepts/SOS-06-A-EVALUATION.md (toolchain choice). v1 emits
chart-derived `scripts.rs` and `scripts.c` byte-equivalent to the
bench-validated hand-written ports at:
  - ports/m7-rust/sos-m7-rust/src/scripts.rs (SOS-04, bench-validated 6/6)
  - ports/m7-c/sos-m7-c/src/scripts.c       (SOS-05, bench-validated 6/6)

The v1 emit pipeline is:
  rtos_kernel.scxml --[lxml load]--> AST dict --[Jinja2 templates]--> source.

Exit codes:
  0  successful emission
  1  chart load / parse error
  2  template render error
  3  invocation / IO error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from lxml import etree  # noqa: F401 — used by loader.
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "sos-codegen: lxml is required; install via "
        f"`pip install -r tools/sos-codegen/requirements.txt`. ({exc})\n"
    )
    sys.exit(3)

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "sos-codegen: jinja2 is required; install via "
        f"`pip install -r tools/sos-codegen/requirements.txt`. ({exc})\n"
    )
    sys.exit(3)

# Local imports. The tool is a flat package; both loader.py and main.py
# live in the same directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from loader import ChartAst, load_chart  # noqa: E402
from transliterate_c import (  # noqa: E402
    embed_c_runtime,
    emit_helpers_c,
    transliterate_to_c,
)
from transliterate_rust import (  # noqa: E402
    VerifiedStripConfig,
    embed_rust_runtime,
    emit_dispatch_event,
    emit_helpers,
    load_discharge_annotations,
    transliterate_to_rust,
)
from verified_audit import AuditEntry, write_audit_log  # noqa: E402

# SOS-08-C L2 HDL emission — the per-dialect walkers (transliterate_hdl_vhdl,
# transliterate_hdl_sv) are sibling agents' work. We import the dialect-
# neutral substrate here at module load time (always present once SOS-08-C
# wave-1 lands), but defer the per-dialect walker imports to the dispatch
# function — that way `--target rust` / `--target c` continue to work even
# if the sibling agents' modules have not yet landed in the working tree.
from hdl_common import (  # noqa: E402
    DEFAULT_GUARD_DEPTH_BUDGET,
    FsmEncoding,
    HdlEmitConfig,
)

TOOL_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = TOOL_DIR / "templates"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="sos-codegen",
        description="Chart-driven codegen for the SOS M7 ports.",
    )
    p.add_argument(
        "--chart",
        type=Path,
        default=TOOL_DIR.parent.parent / "rtos_kernel.scxml",
        help="Path to rtos_kernel.scxml (default: <subrepo>/rtos_kernel.scxml).",
    )
    p.add_argument(
        "--target",
        choices=("rust", "c", "both", "hdl-vhdl", "hdl-sv", "cocotb", "sva"),
        required=True,
        help=(
            "Emission target. ``rust`` / ``c`` / ``both`` emit the SOS-04 / "
            "SOS-05 M7 ports (SOS-06-A). ``hdl-vhdl`` / ``hdl-sv`` emit the "
            "SOS-08-C Layer-2 region FSMs against the SOS-08-A / SOS-08-B "
            "L0/L1 substrate (ratified 2026-05-23, SOS-08-C §15). "
            "``cocotb`` / ``sva`` emit the SOS-08-D primary vector path "
            "(cocotb testbench + SVA bind file) — ratified 2026-05-23, "
            "SOS-08-D §15. See SOS-08-D §6.1 for the emitted directory "
            "layout."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        help="Output path (used when --target is rust or c).",
    )
    p.add_argument(
        "--out-rust",
        type=Path,
        help="Output path for the Rust source (used when --target=both).",
    )
    p.add_argument(
        "--out-c",
        type=Path,
        help="Output path for the C source (used when --target=both).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Render but do not write; print rendered content to stdout.",
    )
    # SOS-13 verified-strip profile flags. Per SOS-13-CONCEPTS.md §15
    # 2026-05-23 ratification entry:
    #   - PCDN-SOS-13-001 — BOTH profile + per-region opt-in.
    #   - PCDN-SOS-13-003 — `dev-keep` is the default (so --verified-strip
    #     defaults to False).
    #   - PCDN-SOS-13-002 — audit log is JSONL.
    p.add_argument(
        "--verified-strip",
        action="store_true",
        default=False,
        help=(
            "Enable SOS-13 verified-strip profile across all regions. "
            "Default is dev-keep (PCDN-SOS-13-003)."
        ),
    )
    p.add_argument(
        "--verified-region",
        action="append",
        default=[],
        metavar="REGION_ID",
        help=(
            "Opt one region into verified-strip even when the global "
            "flag is off. Repeatable. PCDN-SOS-13-001 (per-region "
            "granularity)."
        ),
    )
    p.add_argument(
        "--verified-audit",
        type=Path,
        default=Path("verified_audit.jsonl"),
        help=(
            "Path to the JSONL audit log (PCDN-SOS-13-002). Default "
            "`verified_audit.jsonl` in the current directory. The file "
            "is written only when at least one verified-strip "
            "elimination is emitted."
        ),
    )
    # SOS-08-C L2 HDL emission profile flags. Per SOS-08-C §15
    # 2026-05-23 ratification:
    #   - PCDN-C-005: chart annotation wins; CLI flag is a hint that
    #     applies only to unannotated regions.
    #   - PCDN-C-004: guard-depth budget default 8; SCXML-LINT-C-2
    #     enforces at chart-compile time.
    #   - PCDN-C-006: document-order priority lint warning
    #     (SCXML-LINT-C-1); on by default.
    p.add_argument(
        "--hdl-encoding",
        choices=("one-hot", "binary", "gray"),
        default="one-hot",
        help=(
            "Default FSM state encoding for unannotated regions "
            "(PCDN-SOS-08-C-005). Chart-side `<region encoding=\"...\"/>` "
            "annotations override per-region. Default `one-hot` mirrors "
            "SOS-08 PCDN-002."
        ),
    )
    p.add_argument(
        "--guard-depth-budget",
        type=int,
        default=DEFAULT_GUARD_DEPTH_BUDGET,
        metavar="N",
        help=(
            "Maximum chained guard-expression operator count before the "
            "emitter rejects the guard (PCDN-SOS-08-C-004 / "
            "SCXML-LINT-C-2). Default 8."
        ),
    )
    p.add_argument(
        "--lint-warn-doc-order",
        dest="lint_warn_doc_order",
        action="store_true",
        default=True,
        help=(
            "Emit SCXML-LINT-C-1 warning when two transitions in the "
            "same source state could simultaneously be true under "
            "bounded reachability (PCDN-SOS-08-C-006). On by default."
        ),
    )
    p.add_argument(
        "--no-lint-warn-doc-order",
        dest="lint_warn_doc_order",
        action="store_false",
        help="Disable SCXML-LINT-C-1 emission (see --lint-warn-doc-order).",
    )
    return p.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    """Validate --out vs --target consistency. Exits with code 3 on mismatch."""
    if args.target in ("rust", "c", "hdl-vhdl", "hdl-sv", "cocotb", "sva"):
        if args.out is None and not args.dry_run:
            sys.stderr.write(
                f"sos-codegen: --target={args.target} requires --out=PATH "
                "or --dry-run.\n"
            )
            sys.exit(3)
    elif args.target == "both":
        if not args.dry_run:
            if args.out_rust is None or args.out_c is None:
                sys.stderr.write(
                    "sos-codegen: --target=both requires both --out-rust=PATH "
                    "and --out-c=PATH (or --dry-run).\n"
                )
                sys.exit(3)
    if not args.chart.exists():
        sys.stderr.write(f"sos-codegen: chart not found: {args.chart}\n")
        sys.exit(3)
    # SOS-08-C: validate guard-depth budget is sane.
    budget = getattr(args, "guard_depth_budget", DEFAULT_GUARD_DEPTH_BUDGET)
    if budget < 1:
        sys.stderr.write(
            f"sos-codegen: --guard-depth-budget must be ≥ 1, got {budget}.\n"
        )
        sys.exit(3)


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        # Templates contain `{` / `}` braces in surfaced ECMAScript /
        # Rust / C code; only `{{ ... }}` and `{% ... %}` are Jinja
        # syntax. Default delimiters are fine; document for clarity.
        autoescape=False,
    )


def _decorate_sites_with_transliteration(
    target: str,
    ast: ChartAst,
    verified_strip_enabled: bool = False,
    verified_regions: frozenset = frozenset(),
    discharges_by_state: dict | None = None,
    audit_sink: list | None = None,
) -> list[dict]:
    """For each script site, attempt target-language transliteration.
    On success, expose `transliterated_body` to the template; on
    failure, expose `transliteration_notes` so the template can fall
    back to a stub + comment surfacing of the chart source.

    The trailing kwargs wire the SOS-13 verified-strip profile through
    to the Rust transliterator. They are no-ops for `target == "c"`
    and have no effect when `verified_strip_enabled` is False and
    `verified_regions` is empty (the byte-identical default path).
    """
    out: list[dict] = []
    discharges_by_state = discharges_by_state or {}
    for site in ast.sites:
        site_d: dict = {
            "kind": site.kind,
            "state_id": site.state_id,
            "event": site.event,
            "cond": site.cond,
            "target": site.target,
            "raises": site.raises,
            "script_index": site.script_index,
            "script_source": site.script_source,
            "function_name": site.function_name,
            "transliterated_body": None,
            "transliteration_notes": [],
            "needs_ev_param": False,
        }
        if target == "rust":
            # Build per-site verified-strip config. The site is in scope
            # of the profile when EITHER the global flag is set OR the
            # site's state-id is in the explicit per-region opt-in set.
            # Discharge annotations are read from the chart's
            # <sos:discharged check="..."/> children.
            vs_cfg = None
            if verified_strip_enabled or verified_regions:
                discharges = tuple(
                    discharges_by_state.get(site.state_id, [])
                )
                vs_cfg = VerifiedStripConfig(
                    enabled_globally=verified_strip_enabled,
                    enabled_regions=verified_regions,
                    region_id=site.state_id,
                    discharges=discharges,
                )
            try:
                result = transliterate_to_rust(
                    site.script_source,
                    event_name=site.event,
                    verified_strip=vs_cfg,
                    state_id=site.state_id,
                    chart_site=site.function_name,
                )
                if result.unhandled_notes:
                    site_d["transliteration_notes"] = result.unhandled_notes
                else:
                    site_d["transliterated_body"] = result.rust_source
                    site_d["needs_ev_param"] = result.needs_ev_param
                # Forward audit entries even when notes are present —
                # the post-pass operates on already-emitted source,
                # so its records are valid regardless of fallback
                # status. (Empty when the profile is inactive.)
                if audit_sink is not None and result.verified_strip_audit:
                    audit_sink.extend(result.verified_strip_audit)
            except Exception as exc:
                site_d["transliteration_notes"] = [f"parse error: {exc}"]
        elif target == "c":
            try:
                c_result = transliterate_to_c(
                    site.script_source, event_name=site.event
                )
                if c_result.unhandled_notes:
                    site_d["transliteration_notes"] = c_result.unhandled_notes
                else:
                    site_d["transliterated_body"] = c_result.c_source
                    site_d["needs_ev_param"] = getattr(c_result, "needs_ev_param", False)
            except Exception as exc:
                site_d["transliteration_notes"] = [f"parse error: {exc}"]
        out.append(site_d)
    return out


def _render_hdl_target(
    target: str,
    ast: ChartAst,
    hdl_config: HdlEmitConfig,
) -> str:
    """Dispatch HDL emission to the per-dialect walker (SOS-08-C L2).

    The per-dialect walker modules (`transliterate_hdl_vhdl`,
    `transliterate_hdl_sv`) are owned by sibling agents in the wave-1
    fan-out. We import them lazily here so the `--target rust` /
    `--target c` paths remain functional even before the siblings'
    files land in the working tree.

    Cites: SOS-08-C §15 ratification (2026-05-23); SOS-08-C §6
    emission algorithm (consumed by the per-dialect walker).
    """
    if target == "hdl-vhdl":
        try:
            from transliterate_hdl_vhdl import (  # noqa: E402
                render_target as render_vhdl,
            )
        except ImportError as exc:
            raise RuntimeError(
                "sos-codegen: --target=hdl-vhdl requires "
                "`transliterate_hdl_vhdl.py` next to main.py (SOS-08-C "
                "wave-1 sibling module). Import error: "
                f"{exc}"
            ) from exc
        return render_vhdl(ast.raw_scjson, hdl_config)
    if target == "hdl-sv":
        try:
            from transliterate_hdl_sv import (  # noqa: E402
                render_target as render_sv,
            )
        except ImportError as exc:
            raise RuntimeError(
                "sos-codegen: --target=hdl-sv requires "
                "`transliterate_hdl_sv.py` next to main.py (SOS-08-C "
                "wave-1 sibling module). Import error: "
                f"{exc}"
            ) from exc
        return render_sv(ast.raw_scjson, hdl_config)
    raise ValueError(f"_render_hdl_target: unsupported target {target!r}")


def _render_cocotb_target(
    ast: ChartAst,
    config: dict,
) -> dict[str, str]:
    """Dispatch SOS-08-D cocotb vector-path emission to the sibling walker.

    The sibling module (`transliterate_cocotb`) is owned by a parallel
    fan-out agent. Lazy-import it here so the other ``--target`` paths
    remain functional before the sibling lands.

    Per SOS-08-D §6.1 (emit directory layout, ratified 2026-05-23 — §15)
    the walker returns ``{filename: source}`` with paths rooted at
    ``tests/<chart_name>/`` covering the cocotb testbench
    (``test_<chart_name>_fsm.py``), shared helpers
    (``_cocotb_helpers.py``), the cocotb-classic ``Makefile``, a
    ``pytest.ini`` driving the ``cocotb-test`` runner (PCDN-D-007), a
    ``README.md`` recording chart-side traceability metadata + the
    Python 3.10 minimum (PCDN-D-005), and a ``vectors/`` directory
    seeded with at least one JSONL example (PCDN-D-003).

    Cites: SOS-08-D §15 ratification (2026-05-23); SOS-08-D §6.1
    (emit directory layout); SOS-08-D §6.2 (per-vector test function
    shape); SOS-08-D §6.4 (simulator-invocation conventions).
    """
    try:
        from transliterate_cocotb import (  # noqa: E402
            render_target as render_cocotb,
        )
    except ImportError as exc:
        raise RuntimeError(
            "sos-codegen: --target=cocotb requires "
            "`transliterate_cocotb.py` next to main.py (SOS-08-D wave-1 "
            f"sibling module). Import error: {exc}"
        ) from exc
    return render_cocotb(ast.raw_scjson, config)


def _render_sva_target(
    ast: ChartAst,
    config: dict,
) -> dict[str, str]:
    """Dispatch SOS-08-D SVA bind file emission to the sibling walker.

    The sibling module (`transliterate_sva_bind`) is owned by a parallel
    fan-out agent. Lazy-import it here so the other ``--target`` paths
    remain functional before the sibling lands.

    Per SOS-08-D §6.3 + PCDN-D-004 (resolved 2026-05-23 — §15) the
    walker returns ``{filename: source}`` for at least the assertion
    module (``<chart_name>_fsm_sva.sv``) and the bind directive
    (``<chart_name>_fsm_bind.sv``). Per INV-S-HDL-D-4 the same SVA
    artifact pair feeds both the cocotb vector path and the formal-flow
    consumers (SymbiYosys, JasperGold) without re-emission.

    Cites: SOS-08-D §15 ratification (2026-05-23); SOS-08-D §6.3
    (per-DUT SVA bind file shape); PCDN-D-004 (per-DUT bind file
    co-located with the cocotb test directory).
    """
    try:
        from transliterate_sva_bind import (  # noqa: E402
            render_target as render_sva,
        )
    except ImportError as exc:
        raise RuntimeError(
            "sos-codegen: --target=sva requires "
            "`transliterate_sva_bind.py` next to main.py (SOS-08-D "
            f"wave-1 sibling module). Import error: {exc}"
        ) from exc
    return render_sva(ast.raw_scjson, config)


def render_target(
    target: str,
    ast: ChartAst,
    verified_strip_enabled: bool = False,
    verified_regions: frozenset = frozenset(),
    discharges_by_state: dict | None = None,
    audit_sink: list | None = None,
    hdl_config: HdlEmitConfig | None = None,
    cocotb_sva_config: dict | None = None,
) -> str:
    """Render the target's Jinja2 template against the chart AST.

    Trailing kwargs wire the SOS-13 verified-strip profile through
    to the Rust transliterator; they are no-ops for `target == "c"`
    and have no effect when the profile is not engaged.

    For `target in {"hdl-vhdl", "hdl-sv"}` (SOS-08-C L2 emission), the
    per-dialect walker is invoked via :func:`_render_hdl_target` and
    `hdl_config` is consumed; the Jinja2 path below is bypassed.

    For `target in {"cocotb", "sva"}` (SOS-08-D primary vector path),
    the cocotb / SVA bind sibling walkers are invoked via
    :func:`_render_cocotb_target` / :func:`_render_sva_target` and
    `cocotb_sva_config` is forwarded as the walker's ``config`` arg;
    the Jinja2 path below is bypassed. See SOS-08-D §6.1 / §6.3.
    """
    if target in ("hdl-vhdl", "hdl-sv"):
        if hdl_config is None:
            hdl_config = HdlEmitConfig()
        return _render_hdl_target(target, ast, hdl_config)
    if target == "cocotb":
        return _render_cocotb_target(ast, cocotb_sva_config or {})
    if target == "sva":
        return _render_sva_target(ast, cocotb_sva_config or {})
    env = _env()
    template_name = {"rust": "scripts.rs.j2", "c": "scripts.c.j2"}[target]
    tpl = env.get_template(template_name)
    # Target-specific extras: Rust gets impl-Datamodel helpers + the
    # dispatch_event matcher emitted from the AST; C gets the
    # file-static `dm_*` helpers emitted ahead of the per-site script
    # bodies (SOS-06-A-2 Item 2).
    helpers_rust: list = []
    dispatch_rust: str = ""
    runtime_rust: str = ""
    helpers_c: str = ""
    runtime_c: str = ""
    if target == "rust":
        # SOS-06 §15 Amendment 002 / Phase 1 closure: prefer the
        # bench-validated Layer B runtime (impl Datamodel + WaiterList
        # embedded verbatim from the reference scripts.rs) over the
        # codegen's stubbed `emit_helpers()` output. If the reference
        # isn't available, fall back to the stub-emitter.
        runtime_rust = embed_rust_runtime()
        if not runtime_rust:
            helpers_rust = [
                {"name": h.name, "rust_source": h.rust_source, "is_stub": h.is_stub}
                for h in emit_helpers(ast.helpers_source)
            ]
        dispatch_rust = emit_dispatch_event(ast.sites)
    elif target == "c":
        # SOS-06 §15 Amendment 002 / Phase 1 closure: prefer the
        # bench-validated Layer B runtime (hand-written `dm_*` helpers
        # embedded verbatim from the reference scripts.c) over the
        # codegen's stubbed `emit_helpers_c()` output. If the reference
        # isn't available, fall back to the stub-emitter.
        runtime_c = embed_c_runtime()
        if not runtime_c:
            helpers_c = emit_helpers_c(ast.helpers_source)
    return tpl.render(
        datamodel=ast.datamodel,
        helpers_source=ast.helpers_source,
        sites=_decorate_sites_with_transliteration(
            target,
            ast,
            verified_strip_enabled=verified_strip_enabled,
            verified_regions=verified_regions,
            discharges_by_state=discharges_by_state,
            audit_sink=audit_sink,
        ),
        helpers_rust=helpers_rust,
        dispatch_rust=dispatch_rust,
        runtime_rust=runtime_rust,
        helpers_c=helpers_c,
        runtime_c=runtime_c,
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    validate_args(args)

    try:
        ast = load_chart(args.chart)
    except (FileNotFoundError, RuntimeError) as exc:
        sys.stderr.write(f"sos-codegen: {exc}\n")
        return 1

    # SOS-13 verified-strip: load discharge annotations from the chart
    # so the per-site decorator can consult them. Off the Rust path,
    # this loader is a no-op observer — its return value is only
    # consulted when `target == "rust"`.
    verified_strip_enabled = bool(getattr(args, "verified_strip", False))
    verified_regions = frozenset(getattr(args, "verified_region", []) or [])
    discharges_by_state: dict = {}
    if verified_strip_enabled or verified_regions:
        try:
            discharges_by_state = load_discharge_annotations(args.chart)
        except Exception as exc:
            sys.stderr.write(
                f"sos-codegen: load_discharge_annotations failed: {exc}\n"
            )
            return 1

    audit_sink: list = []

    # SOS-08-C: construct the HDL emission config (consumed only when
    # target is hdl-vhdl or hdl-sv; harmless to build for other targets).
    try:
        hdl_encoding = FsmEncoding.parse(getattr(args, "hdl_encoding", "one-hot"))
    except ValueError as exc:
        sys.stderr.write(f"sos-codegen: {exc}\n")
        return 3
    hdl_config = HdlEmitConfig(
        encoding=hdl_encoding,
        guard_depth_budget=int(
            getattr(args, "guard_depth_budget", DEFAULT_GUARD_DEPTH_BUDGET)
        ),
        lint_warn_doc_order=bool(getattr(args, "lint_warn_doc_order", True)),
        verified_strip=verified_strip_enabled,
    )

    # SOS-08-D primary vector path config — derives the chart_name from
    # the chart filename's stem (so `rtos_kernel.scxml` → `rtos_kernel`).
    # The sibling walkers consume `chart_name` to name the emitted
    # directory + module/file basenames per §6.1 layout.
    cocotb_sva_config: dict = {
        "chart_name": args.chart.stem,
    }

    targets = ("rust", "c") if args.target == "both" else (args.target,)
    rendered: dict[str, str] = {}
    for t in targets:
        try:
            rendered[t] = render_target(
                t,
                ast,
                verified_strip_enabled=verified_strip_enabled,
                verified_regions=verified_regions,
                discharges_by_state=discharges_by_state,
                audit_sink=audit_sink,
                hdl_config=hdl_config,
                cocotb_sva_config=cocotb_sva_config,
            )
        except Exception as exc:
            sys.stderr.write(f"sos-codegen: render({t}) failed: {exc}\n")
            return 2

    # SOS-13 §7.4: emit the audit log when at least one elimination
    # happened. We do NOT create an empty file — the absence of an
    # audit log is a meaningful signal (no eliminations occurred).
    if audit_sink:
        entries = [
            AuditEntry(
                region_id=d.get("region_id", ""),
                chart_state=d.get("chart_state", ""),
                operation=d.get("operation", ""),
                discharge_source=d.get("discharge_source", ""),
                emitted_line=int(d.get("emitted_line", 0)),
                safety_citation=d.get("safety_citation", ""),
                extra={
                    k: v
                    for k, v in d.items()
                    if k not in {
                        "region_id", "chart_state", "operation",
                        "discharge_source", "emitted_line",
                        "safety_citation",
                    }
                },
            )
            for d in audit_sink
        ]
        try:
            write_audit_log(args.verified_audit, entries)
        except Exception as exc:
            sys.stderr.write(
                f"sos-codegen: writing audit log {args.verified_audit} "
                f"failed: {exc}\n"
            )
            return 3

    if args.dry_run:
        for t in targets:
            payload = rendered[t]
            if isinstance(payload, dict):
                # HDL targets emit {filename: source}; print each artifact.
                for fname, body in payload.items():
                    sys.stdout.write(f"=== {t}: {fname} ===\n{body}\n")
            else:
                sys.stdout.write(f"=== {t} ===\n{payload}\n")
        return 0

    if args.target == "both":
        args.out_rust.write_text(rendered["rust"], encoding="utf-8")
        args.out_c.write_text(rendered["c"], encoding="utf-8")
    elif args.target in ("hdl-vhdl", "hdl-sv", "cocotb", "sva"):
        # HDL + SOS-08-D walkers return {filename: source}; write each
        # into args.out (treated as a directory). For cocotb / sva the
        # emitted filenames are relative paths (e.g.
        # `tests/<chart_name>/test_<chart_name>_fsm.py`) per SOS-08-D
        # §6.1 — create intermediate parent dirs as needed.
        payload = rendered[args.target]
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"sos-codegen: --target={args.target} expected dict output; got {type(payload).__name__}"
            )
        out_dir = args.out
        out_dir.mkdir(parents=True, exist_ok=True)
        for fname, body in payload.items():
            dest = out_dir / fname
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body, encoding="utf-8")
    else:
        args.out.write_text(rendered[args.target], encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
