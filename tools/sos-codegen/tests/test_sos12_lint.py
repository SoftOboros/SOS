"""Tests for `sos12_lint.py` — SOS-12 legibility + depth-cap lint rules.

Authority:

- SOS-12-CONCEPTS §6.5 + §10.3 + PCDN-SOS-12-005 — dispatch-tree depth
  cap default 8 (SCXML-LINT-DISP-1).
- SOS-12-CONCEPTS §9 + §10.2 + PCDN-SOS-12-003 — peer-state legibility
  threshold default 15 (SCXML-LINT-DISP-2). The SCXML-LINT-DISP-2 error
  message MUST recommend `extract_region_to_subchart` per §9.2 (the
  "discipline becomes a property the tooling enforces" half of §9).
- SOS-01-CONCEPTS §5.5 + §15 (commit `4f33c1e`) — `SCXML-LINT-DISP-N`
  category-prefix series reservation. SOS-12 owns the series.

Tests are split between two surfaces:

- **Synthetic-AST tests** drive the lint rules with hand-built
  scjson-shape dicts via a fake loader. These cover the core threshold
  edge cases (pass / at-cap / over-cap / custom-threshold) without
  requiring scjson on PATH.
- **Fixture-driven tests** load real `.scxml` files through
  `loader.load_chart` (which shells out to scjson). These exercise the
  end-to-end SCXML → scjson → lint round-trip. Skipped when scjson is
  unavailable.

Both surfaces mirror the precedent of `test_sos12_annotations.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd
# (the module dir uses a dash, so it's not a real Python package).
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos12_annotations import SOS_NS  # noqa: E402
from sos12_lint import (  # noqa: E402
    DEFAULT_LEGIBILITY_THRESHOLD,
    DEFAULT_MAX_DEPTH,
    LintDiagnostic,
    RULE_DISPATCH_DEPTH,
    RULE_LEGIBILITY,
    check_dispatch_depth,
    check_legibility,
)


DISPATCH_QN = f"{{{SOS_NS}}}dispatch"


# ---------------------------------------------------------------------------
# scjson-shape helpers
# ---------------------------------------------------------------------------


def _dispatch_element(ref: str) -> dict:
    return {"qname": DISPATCH_QN, "text": "", "attributes": {"ref": ref}}


def _state(state_id: str, *, dispatches: list[dict] | None = None,
           children: list[dict] | None = None,
           parallels: list[dict] | None = None) -> dict:
    node: dict = {"id": state_id}
    if dispatches:
        node["other_element"] = dispatches
    if children:
        node["state"] = children
    if parallels:
        node["parallel"] = parallels
    return node


def _parallel(par_id: str, *, regions: list[dict] | None = None) -> dict:
    node: dict = {"id": par_id}
    if regions:
        node["state"] = regions
    return node


def _chart(states: list[dict] | None = None,
           parallels: list[dict] | None = None) -> dict:
    root: dict = {"version": 1.0, "datamodel_attribute": "ecmascript"}
    if states:
        root["state"] = states
    if parallels:
        root["parallel"] = parallels
    return root


def _peer_states(n: int, prefix: str = "s") -> list[dict]:
    """Build n sibling `<state>` nodes with ids prefix0..prefix{n-1}."""
    return [_state(f"{prefix}{i}") for i in range(n)]


# ---------------------------------------------------------------------------
# Loader-bridge harness — write a temporary chart file, then drive the lint
# rule with a synthetic loader that returns a known scjson dict regardless
# of the on-disk content. This decouples the test from scjson availability.
# ---------------------------------------------------------------------------


def _make_anchor_file(tmp_path: Path, name: str = "chart.scxml") -> Path:
    """Create an empty `.scxml` file solely for path anchoring.

    The lint rules require the chart_path to exist on disk (FileNotFoundError
    on missing). Content is irrelevant — the synthetic loader returns a
    canned dict — but the file MUST exist for the existence check.
    """
    f = tmp_path / name
    f.write_text(
        "<?xml version=\"1.0\"?>\n<scxml xmlns=\"http://www.w3.org/2005/07/scxml\"/>\n",
        encoding="utf-8",
    )
    return f


# ---------------------------------------------------------------------------
# Frozen-enum + rule-id sanity
# ---------------------------------------------------------------------------


def test_frozen_defaults_match_spec():
    """Per SOS-12 §10: depth cap 8 (PCDN-005), legibility threshold 15
    (PCDN-003); rule ids land in the SCXML-LINT-DISP-N series per
    SOS-01 §15 (commit `4f33c1e`) reservation."""
    assert DEFAULT_MAX_DEPTH == 8
    assert DEFAULT_LEGIBILITY_THRESHOLD == 15
    assert RULE_DISPATCH_DEPTH == "SCXML-LINT-DISP-1"
    assert RULE_LEGIBILITY == "SCXML-LINT-DISP-2"


# ---------------------------------------------------------------------------
# SCXML-LINT-DISP-1 — dispatch-tree depth cap
# ---------------------------------------------------------------------------


def _build_chain_loader(depth: int):
    """Synthetic loader for a depth-N dispatch chain.

    Root chart dispatches into level_1.scxml; level_K dispatches into
    level_{K+1}.scxml; level_{depth} is a leaf with no dispatch.

    The depth value is the deepest sub-chart's depth (root sits at 0,
    so a `depth=8` chain has the root + 8 sub-charts, last one at depth 8).
    """

    def fake_loader(path: Path) -> dict:
        stem = path.stem
        if stem == "chart":
            # root anchor
            return _chart([_state("s", dispatches=[_dispatch_element("level_1.scxml")])])
        try:
            idx = int(stem.split("_")[1])
        except (IndexError, ValueError):
            return _chart([_state("leaf")])
        if idx >= depth:
            return _chart([_state("leaf")])
        return _chart(
            [_state("s", dispatches=[_dispatch_element(f"level_{idx + 1}.scxml")])]
        )

    return fake_loader


def test_disp1_chart_at_depth_7_passes(tmp_path):
    """Chain depth 7 (last sub-chart sits at depth 7) is below the
    default cap (8) and passes."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_dispatch_depth(anchor, loader=_build_chain_loader(depth=7))
    assert diags == []


