-- =============================================================================
-- sos_event_group.vhd  --  L1 service: FreeRTOS-style event-bit group
--                          (portable VHDL-2008)
--
-- @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.2 (sos_event_group)
--                + §5 frozen decisions, §7 cross-service invariants,
--                + §15 ratification entry (PCDN-SOS-08-B-002 -> N_BITS=32).
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 set), §7 (INV-S-HDL-1..5)
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
-- @l0          docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (sos_strobe_latch)
--                + §15 wave-2 amendments (PCDN-A-strobe-pending-shadow ->
--                  3-state FSM IDLE/LATCHED/LATCHED_PENDING + pending_q port).
--
-- Composition recipe (per §6.2):
--   N_BITS x sos_strobe_latch instantiated in a generate-for loop, one per
--   event-bit.  Each strobe_latch's `strobe` input is driven by
--   (set_req and set_mask(i)); its `ack` input is driven by
--   (clear_req and clear_mask(i)).  The `latched` output of strobe_latch(i)
--   becomes bits(i).  Wait-side combinational logic ANDs `bits` against
--   `wait_mask` and reduces via OR (any-of) or equality-to-mask (all-of).
--
-- Cited invariants (this service does not re-derive them):
--   INV-SOS-A..H        (SOS-07 §6)
--   INV-S-HDL-1..5      (SOS-08 §7)
--   INV-S-HDL-B-1..5    (SOS-08-B §7) -- specifically:
--     B-1 vocabulary mirror (set/wait/peek/clear -> FreeRTOS xEventGroup*)
--     B-2 L0 non-modification (sos_strobe_latch instantiated through
--         ratified ports only; no internal-state poking)
--     B-3 service-level SVA on every instance (bind file at
--         tb/sos_event_group/sos_event_group_bind.sv)
--     B-4 vendor-IP pass-through (vacuously satisfied; sos_strobe_latch is
--         portable-RTL-only per §6.2)
--     B-5 chart-vocabulary failure rendering (per INV-S-HDL-5)
--   INV-S-HDL-A-1..5    (SOS-08-A §7) inherited via the strobe_latch instances:
--     A-1 uniform sync active-high reset
--     A-2 handshake associativity
--     A-3 vendor-shim byte-identical (portable-only)
--     A-4 one-hot internal FSM (per-bit 3-state FSM lives in each strobe_latch)
--     A-5 mandatory parameters, no default -- L0 governance; N_BITS is a
--         SERVICE-LEVEL generic with default 32 per PCDN-SOS-08-B-002
--         resolution (§15 2026-05-23), NOT an L0 exception.
--
-- Design choices flagged in the agent report:
--   * Simultaneous set + clear on the same bit (same cycle): the per-bit
--     sos_strobe_latch's wave-2 shadow-promote semantic (PCDN-A-strobe-
--     pending-shadow) determines the outcome:
--       - bit was clear: same-cycle set+clear -> bit becomes set next cycle
--         (L0 IDLE+strobe+ack -> strobe wins).
--       - bit was set: same-cycle set+clear -> bit stays set next cycle
--         (L0 LATCHED+strobe+ack -> ack consumes live, shadow captures the
--          new strobe, shadow immediately promotes to live).
--     The visible service-level rule preserves both edges (no event loss)
--     without re-deriving any FreeRTOS-specific outcome.  Flagged for §15
--     ratification at the SOS-08-B walkthrough.
--
--   * pending_q exposure at the service level: NOT EXPOSED.  Rationale:
--     `event.peek` requests the LIVE bit-vector; the per-bit pending shadow
--     is an L0 implementation detail.  Exposing pending at the L1 interface
--     would force chart consumers to reason about the L0 wave-2 FSM, which
--     violates the L1-hides-L0 discipline (§5.2, INV-S-HDL-B-2).  Internal
--     observability is preserved via the per-instance L0 SVA bind.
--     Flagged for §15 ratification at the SOS-08-B walkthrough.
-- =============================================================================

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity sos_event_group is
    generic (
        -- Per PCDN-SOS-08-B-002 resolution (§15 2026-05-23): N_BITS
        -- parameterised with default 32 (chart datamodel i32 width).
        -- Service-level generic; per-region override via chart annotation.
        N_BITS : positive := 32
    );
    port (
        clk        : in  std_logic;
        rst        : in  std_logic;                                  -- sync active-high
        -- set side: 1-cycle pulse + per-bit mask
        set_req    : in  std_logic;
        set_mask   : in  std_logic_vector(N_BITS-1 downto 0);
        -- clear side: 1-cycle pulse + per-bit mask
        clear_req  : in  std_logic;
        clear_mask : in  std_logic_vector(N_BITS-1 downto 0);
        -- wait side: combinational predicate
        wait_mask  : in  std_logic_vector(N_BITS-1 downto 0);
        wait_mode  : in  std_logic;                                  -- 0 = any-of, 1 = all-of
        wait_match : out std_logic;
        -- observability: current bit-vector
        bits       : out std_logic_vector(N_BITS-1 downto 0)
    );
