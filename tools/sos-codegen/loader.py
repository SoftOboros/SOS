"""SCXML → scjson-shaped AST loader for sos-codegen.

Shells out to `scjson json` (the pip-installable converter from the scjson
family vendored at `ops/packer/submodules/scjson/`) and then re-walks the
JSON output to produce a flatter AST shape — a list of script-site records
the templates can iterate over, plus the datamodel constants and the
HELPERS-block source.

The scjson output preserves the SCXML tree faithfully (states, transitions,
onentry, onexit, datamodel, parallel regions). For codegen we want a
normalized list:

    {
        "datamodel": [{"id": "MAX_TASKS", "expr": "8"}, ...],
        "helpers_source": "<chart's top-level <script> CDATA verbatim>",
        "sites": [
            {
                "kind": "onentry" | "transition",
                "state_id": "boot" | "sched_idle" | ...,
                "event": "kernel.boot.done" | None,
                "cond": "sched_lock == 0" | None,
                "target": ["sched_idle"] | None,
                "raises": ["sched.run", ...],
                "script_index": 0 | 1 | ...,
                "script_source": "<ECMAScript body verbatim>",
                "function_name": "script_boot_onentry_0" | "script_sched_idle_sched_run_0" | ...,
            },
            ...
        ],
    }

The `function_name` field is the load-bearing identifier the templates emit
into the target source files. It must match the naming convention used in
the hand-written ports (per the Track-1 survey):

    script_<parent_state_id>_<event_or_kind>_<index>

For onentry: `script_<state>_onentry_0`.
For transitions: `script_<state>_<event_normalised>_<index>` where the event
name has `.` replaced with `_`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ScriptSite:
    """One <script> location in the chart."""

    kind: str
    state_id: str
    event: str | None
    cond: str | None
    target: list[str] | None
    raises: list[str]
    script_index: int
    script_source: str
    function_name: str


@dataclass
class ChartAst:
    """Normalised AST consumed by templates."""

    datamodel: list[dict[str, str]] = field(default_factory=list)
    helpers_source: str = ""
    sites: list[ScriptSite] = field(default_factory=list)
    # Raw scjson dict — preserved so SOS-08-C HDL walkers (which need a
    # state-centric view) can consume it directly. The script-site-centric
    # `sites` view above remains canonical for Rust/C ports.
    raw_scjson: dict | None = None


def _normalise_event_for_fn(event: str | None, kind: str) -> str:
    """`kernel.boot.done` → `kernel_boot_done`; None → `onentry`/`onexit`."""
    if event is None:
        return kind
    return event.replace(".", "_")


def _collect_states(node: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Walk an scjson node and yield (state_id, state_dict) for every
    <state> the codegen cares about. Skips <parallel> wrappers (descends
    into their children states)."""
    out: list[tuple[str, dict[str, Any]]] = []

    for st in node.get("state", []) or []:
        sid = st.get("id")
        if sid:
            out.append((sid, st))
        # Recurse — states can nest.
        out.extend(_collect_states(st))

    for par in node.get("parallel", []) or []:
        # <parallel> itself isn't a script-bearing state at v1; descend.
        out.extend(_collect_states(par))

    return out


def _collect_helpers_source(root: dict[str, Any]) -> str:
    """The root <scxml> element's top-level <script> blocks form the
    HELPERS section. Returns concatenated CDATA bodies."""
    parts: list[str] = []
    for s in root.get("script", []) or []:
        for c in s.get("content", []) or []:
            parts.append(c)
    return "\n".join(parts)


def _collect_datamodel(root: dict[str, Any]) -> list[dict[str, str]]:
    """The root <datamodel><data id=... expr=... /> entries, in order."""
    entries: list[dict[str, str]] = []
    dm = root.get("datamodel", [])
    if isinstance(dm, list):
        for entry in dm:
            for d in entry.get("data", []) or []:
                entries.append({"id": d.get("id", ""), "expr": d.get("expr", "")})
    elif isinstance(dm, dict):
        for d in dm.get("data", []) or []:
            entries.append({"id": d.get("id", ""), "expr": d.get("expr", "")})
    return entries