def test_disp1_chart_at_depth_8_passes_at_cap(tmp_path):
    """Chain depth 8 — last sub-chart sits exactly at the cap; PASSES.

    The cap is inclusive: depth==max_depth is admissible, depth>max_depth
    rejects. This matches the annotation parser's own §6.5 semantics
    (the parser raises only when depth would exceed max_depth, not when
    it equals).
    """
    anchor = _make_anchor_file(tmp_path)
    diags = check_dispatch_depth(anchor, loader=_build_chain_loader(depth=8))
    assert diags == []


def test_disp1_chart_at_depth_9_fails(tmp_path):
    """Chain depth 9 — one level past the default cap; one diagnostic."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_dispatch_depth(anchor, loader=_build_chain_loader(depth=9))
    assert len(diags) == 1
    d = diags[0]
    assert isinstance(d, LintDiagnostic)
    assert d.rule_id == "SCXML-LINT-DISP-1"
    assert d.severity == "error"
    assert "max_depth=8" in d.message
    # Message must cite §6.5 and PCDN-SOS-12-005 per the spec authority chain.
    assert "§6.5" in d.message
    assert "PCDN-SOS-12-005" in d.message


def test_disp1_custom_max_depth_4_with_chain_at_depth_5_fails(tmp_path):
    """Custom max_depth=4 rejects a chain at depth 5 even though the
    default-cap (8) would have admitted it."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_dispatch_depth(
        anchor, max_depth=4, loader=_build_chain_loader(depth=5)
    )
    assert len(diags) == 1
    assert diags[0].rule_id == "SCXML-LINT-DISP-1"
    assert "max_depth=4" in diags[0].message


