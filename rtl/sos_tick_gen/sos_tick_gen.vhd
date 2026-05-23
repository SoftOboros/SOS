-- =============================================================================
-- sos_tick_gen.vhd  --  L0 periodic rate generator (portable VHDL-2008)
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8
--   Per 2026-05-23 ratification (§15) + 2026-05-23 impl wave-1 PCDN
--   amendments (§15 third entry): periodic-tick generator emitting a 1-cycle
--   `tick` pulse every `PERIOD_CYCLES` cycles.  Parameters UPPER_CASE
--   (PCDN-A-001).  Synchronous active-high reset (PCDN-A-003,
--   INV-S-HDL-A-1).  Mandatory PERIOD_CYCLES and INITIAL_PHASE generics
--   carry no defaults (PCDN-A-004, INV-S-HDL-A-5; the sole INV-S-HDL-A-5
--   default-exception is `GRANT_LATENCY_CYCLES` on `sos_arbiter_rr`, not
--   applicable here).  No internal FSM (counter + comparator only) so
--   INV-S-HDL-A-4 one-hot default is trivially satisfied.
--
--   Spec §6.8 baseline names ports {clk, rst, enable, tick,
--   tick_count[31:0]}.  This implementation specialises the observability
--   port to a modulo `counter` (bare port, width = ceil(log2(PERIOD_CYCLES)))
--   per the wave-1 task contract: a saturating modulo-counter is the witness
--   the §6.8 SVA properties actually need (`period_stable`,
--   `tick_is_pulse`), and matching downstream rate-dividers consume the
--   modulo value not a monotonic counter.  The full 32-bit monotonic
--   counter from the §6.8 draft is dropped.  This narrowing is captured
--   here as a per-primitive impl note pending a future §15 amendment if
--   the broader L0 set needs to reconcile the observability shape.
--
--   `tick` is a bare control output (degenerate req with implicit
--   immediate ack per §10 reconciliation: "pulse-bearing primitives use
--   raw pulses ... the consumer either samples or doesn't").  No
--   `tick_ack` — consumers free-run.  `enable` is a bare control input.
--
-- Cited invariants (this primitive does not redefine them):
--   INV-SOS-A  chart-as-source                     (SOS-07 §6)
--   INV-SOS-B  vectors-as-deliverable              (SOS-07 §6)
--   INV-SOS-E  explicit AuthorityRelationship      (SOS-07 §6)
--   INV-SOS-G  verified-codegen position           (SOS-07 §6)
--   INV-SOS-H  vector-to-chart traceability        (SOS-07 §6)
--   INV-S-HDL-1 handshake-compatible ports         (SOS-08 §7;
--                                                   degenerate raw-pulse form)
--   INV-S-HDL-2 static-allocation discipline       (SOS-08 §7)
--   INV-S-HDL-3 cross-domain isolation             (SOS-08 §7; N/A, single-domain)
--   INV-S-HDL-4 cooperative-only at v1             (SOS-08 §7)
--   INV-S-HDL-5 vector-to-chart traceability (HDL) (SOS-08 §7)
--   INV-S-HDL-A-1 uniform sync active-high reset   (SOS-08-A §7)
--   INV-S-HDL-A-2 handshake associativity          (SOS-08-A §7; trivial — no
--                                                   ready/valid pair)
--   INV-S-HDL-A-3 vendor-shim byte-identical wrap  (SOS-08-A §7; portable-only)
--   INV-S-HDL-A-4 one-hot internal FSM by default  (SOS-08-A §7; no FSM)
--   INV-S-HDL-A-5 mandatory parameters, no default (SOS-08-A §7)
--
-- Behavioural contract:
--   A free-running modulo-PERIOD_CYCLES counter advances each clock while
--   `enable = '1'`.  When the counter reaches `PERIOD_CYCLES - 1`, the
--   combinational `tick` output is asserted for that single cycle, and the
--   counter wraps to 0 on the next rising edge.  When `enable = '0'`, the
--   counter HOLDS its current value (it does NOT reset mid-period) and
--   `tick` is forced low for the duration of the disable.  Reasserting
--   `enable` resumes counting from the held value, preserving the original
--   phase relative to other tick generators that were not paused.
--
--   Synchronous active-high reset clears the counter to INITIAL_PHASE
--   (NOT to 0) so that multi-tick-generator deployments can stagger their
--   phases at reset time.  The caller MUST satisfy
--       0 <= INITIAL_PHASE < PERIOD_CYCLES
--   or the elaboration-time assert below fails.
--
-- Resource cost:  ceil(log2(PERIOD_CYCLES)) counter FFs, one comparator,
--   one AND gate for the enable mask.  No FSM, no synchronizer, no memory.
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

package sos_tick_gen_pkg is
  -- ceil(log2(n)).  Sized so values 0..n-1 fit.
  function clog2_counter (n : positive) return positive;
end package sos_tick_gen_pkg;

package body sos_tick_gen_pkg is
  function clog2_counter (n : positive) return positive is
    variable v : natural  := n - 1;
    variable r : positive := 1;
  begin
    -- For n = 1, counter width is still 1 to give a valid std_logic_vector.
    if n <= 1 then
      return 1;
    end if;
    while v > 1 loop
      v := v / 2;
      r := r + 1;
    end loop;
    return r;
  end function;
end package body sos_tick_gen_pkg;

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

library work;
  use work.sos_tick_gen_pkg.all;

entity sos_tick_gen is
  generic (
    -- Mandatory: no default (INV-S-HDL-A-5).
    -- Period in `clk` cycles; tick fires every PERIOD_CYCLES-th cycle.
    -- Minimum value is 2 (a "tick every cycle" generator would have no
    -- pulse-width contract).
    PERIOD_CYCLES : positive;
    -- Mandatory: no default (INV-S-HDL-A-5).
    -- Initial counter value at reset; allows multi-instance phase stagger.
    -- MUST satisfy 0 <= INITIAL_PHASE < PERIOD_CYCLES (enforced by the
    -- elaboration-time assert in the architecture body).
    INITIAL_PHASE : natural
  );
  port (
    clk     : in  std_logic;
    rst     : in  std_logic;  -- synchronous active-high (INV-S-HDL-A-1)
    enable  : in  std_logic;
    tick    : out std_logic;
    -- Observability: current value of the modulo counter, range
    -- [0, PERIOD_CYCLES - 1].  Width = ceil(log2(PERIOD_CYCLES)).
    counter : out std_logic_vector(clog2_counter(PERIOD_CYCLES) - 1 downto 0)
  );
end entity sos_tick_gen;

architecture rtl of sos_tick_gen is

  constant CNT_W : positive := clog2_counter(PERIOD_CYCLES);

  -- Modulo counter; holds INITIAL_PHASE at reset.
  signal counter_q : unsigned(CNT_W - 1 downto 0);

  -- Combinational tick: high when the counter is at the terminal value AND
  -- the generator is enabled.  When `enable` deasserts mid-period the
  -- counter holds; if it happened to be parked at PERIOD_CYCLES - 1 when
  -- enable dropped, the enable mask still forces tick low (consumers never
  -- see a tick while disabled).
  signal at_terminal : std_logic;

begin

  ----------------------------------------------------------------------------
  -- Elaboration-time validation of INITIAL_PHASE.
  -- Per task scope: INITIAL_PHASE MUST satisfy 0 <= INITIAL_PHASE < PERIOD_CYCLES.
  -- (`natural` already guarantees the lower bound; we still enforce both
  -- ends for the failure message.)
  ----------------------------------------------------------------------------
  assert INITIAL_PHASE < PERIOD_CYCLES
    report "sos_tick_gen: SOS-08-A §6.8 requires 0 <= INITIAL_PHASE < "
           & "PERIOD_CYCLES; got INITIAL_PHASE="
           & integer'image(INITIAL_PHASE)
           & " PERIOD_CYCLES="
           & integer'image(PERIOD_CYCLES)
    severity failure;

  assert PERIOD_CYCLES >= 2
    report "sos_tick_gen: SOS-08-A §6.8 requires PERIOD_CYCLES >= 2; got "
           & integer'image(PERIOD_CYCLES)
    severity failure;

  ----------------------------------------------------------------------------
  -- Combinational tick: counter == PERIOD_CYCLES - 1 AND enable.
  ----------------------------------------------------------------------------

  at_terminal <= '1' when counter_q = to_unsigned(PERIOD_CYCLES - 1, CNT_W)
                 else '0';

  tick <= at_terminal and enable;

  counter <= std_logic_vector(counter_q);

  ----------------------------------------------------------------------------
  -- Sequential update of the modulo counter.
  --   * rst='1'             -> counter <= INITIAL_PHASE
  --   * rst='0', enable='1' -> counter <= (counter + 1) mod PERIOD_CYCLES
  --   * rst='0', enable='0' -> counter holds (no increment, no reset)
  ----------------------------------------------------------------------------

  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        counter_q <= to_unsigned(INITIAL_PHASE, CNT_W);
      elsif enable = '1' then
        if counter_q = to_unsigned(PERIOD_CYCLES - 1, CNT_W) then
          counter_q <= (others => '0');
        else
          counter_q <= counter_q + 1;
        end if;
      end if;
      -- enable = '0' : counter holds.
    end if;
  end process;

end architecture rtl;