def _extract_scripts_from(
    container: dict[str, Any],
    state_id: str,
    kind: str,
    event: str | None,
    cond: str | None,
    target: list[str] | None,
    raises_from_container: list[str],
) -> list[ScriptSite]:
    """Pull every <script> out of an onentry / onexit / transition node."""
    sites: list[ScriptSite] = []
    scripts = container.get("script", []) or []
    fn_event_part = _normalise_event_for_fn(event, kind)
    for idx, s in enumerate(scripts):
        bodies = s.get("content", []) or []
        body = "\n".join(bodies)
        sites.append(
            ScriptSite(
                kind=kind,
                state_id=state_id,
                event=event,
                cond=cond,
                target=target,
                raises=raises_from_container,
                script_index=idx,
                script_source=body,
                function_name=f"script_{state_id}_{fn_event_part}_{idx}",
            )
        )
    return sites


def _collect_sites_for_state(
    state_id: str, st: dict[str, Any]
) -> list[ScriptSite]:
    """Per-state script-site collection: onentry, onexit, transitions."""
    sites: list[ScriptSite] = []

    for oe in st.get("onentry", []) or []:
        raises = [r.get("event", "") for r in (oe.get("raise_value", []) or [])]
        sites.extend(
            _extract_scripts_from(oe, state_id, "onentry", None, None, None, raises)
        )

    for ox in st.get("onexit", []) or []:
        raises = [r.get("event", "") for r in (ox.get("raise_value", []) or [])]
        sites.extend(
            _extract_scripts_from(ox, state_id, "onexit", None, None, None, raises)
        )

    for tr in st.get("transition", []) or []:
        event = tr.get("event")
        cond = tr.get("cond")
        target = tr.get("target")
        if isinstance(target, str):
            target = [target]
        raises = [r.get("event", "") for r in (tr.get("raise_value", []) or [])]
        sites.extend(
            _extract_scripts_from(
                tr, state_id, "transition", event, cond, target, raises
            )
        )

    return sites


def load_chart(chart_path: Path) -> ChartAst:
    """Run scjson, parse output, return a normalised ChartAst."""
    if not chart_path.exists():
        raise FileNotFoundError(f"chart not found: {chart_path}")

    # Shell out to scjson — produces a JSON file next to the input, or
    # to --output. Use --output to a deterministic temp path so we don't
    # pollute the chart directory.
    out_json = Path("/tmp") / f"{chart_path.stem}.scjson.json"
    res = subprocess.run(
        ["scjson", "json", str(chart_path), "--output", str(out_json)],
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"scjson failed (exit {res.returncode}): {res.stderr.strip()}"
        )

    raw = json.loads(out_json.read_text(encoding="utf-8"))
    ast = ChartAst(
        datamodel=_collect_datamodel(raw),
        helpers_source=_collect_helpers_source(raw),
        raw_scjson=raw,
    )
    for state_id, st in _collect_states(raw):
        ast.sites.extend(_collect_sites_for_state(state_id, st))

    return ast


def _cli_summarise(ast: ChartAst) -> None:
    """Dev / debug entry — print a summary of the loaded AST."""
    sys.stdout.write(f"datamodel entries: {len(ast.datamodel)}\n")
    sys.stdout.write(f"helpers source bytes: {len(ast.helpers_source)}\n")
    sys.stdout.write(f"script sites: {len(ast.sites)}\n")
    for s in ast.sites:
        body_preview = s.script_source.strip().splitlines()[:1]
        preview = body_preview[0] if body_preview else "(empty)"
        sys.stdout.write(
            f"  {s.function_name}  (kind={s.kind}, event={s.event or '-'}, "
            f"cond={s.cond or '-'})  body[0]: {preview[:60]}\n"
        )


if __name__ == "__main__":
    chart = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("rtos_kernel.scxml")
    ast = load_chart(chart)
    _cli_summarise(ast)