def test_disp1_custom_max_depth_4_with_chain_at_depth_4_passes(tmp_path):
    """Custom max_depth=4 admits a chain at exactly depth 4 (cap inclusive)."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_dispatch_depth(
        anchor, max_depth=4, loader=_build_chain_loader(depth=4)
    )
    assert diags == []


def test_disp1_chart_with_no_dispatches_passes(tmp_path):
    """A chart with zero `<sos:dispatch>` elements at any level is a
    flat chart and always passes the depth-cap (depth 0)."""
    anchor = _make_anchor_file(tmp_path)

    def fake_loader(path: Path) -> dict:
        return _chart([_state("alone"), _state("also_alone")])

    diags = check_dispatch_depth(anchor, loader=fake_loader)
    assert diags == []


def test_disp1_missing_chart_path_raises(tmp_path):
    """A non-existent chart path raises FileNotFoundError before any
    loader call (defensive — the rule is a chart-author tool, not a
    silent skip)."""
    missing = tmp_path / "does_not_exist.scxml"
    with pytest.raises(FileNotFoundError):
        check_dispatch_depth(missing)


# ---------------------------------------------------------------------------
# SCXML-LINT-DISP-2 — peer-state legibility threshold
# ---------------------------------------------------------------------------


def _root_with_n_peers_loader(n: int, *, prefix: str = "s"):
    """Synthetic loader returning a chart whose root has n peer states."""

    def fake_loader(path: Path) -> dict:
        return _chart(_peer_states(n, prefix=prefix))

    return fake_loader


def test_disp2_15_peers_at_root_passes(tmp_path):
    """15 peers at the root sits exactly AT the default threshold and PASSES.

    The threshold is inclusive at the limit: 15 ≤ 15 passes, 16 > 15
    fails. This matches the SOS-12 §8.5 worked-example narrative ("the
    `http_post` chart at 15 states sits exactly at the threshold").
    """
    anchor = _make_anchor_file(tmp_path)
    diags = check_legibility(anchor, loader=_root_with_n_peers_loader(15))
    assert diags == []


def test_disp2_16_peers_at_root_fails(tmp_path):
    """16 peers at the root breaches the default threshold (15) and
    yields exactly one diagnostic citing the rule id, severity, and
    extract_region_to_subchart recommendation."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_legibility(anchor, loader=_root_with_n_peers_loader(16))
    assert len(diags) == 1
    d = diags[0]
    assert d.rule_id == "SCXML-LINT-DISP-2"
    assert d.severity == "error"
    assert "16 peer states" in d.message
    # The SOS-11 structural-add tool MUST be named in the diagnostic per
    # the §9.2 tool-surface behaviour clause + §9 enforcement intent.
    assert "extract_region_to_subchart" in d.message


def test_disp2_breach_message_cites_spec(tmp_path):
    """The diagnostic must cite SOS-12 §9 and PCDN-SOS-12-003 so a chart
    author can trace the rule back to its ratified authority."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_legibility(anchor, loader=_root_with_n_peers_loader(16))
    msg = diags[0].message
    assert "§9" in msg
    assert "PCDN-SOS-12-003" in msg


def test_disp2_breach_at_depth_3_names_correct_location(tmp_path):
    """A breach inside a nested state at depth 3 names the right
    chart_path AND a dotted-id location path."""
    anchor = _make_anchor_file(tmp_path)

    def fake_loader(path: Path) -> dict:
        # outer → middle → inner, where inner carries 16 peers.
        inner = _state("inner", children=_peer_states(16, prefix="leaf"))
        middle = _state("middle", children=[inner])
        outer = _state("outer", children=[middle])
        return _chart([outer])

    diags = check_legibility(anchor, loader=fake_loader)
    assert len(diags) == 1
    d = diags[0]
    assert d.rule_id == "SCXML-LINT-DISP-2"
    assert d.chart_path == str(anchor)
    # The location should name `inner` (the breaching node) and include
    # its ancestor path.
    assert "inner" in d.location
    assert "outer" in d.location
    assert "extract_region_to_subchart" in d.message


def test_disp2_custom_threshold_5_with_6_peers_fails(tmp_path):
    """A project-overridden legibility_threshold=5 rejects 6 peers even
    though the default (15) would have admitted them."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_legibility(
        anchor, legibility_threshold=5, loader=_root_with_n_peers_loader(6)
    )
    assert len(diags) == 1
    assert "6 peer states" in diags[0].message
    assert "limit is 5" in diags[0].message


def test_disp2_custom_threshold_5_with_5_peers_passes(tmp_path):
    """A project-overridden legibility_threshold=5 admits 5 peers
    (inclusive at the limit)."""
    anchor = _make_anchor_file(tmp_path)
    diags = check_legibility(
        anchor, legibility_threshold=5, loader=_root_with_n_peers_loader(5)
    )
    assert diags == []


def test_disp2_zero_threshold_rejected_as_invalid():
    """A legibility_threshold of 0 is not meaningful (chart would be
    forced to be empty); reject as a configuration error."""
    with pytest.raises(ValueError):
        check_legibility("/tmp/anything.scxml", legibility_threshold=0)