end entity sos_event_group;

architecture rtl of sos_event_group is

    -- Per-bit signals plumbed through the generate loop.
    signal bit_strobe  : std_logic_vector(N_BITS-1 downto 0);
    signal bit_ack     : std_logic_vector(N_BITS-1 downto 0);
    signal bit_latched : std_logic_vector(N_BITS-1 downto 0);
    signal bit_pending : std_logic_vector(N_BITS-1 downto 0);  -- L0 internal observability
    signal bit_state_q : std_logic_vector(N_BITS-1 downto 0);  -- L0 internal observability

    -- Wait-side combinational signals.
    signal masked_bits : std_logic_vector(N_BITS-1 downto 0);
    signal match_any   : std_logic;
    signal match_all   : std_logic;

    -- Helpers for OR-/AND-reductions across N_BITS.
    function reduce_or(v : std_logic_vector) return std_logic is
        variable r : std_logic := '0';
    begin
        for i in v'range loop
            r := r or v(i);
        end loop;
        return r;
    end function;

begin

    ---------------------------------------------------------------------------
    -- Generate one sos_strobe_latch per event bit (per §6.2 L0 composition).
    ---------------------------------------------------------------------------
    g_bits : for i in 0 to N_BITS-1 generate
        bit_strobe(i) <= set_req   and set_mask(i);
        bit_ack(i)    <= clear_req and clear_mask(i);

        u_bit : entity work.sos_strobe_latch
            port map (
                clk             => clk,
                rst             => rst,
                strobe          => bit_strobe(i),
                ack             => bit_ack(i),
                latched         => bit_latched(i),
                pending_q       => bit_pending(i),
                latched_state_q => bit_state_q(i)
            );
    end generate g_bits;

    ---------------------------------------------------------------------------
    -- bits is the live latched vector (per §6.2 "current_bits == latched").
    -- The pending and state_q signals stay internal; see header rationale on
    -- the L1-hides-L0 discipline.
    ---------------------------------------------------------------------------
    bits <= bit_latched;

    ---------------------------------------------------------------------------
    -- Wait-side combinational predicate (§6.2 SVA-EVG-2 / SVA-EVG-3).
    ---------------------------------------------------------------------------
    masked_bits <= bit_latched and wait_mask;

    match_any <= reduce_or(masked_bits);
    match_all <= '1' when masked_bits = wait_mask else '0';

    wait_match <= match_all when wait_mode = '1' else match_any;

    ---------------------------------------------------------------------------
    -- bit_pending and bit_state_q are intentionally not consumed by the L1
    -- surface; they exist for the per-instance L0 SVA bind to observe.  No
    -- VHDL warning suppression is needed (unused-signal warnings are
    -- tool-specific; the synthesiser will optimise them away).
    ---------------------------------------------------------------------------

end architecture rtl;
