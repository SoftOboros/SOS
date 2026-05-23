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
    embed_rust_runtime,
    emit_dispatch_event,
    emit_helpers,
    transliterate_to_rust,
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
        choices=("rust", "c", "both"),
        required=True,
        help="Emission target.",
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
    return p.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    """Validate --out vs --target consistency. Exits with code 3 on mismatch."""
    if args.target in ("rust", "c"):
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


def _decorate_sites_with_transliteration(target: str, ast: ChartAst) -> list[dict]:
    """For each script site, attempt target-language transliteration.
    On success, expose `transliterated_body` to the template; on
    failure, expose `transliteration_notes` so the template can fall
    back to a stub + comment surfacing of the chart source."""
    out: list[dict] = []
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
            try:
                result = transliterate_to_rust(
                    site.script_source, event_name=site.event
                )
                if result.unhandled_notes:
                    site_d["transliteration_notes"] = result.unhandled_notes
                else:
                    site_d["transliterated_body"] = result.rust_source
                    site_d["needs_ev_param"] = result.needs_ev_param
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


def render_target(target: str, ast: ChartAst) -> str:
    """Render the target's Jinja2 template against the chart AST."""
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
        sites=_decorate_sites_with_transliteration(target, ast),
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

    targets = ("rust", "c") if args.target == "both" else (args.target,)
    rendered: dict[str, str] = {}
    for t in targets:
        try:
            rendered[t] = render_target(t, ast)
        except Exception as exc:
            sys.stderr.write(f"sos-codegen: render({t}) failed: {exc}\n")
            return 2

    if args.dry_run:
        for t in targets:
            sys.stdout.write(f"=== {t} ===\n{rendered[t]}\n")
        return 0

    if args.target == "both":
        args.out_rust.write_text(rendered["rust"], encoding="utf-8")
        args.out_c.write_text(rendered["c"], encoding="utf-8")
    else:
        args.out.write_text(rendered[args.target], encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
