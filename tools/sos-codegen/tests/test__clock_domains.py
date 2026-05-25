"""SOS-08-D wave-7a (2026-05-25 §15) — unit tests for the
``_clock_domains`` shared helper.

@spec docs/concepts/SOS-08-D-CONCEPTS.md §15 (2026-05-25
      "PCDN-SOS-08-D-008 ratification — `<sos:clock_domains>` element
       formalised").

The helper is consumed by ``transliterate_sva_bind.py`` (D-side walker,
this wave) and will be consumed by ``transliterate_hdl_sv_tb.py`` (E-
side walker) in wave-7b — so this test module exercises the public
API in isolation rather than relying on either walker's end-to-end
behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


_clock_domains = pytest.importorskip(
    "_clock_domains",
    reason="_clock_domains helper not importable — wave-7a suite skips "
    "until the module lands.",
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _block(*clocks: dict) -> dict:
    """Build a chart-IR dict with a ``<sos:clock_domains>`` block from a
    list of ``<sos:clock>`` attribute dicts."""
    return {
        "sos:clock_domains": {
            "sos:clock": list(clocks),
        }
    }


# ---------------------------------------------------------------------------
# Implicit-default behaviour (backwards-compat MUST from §15).
# ---------------------------------------------------------------------------


class TestParseClockDomainsImplicitDefault:
    """Charts without ``<sos:clock_domains>`` MUST get the implicit
    default-clock map.  Wave-1 byte-identity hinges on this contract."""

    def test_empty_chart_returns_implicit_default_clock(self):
        m = _clock_domains.parse_clock_domains({})
        assert "clk" in m
        assert len(m) == 1
        decl = m["clk"]
        assert decl.name == "clk"
        assert decl.source == "chart_root"
        assert decl.kind == "rising"

    def test_implicit_default_clock_carries_v1_defaults(self):
        decl = _clock_domains.implicit_default_clock()
        assert decl.name == "clk"
        assert decl.source == "chart_root"
        assert decl.kind == "rising"
        assert decl.period_ns == 10.0
        assert decl.duty_cycle == 0.5
        assert decl.phase_ns == 0.0

    def test_none_chart_returns_implicit_default_clock(self):
        m = _clock_domains.parse_clock_domains(None)
        assert "clk" in m
        assert len(m) == 1
        assert m["clk"] == _clock_domains.implicit_default_clock()

    def test_chart_with_empty_clock_domains_block_falls_back_to_default(self):
        """An empty ``<sos:clock_domains/>`` element with no children
        defensively yields the implicit default — chart authors who
        write the wrapper but no children still get a working map."""
        m = _clock_domains.parse_clock_domains({"sos:clock_domains": {}})
        assert m == {"clk": _clock_domains.implicit_default_clock()}


# ---------------------------------------------------------------------------
# Single-clock parsing + defaults.
# ---------------------------------------------------------------------------


class TestParseClockDomainsSingleClock:
    """One ``<sos:clock>`` child — verify all optional attributes
    default per §15."""

    def test_single_clock_minimum_attributes(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "clk", "kind": "rising"})
        )
        assert "clk" in m
        decl = m["clk"]
        assert decl.name == "clk"
        # source omitted → defaults to name.
        assert decl.source == "clk"
        assert decl.kind == "rising"
        assert decl.period_ns == 10.0
        assert decl.duty_cycle == 0.5
        assert decl.phase_ns == 0.0

    def test_source_omitted_defaults_to_name(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "myclk", "kind": "rising"})
        )
        assert m["myclk"].source == "myclk"

    def test_source_present_overrides_default(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "clk", "source": "pll_a", "kind": "rising"})
        )
        assert m["clk"].source == "pll_a"

    def test_period_ns_default_applied_when_omitted(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising"})
        )
        assert m["c"].period_ns == 10.0

    def test_period_ns_present_overrides_default(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising", "period_ns": 5.0})
        )
        assert m["c"].period_ns == 5.0

    def test_period_ns_accepts_string_form_from_xml_loader(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising", "period_ns": "12.5"})
        )
        assert m["c"].period_ns == 12.5

    def test_duty_cycle_default_applied_when_omitted(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising"})
        )
        assert m["c"].duty_cycle == 0.5

    def test_duty_cycle_present_overrides_default(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising", "duty_cycle": 0.4})
        )
        assert m["c"].duty_cycle == 0.4

    def test_phase_ns_default_applied_when_omitted(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising"})
        )
        assert m["c"].phase_ns == 0.0

    def test_phase_ns_present_overrides_default(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising", "phase_ns": 2.5})
        )
        assert m["c"].phase_ns == 2.5

    def test_falling_kind_accepted(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "falling"})
        )
        assert m["c"].kind == "falling"

    def test_single_clock_as_dict_not_list(self):
        """Loaders may emit a sole child as a bare dict rather than a
        single-element list — both shapes MUST parse to the same map."""
        m = _clock_domains.parse_clock_domains(
            {"sos:clock_domains": {"sos:clock": {"name": "c", "kind": "rising"}}}
        )
        assert "c" in m
        assert m["c"].name == "c"


# ---------------------------------------------------------------------------
# Aliases — multiple clocks sharing (source, kind).
# ---------------------------------------------------------------------------


class TestAliasResolution:
    """Two ``<sos:clock>`` declarations with the same resolved
    ``(source, kind)`` pair are aliases — same domain, different
    name.  Canonical name = alphabetic-first."""

    def test_two_clocks_sharing_source_and_kind_are_aliases(self):
        m = _clock_domains.parse_clock_domains(_block(
            {"name": "fast", "source": "pll_a", "kind": "rising"},
            {"name": "aclk", "source": "pll_a", "kind": "rising"},
        ))
        # Both declarations land in the map under their own names.
        assert set(m.keys()) == {"fast", "aclk"}
        # Both resolve to the same canonical (alphabetic-first).
        assert _clock_domains.canonical_name_for_pair(
            "pll_a", "rising", m
        ) == "aclk"

    def test_canonical_name_for_pair_alphabetic_first(self):
        m = _clock_domains.parse_clock_domains(_block(
            {"name": "zclk", "source": "src", "kind": "rising"},
            {"name": "aclk", "source": "src", "kind": "rising"},
            {"name": "mclk", "source": "src", "kind": "rising"},
        ))
        assert _clock_domains.canonical_name_for_pair(
            "src", "rising", m
        ) == "aclk"

    def test_canonical_independent_of_declaration_order(self):
        """The canonical name MUST be alphabetic-first regardless of
        the order in which `<sos:clock>` children are declared."""
        m_forward = _clock_domains.parse_clock_domains(_block(
            {"name": "aclk", "source": "src", "kind": "rising"},
            {"name": "bclk", "source": "src", "kind": "rising"},
        ))
        m_reverse = _clock_domains.parse_clock_domains(_block(
            {"name": "bclk", "source": "src", "kind": "rising"},
            {"name": "aclk", "source": "src", "kind": "rising"},
        ))
        assert _clock_domains.canonical_name_for_pair(
            "src", "rising", m_forward
        ) == "aclk"
        assert _clock_domains.canonical_name_for_pair(
            "src", "rising", m_reverse
        ) == "aclk"

    def test_resolve_alias_returns_canonical_triple(self):
        m = _clock_domains.parse_clock_domains(_block(
            {"name": "fast", "source": "pll_a", "kind": "rising"},
            {"name": "aclk", "source": "pll_a", "kind": "rising"},
        ))
        # 'fast' is the queried alias; canonical is 'aclk'.
        canonical, source, kind = _clock_domains.resolve_alias("fast", m)
        assert canonical == "aclk"
        assert source == "pll_a"
        assert kind == "rising"

    def test_resolve_alias_on_canonical_returns_itself(self):
        """``resolve_alias('aclk', ...)`` where 'aclk' is itself the
        canonical name MUST return ('aclk', ...)."""
        m = _clock_domains.parse_clock_domains(_block(
            {"name": "fast", "source": "pll_a", "kind": "rising"},
            {"name": "aclk", "source": "pll_a", "kind": "rising"},
        ))
        canonical, _, _ = _clock_domains.resolve_alias("aclk", m)
        assert canonical == "aclk"

    def test_resolve_alias_raises_keyerror_for_unknown_name(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising"})
        )
        with pytest.raises(KeyError, match=r"not declared"):
            _clock_domains.resolve_alias("nope", m)

    def test_canonical_name_for_pair_raises_keyerror_for_unknown_pair(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "source": "s1", "kind": "rising"})
        )
        with pytest.raises(KeyError):
            _clock_domains.canonical_name_for_pair("unknown", "rising", m)

    def test_pair_of_returns_source_kind(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "source": "pll_a", "kind": "falling"})
        )
        assert _clock_domains.pair_of("c", m) == ("pll_a", "falling")

    def test_pair_of_raises_keyerror_for_unknown_name(self):
        m = _clock_domains.parse_clock_domains(
            _block({"name": "c", "kind": "rising"})
        )
        with pytest.raises(KeyError):
            _clock_domains.pair_of("nope", m)

    def test_same_source_different_kind_is_not_an_alias(self):
        """Two clocks with the same source but different kinds are
        DISTINCT domains — same-source-different-kind is a CDC
        boundary per §15."""
        m = _clock_domains.parse_clock_domains(_block(
            {"name": "fast", "source": "pll_a", "kind": "rising"},
            {"name": "fast_n", "source": "pll_a", "kind": "falling"},
        ))
        assert _clock_domains.canonical_name_for_pair(
            "pll_a", "rising", m
        ) == "fast"
        assert _clock_domains.canonical_name_for_pair(
            "pll_a", "falling", m
        ) == "fast_n"
        # Pairs differ.
        assert _clock_domains.pair_of("fast", m) != _clock_domains.pair_of(
            "fast_n", m
        )


# ---------------------------------------------------------------------------
# Kind validation.
# ---------------------------------------------------------------------------


class TestKindValidation:
    """``validate_kind`` enforces the §15 Standards-Action enum."""

    def test_validate_kind_rising_is_noop(self):
        assert _clock_domains.validate_kind("rising") is None

    def test_validate_kind_falling_is_noop(self):
        assert _clock_domains.validate_kind("falling") is None

    @pytest.mark.parametrize(
        "reserved",
        ["both", "quadrature_pair", "three_phase", "waltz"],
    )
    def test_validate_kind_reserved_kinds_raise(self, reserved):
        with pytest.raises(
            _clock_domains.UnsupportedClockKindError,
            match=r"SOS-08-D wave-future-clkkind:",
        ):
            _clock_domains.validate_kind(reserved)

    def test_validate_kind_unknown_value_raises(self):
        with pytest.raises(
            _clock_domains.UnsupportedClockKindError,
            match=r"SOS-08-D wave-future-clkkind:",
        ):
            _clock_domains.validate_kind("sideways")

    def test_supported_kinds_constant_exposed(self):
        assert "rising" in _clock_domains.SUPPORTED_KINDS
        assert "falling" in _clock_domains.SUPPORTED_KINDS

    def test_reserved_kinds_constant_exposed(self):
        for k in ("both", "quadrature_pair", "three_phase", "waltz"):
            assert k in _clock_domains.RESERVED_KINDS


class TestParseClockDomainsReservedKind:
    """Parsing a chart that declares a reserved-future kind MUST raise
    at parse time (not at emit time) — the chart author finds out
    early."""

    @pytest.mark.parametrize(
        "reserved",
        ["both", "quadrature_pair", "three_phase", "waltz"],
    )
    def test_reserved_kind_in_clock_declaration_raises(self, reserved):
        with pytest.raises(
            _clock_domains.UnsupportedClockKindError,
            match=r"SOS-08-D wave-future-clkkind:",
        ):
            _clock_domains.parse_clock_domains(
                _block({"name": "c", "kind": reserved})
            )


# ---------------------------------------------------------------------------
# Error surface — required attributes.
# ---------------------------------------------------------------------------


class TestParseClockDomainsRequiredAttributes:
    """Missing required attributes (``name=`` or ``kind=``) MUST raise
    with a clear, actionable message."""

    def test_missing_name_raises(self):
        with pytest.raises(
            _clock_domains.ClockDomainsParseError,
            match=r"`name`",
        ):
            _clock_domains.parse_clock_domains(_block({"kind": "rising"}))

    def test_empty_name_raises(self):
        with pytest.raises(
            _clock_domains.ClockDomainsParseError,
            match=r"`name`",
        ):
            _clock_domains.parse_clock_domains(
                _block({"name": "", "kind": "rising"})
            )

    def test_missing_kind_raises(self):
        with pytest.raises(
            _clock_domains.ClockDomainsParseError,
            match=r"`kind`",
        ):
            _clock_domains.parse_clock_domains(_block({"name": "c"}))

    def test_duplicate_name_raises(self):
        with pytest.raises(
            _clock_domains.ClockDomainsParseError,
            match=r"duplicate clock name",
        ):
            _clock_domains.parse_clock_domains(_block(
                {"name": "c", "kind": "rising"},
                {"name": "c", "source": "alt", "kind": "rising"},
            ))

    def test_unparseable_period_ns_raises(self):
        with pytest.raises(
            _clock_domains.ClockDomainsParseError,
            match=r"period_ns",
        ):
            _clock_domains.parse_clock_domains(_block(
                {"name": "c", "kind": "rising", "period_ns": "not-a-float"}
            ))


# ---------------------------------------------------------------------------
# Loader-shape tolerance.
# ---------------------------------------------------------------------------


class TestLoaderShapeTolerance:
    """The helper MUST tolerate both SCXML-namespaced (``sos:clock``)
    and bare (``clock``) keys, since the project's scjson loaders
    differ on namespace stripping."""

    def test_bare_keys_parse_identically_to_namespaced(self):
        namespaced = {
            "sos:clock_domains": {
                "sos:clock": [{"name": "c", "kind": "rising"}]
            }
        }
        bare = {
            "clock_domains": {
                "clock": [{"name": "c", "kind": "rising"}]
            }
        }
        assert _clock_domains.parse_clock_domains(
            namespaced
        ) == _clock_domains.parse_clock_domains(bare)