def test_disp2_multiple_levels_breaching_yield_multiple_diagnostics(tmp_path):
    """Two nested levels that both breach yield two diagnostics in
    document order (outer breach first, inner breach second)."""
    anchor = _make_anchor_file(tmp_path)

    def fake_loader(path: Path) -> dict:
        # Inner state with 16 peers (breach #2).
        inner_breach = _state("inner_breach", children=_peer_states(16, prefix="leaf"))
        # Outer level: 16 peers, one of which is the breaching inner state.
        # We pad with 15 trivial peers + the inner_breach state = 16 peers.
        outer_peers = _peer_states(15, prefix="o") + [inner_breach]
        return _chart(outer_peers)

    diags = check_legibility(anchor, loader=fake_loader)
    assert len(diags) == 2
    # Both must be DISP-2 errors with the structural-add recommendation.
    for d in diags:
        assert d.rule_id == "SCXML-LINT-DISP-2"
        assert d.severity == "error"
        assert "extract_region_to_subchart" in d.message


def test_disp2_parallel_regions_counted_as_peers(tmp_path):
    """A `<parallel>` with 16 region children breaches the threshold at
    the parallel's own level (each region is a peer state of every
    other region)."""
    anchor = _make_anchor_file(tmp_path)

    def fake_loader(path: Path) -> dict:
        par = _parallel("p", regions=_peer_states(16, prefix="r"))
        return _chart([_state("wrapper", parallels=[par])])

    diags = check_legibility(anchor, loader=fake_loader)
    assert len(diags) == 1
    d = diags[0]
    assert d.rule_id == "SCXML-LINT-DISP-2"
    # The breaching level is owned by `p` (the parallel); the location
    # path should name it.
    assert "p" in d.location


def test_disp2_missing_chart_path_raises(tmp_path):
    """Non-existent chart path raises FileNotFoundError (parallels
    SCXML-LINT-DISP-1's behaviour)."""
    missing = tmp_path / "does_not_exist.scxml"
    with pytest.raises(FileNotFoundError):
        check_legibility(missing)


# ---------------------------------------------------------------------------
# SCXML-LINT-DISP-2 — count_parallel_regions kwarg (PCDN-SOS-12-008,
# SOS-12 §15 2026-05-27 SOS12B-PCDN-008)
# ---------------------------------------------------------------------------


def test_disp2_count_parallel_regions_default_is_strict():
    """The kwarg's default MUST be `True` (strict mode, Wave-3L semantics).

    Frozen-enumeration policy: Specification Required for the keyword's
    existence and default per SOS-12 §15 2026-05-27 SOS12B-PCDN-008.
    Changing the default would silently flip every existing caller into
    a more-permissive mode and is prohibited without a §15 amendment.
    """
    import inspect

    sig = inspect.signature(check_legibility)
    assert "count_parallel_regions" in sig.parameters
    param = sig.parameters["count_parallel_regions"]
    assert param.default is True
    # Keyword-only — mirrors the rest of the kwargs surface.
    assert param.kind == inspect.Parameter.KEYWORD_ONLY


def test_disp2_liberal_mode_admits_parallel_with_16_regions(tmp_path):
    """A `<parallel>` with 16 region children PASSES under
    `count_parallel_regions=False` (liberal mode) even though the strict
    default would reject it.

    Per PCDN-SOS-12-008 ratification: under liberal mode the
    `<parallel>`'s region children do NOT count as peers at the
    parallel's own level. The `<parallel>` ITSELF still counts as one
    peer at its parent's level (here the wrapping state — well below
    threshold).
    """
    anchor = _make_anchor_file(tmp_path)

    def fake_loader(path: Path) -> dict:
        par = _parallel("p", regions=_peer_states(16, prefix="r"))
        return _chart([_state("wrapper", parallels=[par])])

    diags = check_legibility(
        anchor, count_parallel_regions=False, loader=fake_loader
    )
    assert diags == []


