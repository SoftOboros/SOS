-- =============================================================================
-- sos_periodic_task.vhd  --  L1 service: per-task periodic activation with
--                            overrun detection (portable VHDL-2008).
--
-- @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.4 (sos_periodic_task contract)
--   + §5.1 (FreeRTOS / POSIX vocabulary mirror), §5.2 (L1-composes-L0-without-
--   modification), §5.3 (vendor-IP override pass-through; N/A here -- the
--   inner sos_rate_divider is portable-only), §5.4 (service-level SVA binding
--   default).  Per the 2026-05-23 §15 ratification entry (PCDN walkthrough).
--
--   Per PCDN-SOS-08-B-004 resolution (RESOLVED, recommendation accepted):
--   ONE global `sos_tick_gen` per system; per-task `sos_rate_divider` for
--   sub-rates.  This service represents ONE periodic task.  The global
--   `sos_tick_gen` is shared at the system level and is NOT instantiated
--   here; this service consumes the global `base_tick` and divides it
--   per-task via a single internal `sos_rate_divider`.
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8 (`sos_tick_gen` -- by-reference
--   only; not instantiated here) + §6.11 (`sos_rate_divider` -- instantiated
--   internally).  Per the 2026-05-23 wave-2 §15 amendments:
--     * §6.8 PCDN-A-tick-prose-collapse: the global tick generator's
--       observability is a modulo counter, not a monotonic 32-bit tick count
--       (the prompt's draft `tick_count[31:0]` port is WITHDRAWN at the L1
--       boundary; this service mirrors the L0 collapse by exposing
--       `divider_counter` -- the inner `sos_rate_divider.counter` -- as the
--       only observability port, width `ceil(log2(DIVISOR))`).
--     * §6.11 PCDN-A-rate-prose-collapse: compile-time `DIVISOR` +
--       `INITIAL_COUNTER` generics; no runtime ratio.  These generics are
--       passed through to the inner `sos_rate_divider`.
--
-- Cited invariants (this service does not redefine them):
--   INV-SOS-A   chart-as-source                       (SOS-07 §6)
--   INV-SOS-B   vectors-as-deliverable                (SOS-07 §6)
--   INV-SOS-E   explicit AuthorityRelationship        (SOS-07 §6)
--   INV-SOS-G   verified-codegen position             (SOS-07 §6)
--   INV-SOS-H   vector-to-chart traceability         (SOS-07 §6)
--   INV-S-HDL-1 handshake-compatible ports            (SOS-08 §7; pulse form)
--   INV-S-HDL-2 static-allocation discipline          (SOS-08 §7)
--   INV-S-HDL-3 cross-domain isolation                (SOS-08 §7; N/A single-clk)
--   INV-S-HDL-4 cooperative-only at v1                (SOS-08 §7)
--   INV-S-HDL-5 vector-to-chart traceability (HDL)    (SOS-08 §7)
--   INV-S-HDL-B-1 vocabulary mirror discipline        (SOS-08-B §7)
--   INV-S-HDL-B-2 L0 non-modification                 (SOS-08-B §7)
--   INV-S-HDL-B-3 service-level SVA on every L1       (SOS-08-B §7)
--   INV-S-HDL-B-4 vendor-IP pass-through              (SOS-08-B §7; N/A)
--   INV-S-HDL-B-5 chart-vocabulary failure rendering  (SOS-08-B §7)
--
-- Behavioural contract (§6.4):
--   The service consumes a 1-cycle `base_tick` pulse from a system-wide
--   `sos_tick_gen` (NOT instantiated here -- shared global).  The inner
--   `sos_rate_divider` divides the base tick by `DIVISOR`, with an optional
--   phase offset `INITIAL_COUNTER`, producing an internal `task_tick`
--   1-cycle pulse.
--
--   On each `task_tick`, the service emits a `task_enable` 1-cycle pulse one
--   cycle later (SVA-PT-2: "each `task_tick` pulse produces exactly one
--   `task_enable` pulse on the next cycle").  The task's worker logic is
--   expected to assert `task_busy` (level) within bounded latency after
--   `task_enable` and hold it until it completes its activation.
--
--   Overrun detection: if `task_busy` is still asserted on the cycle of a
--   subsequent `task_tick`, the worker missed its deadline.  `overrun_fault`
--   latches high one cycle later and remains high until reset (sticky,
--   SVA-PT-3).  The service default per SVA-PT-4 is: `task_enable` continues
--   to pulse under `overrun_fault == 1` (the chart-side FSM observes both
--   signals and decides recovery).
--
-- FSM encoding (one-hot per INV-S-HDL-A-4 / SOS-08-A §5.2 by extension to
-- L1; the three-state FSM is small enough that one-hot adds 1 FF over a
-- binary encoding while making the SVA easier to author):
--   ST_IDLE     -- post-reset; have not yet seen the first task_tick.
--                  Transitions to ST_RUNNING on a task_tick (which also
--                  schedules a task_enable pulse for the next cycle).
--   ST_RUNNING  -- the steady-state.  On each subsequent task_tick, sample
--                  task_busy: if low, stay in ST_RUNNING and schedule the
--                  next task_enable pulse; if high, transition to
--                  ST_OVERRUN and latch overrun_fault.
--   ST_OVERRUN  -- sticky fault state.  task_enable continues to pulse on
--                  each task_tick (SVA-PT-4 default).  Cleared only by
--                  synchronous reset.
--
-- Resource cost:
--   ceil(log2(DIVISOR)) FFs (in the inner rate divider counter)
--   + 3 FFs (one-hot FSM state)
--   + 1 FF (registered task_enable pulse)
--   + 1 FF (sticky overrun_fault).
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

library work;
  use work.sos_rate_divider_pkg.all;

entity sos_periodic_task is
  generic (
    -- Mandatory: no default (INV-S-HDL-B-2 via INV-S-HDL-A-5 pass-through to
    -- the inner sos_rate_divider).  DIVISOR >= 1 required.
    DIVISOR         : positive;
    -- Mandatory: no default.  Must satisfy 0 <= INITIAL_COUNTER < DIVISOR.
    -- Allows N parallel periodic tasks to be staggered in phase off a shared
    -- global base_tick.
    INITIAL_COUNTER : natural
  );
  port (
    clk             : in  std_logic;
    rst             : in  std_logic;  -- synchronous active-high

    -- Upstream: 1-cycle pulse from the system-level sos_tick_gen.  Per
    -- PCDN-SOS-08-B-004, the tick generator is shared across the system and
    -- lives outside this service.
    base_tick       : in  std_logic;

    -- Task activation (output, 1-cycle pulse).  Registered: pulses one
    -- cycle after the qualifying internal task_tick.  SVA-PT-2.
    task_enable     : out std_logic;

    -- Worker status (input, level held by worker logic while busy).
    task_busy       : in  std_logic;

    -- Sticky overrun fault (output, level).  Latches high one cycle after
    -- a task_tick is observed with task_busy = '1'; cleared only by reset.
    -- SVA-PT-3.
    overrun_fault   : out std_logic;

    -- Observability: inner rate-divider counter value, width
    -- ceil(log2(DIVISOR)) (minimum 1 bit).  Per §6.8 PCDN-A-tick-prose-
    -- collapse, the canonical observability is the divider's modulo
    -- counter -- not a 32-bit monotonic tick count.
    divider_counter : out std_logic_vector(clog2_min1(DIVISOR) - 1 downto 0)
  );
end entity sos_periodic_task;

architecture rtl of sos_periodic_task is

  -- Internal task tick: 1-cycle pulse from the rate divider.
  signal task_tick      : std_logic;

  -- Registered task_enable: pulses one cycle after task_tick.
  signal task_enable_q  : std_logic;

  -- One-hot FSM state.  Bit assignments:
  --   state_q(0) = ST_IDLE
  --   state_q(1) = ST_RUNNING
  --   state_q(2) = ST_OVERRUN
  signal state_q        : std_logic_vector(2 downto 0);

  -- Sticky overrun fault register.
  signal overrun_q      : std_logic;

  -- One-hot state aliases for readability.
  constant ST_IDLE      : std_logic_vector(2 downto 0) := "001";
  constant ST_RUNNING   : std_logic_vector(2 downto 0) := "010";
  constant ST_OVERRUN   : std_logic_vector(2 downto 0) := "100";

begin

  -- =========================================================================
  -- Inner sos_rate_divider: divides base_tick by DIVISOR, producing task_tick.
  -- DIVISOR + INITIAL_COUNTER are passed through verbatim (INV-S-HDL-B-4
  -- vendor-IP pass-through, even though no vendor selection applies here).
  -- The exposed divider_counter port is the inner counter (per §6.8
  -- prose-collapse: modulo counter is the canonical observability).
  -- =========================================================================
  u_div : entity work.sos_rate_divider
    generic map (
      DIVISOR         => DIVISOR,
      INITIAL_COUNTER => INITIAL_COUNTER
    )
    port map (
      clk      => clk,
      rst      => rst,
      tick_in  => base_tick,
      tick_out => task_tick,
      counter  => divider_counter
    );

  -- =========================================================================
  -- FSM + overrun latch + registered task_enable pulse.
  --
  -- All four registers (state, task_enable_q, overrun_q) update synchronously
  -- on rising edge of clk under sync active-high reset (INV-S-HDL-A-1 by
  -- extension to L1).
  -- =========================================================================
  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        state_q       <= ST_IDLE;
        task_enable_q <= '0';
        overrun_q     <= '0';
      else
        -- Default: task_enable returns to '0' next cycle (pulse).
        task_enable_q <= '0';

        -- FSM next-state logic.
        case state_q is
          when ST_IDLE =>
            -- First task_tick after reset: schedule a task_enable pulse for
            -- next cycle and enter ST_RUNNING.  task_busy is ignored here
            -- (the worker has not yet been enabled, so a high task_busy at
            -- the very first tick is a precondition violation -- caught by
            -- SVA-PT-3 as an overrun anyway, but in steady-state never
            -- happens).
            if task_tick = '1' then
              state_q       <= ST_RUNNING;
              task_enable_q <= '1';
            end if;

          when ST_RUNNING =>
            -- Steady state: on each subsequent task_tick, decide whether
            -- this is an on-time tick (task_busy = '0') or an overrun
            -- (task_busy = '1' -> worker missed its deadline).
            if task_tick = '1' then
              task_enable_q <= '1';  -- SVA-PT-4 default: pulses continue.
              if task_busy = '1' then
                state_q   <= ST_OVERRUN;
                overrun_q <= '1';
              end if;
            end if;

          when ST_OVERRUN =>
            -- Sticky fault state.  task_enable continues to pulse on each
            -- task_tick.  overrun_q stays asserted; only synchronous reset
            -- clears it (handled by the `rst = '1'` arm above).
            if task_tick = '1' then
              task_enable_q <= '1';
            end if;

          when others =>
            -- Defensive: any non-one-hot encoding (impossible under reset +
            -- the legal transitions above) reverts to ST_IDLE on the next
            -- cycle.  This guards against single-event upsets at the FF
            -- level without compromising the SVA-PT-3 sticky-overrun
            -- property (the next overrun observation will re-latch
            -- overrun_q -- which is itself a separate register and not part
            -- of state_q).
            state_q <= ST_IDLE;
        end case;
      end if;
    end if;
  end process;

  -- Output drivers (registered).
  task_enable   <= task_enable_q;
  overrun_fault <= overrun_q;

end architecture rtl;
