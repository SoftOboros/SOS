-- =============================================================================
-- sos_rate_divider.vhd  --  L0 programmable rate divider (portable VHDL-2008)
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.11
--   Per 2026-05-23 ratification (§15 initial entry) and the 2026-05-23
--   continuation-amendment PCDN walkthrough (§15 second + third 2026-05-23
--   entries): control primitive, tick-style 1-cycle-pulse i/o (PCDN-A-002
--   degenerate-pulse form for rate primitives -- §10 reconciliation row),
--   parameters UPPER_CASE (PCDN-A-001), synchronous active-high reset
--   (PCDN-A-003, INV-S-HDL-A-1), one-hot internal FSM convention is N/A here
--   (the counter is a binary counter, not an FSM; §5.2 / INV-S-HDL-A-4 only
--   binds FSM-shaped internal state, not arithmetic counters).
--
--   Per task scope (2026-05-23 walkthrough amendments folded against §6.11):
--     * The divider is **tick-driven**: the internal counter advances on
--       each asserted `tick_in`, not on every `clk` edge.  When `tick_in`
--       is idle, the counter holds.  This is the natural composition with
--       an upstream `sos_tick_gen` (§6.8) -- one rate-generator emits the
--       fundamental tick; downstream rate dividers cleanly subdivide it.
--     * `DIVISOR` is a **mandatory** generic (no default, INV-S-HDL-A-5)
--       with the static-elaboration constraint `DIVISOR >= 1`.  Note that
--       `DIVISOR = 0` is **forbidden** rather than treated as "no ticks
--       ever"; the latter is encodable at the chart level by gating
--       `tick_in` instead.  Forbidding `DIVISOR = 0` keeps the primitive's
--       arithmetic invariant (counter range is `[0, DIVISOR-1]`) well-defined.
--     * `INITIAL_COUNTER` is a **mandatory** generic (no default,
--       INV-S-HDL-A-5) with the static-elaboration constraint
--       `0 <= INITIAL_COUNTER < DIVISOR`.  Allows N parallel instances to
--       be staggered in phase off a shared `tick_in` source (e.g. for
--       multi-channel scan-out pacing where each channel fires on a
--       different sub-cycle of the same divide ratio).
--     * Degenerate case `DIVISOR = 1`: every `tick_in` pulse produces a
--       `tick_out` pulse the same cycle (passthrough).  Forced by the
--       counter-equals-`DIVISOR-1` test reducing to "counter equals 0",
--       which is true on every accepted `tick_in` when reset value is 0.
--       `INITIAL_COUNTER` must be `0` when `DIVISOR = 1` (the only legal
--       value under the bound).
--     * `counter` is exposed as an **observability port** (not a control
--       output) carrying the current counter value, width
--       `ceil(log2(DIVISOR))`.  Driven by the same register that gates
--       `tick_out`; downstream consumers MAY use it for debug visibility,
--       but the primitive's behavioural contract does not depend on it
--       being consumed.
--
-- Cited invariants (this primitive does not redefine them):
--   INV-SOS-A   chart-as-source                     (SOS-07 §6)
--   INV-SOS-B   vectors-as-deliverable              (SOS-07 §6)
--   INV-SOS-E   explicit AuthorityRelationship      (SOS-07 §6)
--   INV-SOS-G   verified-codegen position           (SOS-07 §6)
--   INV-SOS-H   vector-to-chart traceability        (SOS-07 §6)
--   INV-S-HDL-1 handshake-compatible ports          (SOS-08 §7; pulse form)
--   INV-S-HDL-2 static-allocation discipline        (SOS-08 §7)
--   INV-S-HDL-3 cross-domain isolation              (SOS-08 §7; N/A single-domain)
--   INV-S-HDL-4 cooperative-only at v1              (SOS-08 §7)
--   INV-S-HDL-5 vector-to-chart traceability (HDL)  (SOS-08 §7)
--   INV-S-HDL-A-1 uniform sync active-high reset    (SOS-08-A §7)
--   INV-S-HDL-A-2 handshake associativity           (SOS-08-A §7)
--   INV-S-HDL-A-3 vendor-shim byte-identical wrap   (SOS-08-A §7; portable-only)
--   INV-S-HDL-A-4 one-hot internal FSM by default   (SOS-08-A §7; N/A counter)
--   INV-S-HDL-A-5 mandatory parameters, no default  (SOS-08-A §7)
--
-- Behavioural contract:
--   counter starts at INITIAL_COUNTER on reset.  On every cycle that
--   `tick_in` is asserted:
--     * If counter == DIVISOR-1, `tick_out` pulses for one cycle and
--       counter is loaded with 0.
--     * Otherwise, counter increments by 1 and `tick_out` stays low.
--   `tick_out` is combinational on `(tick_in, counter)`: it is asserted
--   exactly on the same cycle the qualifying `tick_in` pulse arrives.
--   When `tick_in` is low, `tick_out` is low and counter is held.
--
-- Resource cost:
--   ceil(log2(DIVISOR)) counter FFs + a single comparator + a one-cycle
--   pulse multiplexer.
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