def test_disp2_strict_mode_rejects_parallel_with_16_regions(tmp_path):
    """The same 16-region parallel still FAILS under the strict default.

    Companion to the liberal-mode case — pins that the two modes
    actually disagree on the contentious shape (a `<parallel>` with
    many regions). Without this pin the liberal-mode test could pass
    trivially if the strict mode were also silently passing.
    """
    anchor = _make_anchor_file(tmp_path)

    def fake_loader(path: Path) -> dict:
        par = _parallel("p", regions=_peer_states(16, prefix="r"))
        return _chart([_state("wrapper", parallels=[par])])

    # Default (strict) — should fail.
    diags_default = check_legibility(anchor, loader=fake_loader)
    assert len(diags_default) == 1
    assert diags_default[0].rule_id == "SCXML-LINT-DISP-2"
    assert "p" in diags_default[0].location

    # Explicit strict — same result (pins the kwarg=True path).
    diags_strict = check_legibility(
        anchor, count_parallel_regions=True, loader=fake_loader
    )
    assert len(diags_strict) == 1
    assert diags_strict[0].location == diags_default[0].location


def test_disp2_liberal_mode_still_rejects_alternatives_inside_region(tmp_path):
    """Liberal mode disables the threshold check AT the parallel's own
    level only — alternatives INSIDE a region still count normally.

    Concretely: a `<parallel>` whose single region carries 16 `<state>`
    children breaches the threshold at that region's level (16 peer
    `<state>` alternatives) regardless of `count_parallel_regions`. The
    liberal-mode opt-out applies to the parallel-level count, not to
    the recursive descent.
    """
    anchor = _make_anchor_file(tmp_path)

    def fake_loader(path: Path) -> dict:
        # The region itself is a `<state>` (per scjson shape) carrying
        # 16 child `<state>`s — those 16 are alternatives, not regions.
        region = _state("region", children=_peer_states(16, prefix="alt"))
        par = _parallel("p", regions=[region])
        return _chart([_state("wrapper", parallels=[par])])

    diags = check_legibility(
        anchor, count_parallel_regions=False, loader=fake_loader
    )
    assert len(diags) == 1
    d = diags[0]
    assert d.rule_id == "SCXML-LINT-DISP-2"
    # The breach is at `region`, NOT at `p` — the parallel-level count
    # is skipped under liberal mode but the in-region alternatives still
    # exceed the threshold.
    assert "region" in d.location
    # And `p` should appear in the ancestor path because it's part of
    # the prefix walk; the breach owner is `region`.
    assert d.location.endswith("region")
    assert "extract_region_to_subchart" in d.message


# ---------------------------------------------------------------------------
# Fixture-driven integration tests (require scjson on PATH)
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sos_12"


def _have_scjson() -> bool:
    """Best-effort detection of scjson availability."""
    try:
        from loader import load_chart  # noqa: F401
    except Exception:
        return False
    return True


def test_fixture_deep_chain_at_cap_passes():
    """The existing 8-deep fixture (`deep_chain/`) sits AT the cap and
    PASSES the depth-cap rule."""
    if not _have_scjson():
        pytest.skip("scjson unavailable; fixture-driven test skipped")
    root = _FIXTURE_DIR / "deep_chain" / "level_0.scxml"
    if not root.exists():
        pytest.skip("deep_chain fixture missing")
    try:
        diags = check_dispatch_depth(root)
    except RuntimeError as exc:
        pytest.skip(f"scjson load failed: {exc}")
    assert diags == []


def test_fixture_deep_chain_overflow_fails():
    """The existing 9-deep fixture (`deep_chain_overflow/`) sits ONE
    PAST the cap and fails the depth-cap rule with a diagnostic citing
    PCDN-SOS-12-005."""
    if not _have_scjson():
        pytest.skip("scjson unavailable; fixture-driven test skipped")
    root = _FIXTURE_DIR / "deep_chain_overflow" / "level_0.scxml"
    if not root.exists():
        pytest.skip("deep_chain_overflow fixture missing")
    try:
        diags = check_dispatch_depth(root)
    except RuntimeError as exc:
        pytest.skip(f"scjson load failed: {exc}")
    assert len(diags) == 1
    assert diags[0].rule_id == "SCXML-LINT-DISP-1"
    assert "PCDN-SOS-12-005" in diags[0].message


def test_fixture_single_level_dispatch_passes_legibility():
    """The single-level dispatch fixture has 2 peer states at the root
    and 0 elsewhere — well under the default threshold."""
    if not _have_scjson():
        pytest.skip("scjson unavailable; fixture-driven test skipped")
    chart = _FIXTURE_DIR / "parent_single_level.scxml"
    if not chart.exists():
        pytest.skip("parent_single_level fixture missing")
    try:
        diags = check_legibility(chart)
    except RuntimeError as exc:
        pytest.skip(f"scjson load failed: {exc}")
    assert diags == []
