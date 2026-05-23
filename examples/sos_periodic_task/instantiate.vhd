-- =============================================================================
-- examples/sos_periodic_task/instantiate.vhd
--
-- Minimal VHDL-2008 instantiation example for `sos_periodic_task` with
-- DIVISOR = 10 and INITIAL_COUNTER = 0 (canonical "fire every 10 base_ticks
-- with no phase offset" configuration -- the simplest non-passthrough
-- periodic-task instance).
--
-- @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.4 (sos_periodic_task contract),
--   §5.4 (service-level SVA binding default), §12 (acceptance checklist;
--   instantiation-example gate).  Per the 2026-05-23 §15 ratification entry.
--   Per PCDN-SOS-08-B-004 resolution: this example does NOT instantiate the
--   global `sos_tick_gen` -- the assumption is that the enclosing system
--   instantiates one global tick generator whose `tick` output feeds the
--   `base_tick` input of every `sos_periodic_task` in the design.  This
--   example exposes `base_tick` at the wrapper boundary for the system
--   integrator to wire up.
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8 (`sos_tick_gen` -- referenced
--   only; not instantiated here) + §6.11 (`sos_rate_divider` -- composed
--   inside `sos_periodic_task`, not directly instantiated here).
--
-- Cited invariants:
--   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
--   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
--   INV-S-HDL-B-1, INV-S-HDL-B-2, INV-S-HDL-B-3       (SOS-08-B §7)
--
-- The instantiation is illustrative only; it shows the parameter override
-- (DIVISOR = 10 + INITIAL_COUNTER = 0, both mandatory at the L1 boundary
-- per INV-S-HDL-A-5 pass-through), the canonical port set, the tick-style
-- 1-cycle pulse i/o for both upstream (base_tick) and downstream
-- (task_enable), and the synchronous active-high reset wiring.
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;

entity sos_periodic_task_inst10 is
  port (
    clk             : in  std_logic;
    rst             : in  std_logic;

    -- Upstream tick from the system-level sos_tick_gen.
    base_tick       : in  std_logic;

    -- Task activation (1-cycle pulse, fires one cycle after each task_tick).
    task_enable     : out std_logic;

    -- Worker status (level held by worker logic while working).
    task_busy       : in  std_logic;

    -- Sticky overrun fault (level; cleared only by reset).
    overrun_fault   : out std_logic;

    -- Observability: inner rate-divider counter, ceil(log2(10)) = 4 bits.
    divider_counter : out std_logic_vector(3 downto 0)
  );
end entity sos_periodic_task_inst10;

architecture rtl of sos_periodic_task_inst10 is
begin

  u_periodic_task_10 : entity work.sos_periodic_task
    generic map (
      DIVISOR         => 10,
      INITIAL_COUNTER => 0
    )
    port map (
      clk             => clk,
      rst             => rst,
      base_tick       => base_tick,
      task_enable     => task_enable,
      task_busy       => task_busy,
      overrun_fault   => overrun_fault,
      divider_counter => divider_counter
    );

end architecture rtl;