package sos_rate_divider_pkg is
  -- ceil(log2(n)) for n >= 1.  Returns 1 for n=1 so the counter port is
  -- always at least 1 bit wide (avoids zero-width vectors in VHDL).
  function clog2_min1 (n : positive) return positive;
end package sos_rate_divider_pkg;

package body sos_rate_divider_pkg is
  function clog2_min1 (n : positive) return positive is
    variable v : natural  := n - 1;
    variable r : positive := 1;
  begin
    if n <= 1 then
      return 1;
    end if;
    while v > 1 loop
      v := v / 2;
      r := r + 1;
    end loop;
    return r;
  end function;
end package body sos_rate_divider_pkg;

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

library work;
  use work.sos_rate_divider_pkg.all;

entity sos_rate_divider is
  generic (
    -- Mandatory: no default (INV-S-HDL-A-5).  DIVISOR >= 1 required;
    -- DIVISOR = 0 is forbidden (see header behavioural contract note).
    DIVISOR         : positive;
    -- Mandatory: no default (INV-S-HDL-A-5).  Must satisfy
    -- 0 <= INITIAL_COUNTER < DIVISOR.  Enables staggered division phases.
    INITIAL_COUNTER : natural
  );
  port (
    clk      : in  std_logic;
    rst      : in  std_logic;  -- synchronous active-high (INV-S-HDL-A-1)
    tick_in  : in  std_logic;
    tick_out : out std_logic;
    -- Observability: current counter value, width = ceil(log2(DIVISOR))
    -- (minimum 1 bit so DIVISOR = 1 still has a well-formed port).
    counter  : out std_logic_vector(clog2_min1(DIVISOR) - 1 downto 0)
  );
end entity sos_rate_divider;

architecture rtl of sos_rate_divider is

  constant CNT_W : positive := clog2_min1(DIVISOR);

  signal counter_q : unsigned(CNT_W - 1 downto 0);
  signal at_limit  : std_logic;

begin

  ----------------------------------------------------------------------------
  -- Elaboration-time validation of the parameter bounds.
  ----------------------------------------------------------------------------
  assert DIVISOR >= 1
    report "sos_rate_divider: SOS-08-A §6.11 requires DIVISOR >= 1; "
           & "got DIVISOR=" & integer'image(DIVISOR)
    severity failure;

  assert INITIAL_COUNTER < DIVISOR
    report "sos_rate_divider: SOS-08-A §6.11 requires INITIAL_COUNTER < DIVISOR; "
           & "got INITIAL_COUNTER=" & integer'image(INITIAL_COUNTER)
           & " DIVISOR=" & integer'image(DIVISOR)
    severity failure;

  ----------------------------------------------------------------------------
  -- Comparator: counter has reached the divide threshold this cycle.
  -- For DIVISOR=1 the threshold is 0, so at_limit is permanently '1' and
  -- tick_out tracks tick_in (passthrough).
  ----------------------------------------------------------------------------
  at_limit <= '1' when counter_q = to_unsigned(DIVISOR - 1, CNT_W) else '0';

  ----------------------------------------------------------------------------
  -- tick_out: combinational on (tick_in, at_limit).  Asserted exactly on
  -- the cycle the qualifying tick_in arrives.
  ----------------------------------------------------------------------------
  tick_out <= tick_in and at_limit;

  ----------------------------------------------------------------------------
  -- Counter update (tick-driven, not clock-driven).
  ----------------------------------------------------------------------------
  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        counter_q <= to_unsigned(INITIAL_COUNTER, CNT_W);
      elsif tick_in = '1' then
        if at_limit = '1' then
          counter_q <= (others => '0');
        else
          counter_q <= counter_q + 1;
        end if;
      end if;
      -- tick_in = '0' -> counter holds (no clock-cycle drift).
    end if;
  end process;

  counter <= std_logic_vector(counter_q);

end architecture rtl;
