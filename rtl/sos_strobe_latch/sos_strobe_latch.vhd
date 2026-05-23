--------------------------------------------------------------------------------
-- sos_strobe_latch.vhd - L0 primitive: pulse-to-level + ack + depth-1 shadow
--
-- @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- PCDN-A-strobe-pending-shadow resolved 2026-05-23 (§15): the primitive
-- carries a depth-1 `pending_strobe` shadow register so that a strobe arriving
-- same-cycle with ack-from-LATCHED is captured rather than dropped. The FSM
-- expands from a 2-state (IDLE / LATCHED) one-hot to a 3-state one-hot
-- (IDLE / LATCHED / LATCHED_PENDING), and a new observability port
-- `pending_q` exposes the shadow bit.
--
-- Invariants cited (not re-derived):
--   INV-SOS-A  chart-as-source                  (SOS-07 §6)
--   INV-SOS-B  vectors-as-deliverable           (SOS-07 §6)
--   INV-SOS-C  MCP as sole modification surface (SOS-07 §6)
--   INV-SOS-D  iState authoring, SCXML canon.   (SOS-07 §6)
--   INV-SOS-E  explicit AuthorityRelationship   (SOS-07 §6)
--   INV-SOS-F  bound composition                (SOS-07 §6)
--   INV-SOS-G  verified-codegen position        (SOS-07 §6)
--   INV-SOS-H  vector-to-chart traceability     (SOS-07 §6)
--
--   INV-S-HDL-1  handshake-compatible ports    (SOS-08 §7)
--   INV-S-HDL-2  static-allocation discipline  (SOS-08 §7)
--   INV-S-HDL-3  cross-domain isolation        (SOS-08 §7) — N/A: single domain.
--                Cross-domain strobe latching composes a sos_synchronizer on
--                the `strobe` input UPSTREAM of this primitive's boundary
--                (per §6.10 MTBF treatment).
--   INV-S-HDL-4  cooperative-only at v1         (SOS-08 §7)
--   INV-S-HDL-5  vector-to-chart traceability   (SOS-08 §7)
--
--   INV-S-HDL-A-1 uniform reset semantics       (SOS-08-A §7) — sync active-high
--   INV-S-HDL-A-2 handshake associativity       (SOS-08-A §7)
--   INV-S-HDL-A-3 vendor-shim byte-identical    (SOS-08-A §7) — portable-only
--   INV-S-HDL-A-4 one-hot internal FSM default  (SOS-08-A §7) — 3-state one-hot
--                 (IDLE / LATCHED / LATCHED_PENDING). The shadow register is
--                 encoded INTO the FSM state, not as a separate flip-flop, so
--                 the one-hot encoding remains the sole state representation.
--                 SUPERSEDES the prior "IDLE/LATCHED 2-state one-hot" reading.
--   INV-S-HDL-A-5 mandatory params no defaults  (SOS-08-A §7) — VACUOUSLY SATISFIED
--                 (no user-facing generics on this primitive; see note below)
--
-- Per PCDN-A-002 resolution (§15 2026-05-23): control-only primitives use bare
-- `strobe` / `ack` / `latched` (not AXI-Stream prefixed). This primitive sits
-- in the pulse-bearing class (§10 reconciliation), but its OUTPUT `latched` is
-- LEVEL-HELD rather than a single-cycle pulse — see "hybrid handshake" note.
--
-- HYBRID HANDSHAKE PATTERN (per PCDN-A-mutex-ack precedent, §15 2026-05-23 entry
-- "Impl wave-1 PCDN amendments"):
--   sos_strobe_latch combines the two §5.1 control-handshake variants:
--     * `strobe` (in)   — PULSE-BASED (1-cycle pulse) per §5.1(a). Producer
--                         emits a one-shot event; consumer is the latch.
--     * `latched` (out) — LEVEL-HELD per §5.1(b). The latched-state output
--                         is asserted for every cycle between strobe-capture
--                         and ack, mirroring sos_mutex `ack[i]`'s
--                         ownership-tracking shape.
--     * `ack` (in)      — PULSE-BASED (1-cycle pulse) per §5.1(a). Consumer
--                         acknowledges the latched event and clears the state.
--     * `pending_q`(out)— LEVEL-HELD observability of the depth-1 shadow.
--   The §6.10 contract literal "pulse-to-level + ack" describes exactly this
--   shape: strobe (pulse) -> latched (level) -> ack (pulse), with the shadow
--   bridging the same-cycle race from LATCHED.
--
-- INV-S-HDL-A-5 VACUOUSLY-SATISFIED NOTE:
--   The invariant requires "mandatory parameters have no defaults"; this
--   primitive has NO user-facing generics (no DEPTH, no WIDTH, no count).
--   The set of mandatory-parameters-without-defaults is empty, and the
--   universal-quantification "all mandatory parameters have no default" is
--   vacuously true. No parameter is added solely to give the invariant
--   something to apply to; the right answer is "the primitive is
--   parameterless, the invariant is satisfied by emptiness".
--
--   Should a future deployment need a `RESET_VALUE` generic (default IDLE)
--   to allow latched-on-reset behaviour, that would be a §15 amendment to
--   §6.10 (Standards Action per §5.2/§5.1 enum policy). Likewise, any
--   widening of the shadow depth beyond 1 is a §15 amendment.
--
-- Behaviour (per §6.10 + PCDN-A-strobe-pending-shadow):
--   * `strobe` asserted for one cycle while latched=0 captures the event:
--     next cycle, latched goes high and stays high (transition IDLE -> LATCHED).
--   * `ack` asserted for one cycle while latched=1 clears the latched state
--     (if no shadow is present) or consumes the shadow (if it is). Specifically:
--       - LATCHED + ack (no concurrent strobe) -> IDLE (cleared).
--       - LATCHED_PENDING + ack -> LATCHED (shadow consumed; the previously
--         shadowed strobe is now the live latched event).
--   * Re-strobing while LATCHED (no concurrent ack) captures into the shadow:
--     transition LATCHED -> LATCHED_PENDING. This DIVERGES from the prior
--     "re-strobe absorbed" behaviour: the shadow now preserves the second
--     event, eliminating the same-cycle drop hazard.
--   * Re-strobing while LATCHED_PENDING (no concurrent ack) is dropped (depth-1
--     shadow saturates): state remains LATCHED_PENDING.
--   * Same-cycle strobe + ack arbitration (refined ack-wins-from-LATCHED with
--     shadow):
--       - From IDLE: strobe sets latched=1 next cycle; ack is a no-op
--         (no latched state to clear; spec property `every_strobe_latched`
--         holds — strobe in IDLE always latches by next cycle).
--       - From LATCHED with strobe + ack same cycle: ack consumes the LATCHED
--         event AND the shadow captures the new strobe, so the FSM stays in
--         LATCHED next cycle (the shadowed strobe is now the live latched
--         event). The strobe survives — this is the load-bearing change vs the
--         prior implementation, which dropped it.
--       - From LATCHED_PENDING with strobe + ack same cycle: ack consumes the
--         live LATCHED event; the shadow promotes to live (state -> LATCHED);
--         the additional concurrent strobe is dropped (depth-1 saturated).
--   * Synchronous active-high `rst` returns FSM to IDLE (clearing both
--     `latched` and `pending_q`), and is the recovery path for any illegal
--     one-hot state.
--
-- Observability:
--   * `latched_state_q` is the registered version of `latched` (combinationally
--     == `latched`). Exposed so external monitors / SVA can observe the FSM
--     state without inferring it from the output port.
--   * `pending_q` is high while the FSM is in LATCHED_PENDING and low
--     otherwise. Exposed so external monitors / SVA can observe the shadow
--     bit directly without inferring it from same-cycle race tracing.
--   * The 3-bit one-hot internal `state` signal honours INV-S-HDL-A-4; the
--     external observability ports are boolean reductions of that state.
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_strobe_latch is
    -- No user-facing generics (INV-S-HDL-A-5 vacuously satisfied; see header).
    port (
        clk             : in  std_logic;
        rst             : in  std_logic;  -- sync active-high (INV-S-HDL-A-1)
        strobe          : in  std_logic;  -- 1-cycle pulse from producer (§5.1 pulse variant)
        ack             : in  std_logic;  -- 1-cycle pulse from consumer (§5.1 pulse variant)
        latched         : out std_logic;  -- level: high while latched, low while IDLE
        pending_q       : out std_logic;  -- level: high while shadow holds a pending strobe
        latched_state_q : out std_logic   -- observability: registered FSM latched state
    );
end entity sos_strobe_latch;

architecture rtl of sos_strobe_latch is

    --------------------------------------------------------------------------
    -- Internal FSM (one-hot per INV-S-HDL-A-4).
    --   state(0) = IDLE             -> latched=0, pending_q=0
    --   state(1) = LATCHED          -> latched=1, pending_q=0
    --   state(2) = LATCHED_PENDING  -> latched=1, pending_q=1
    --
    -- The shadow strobe is encoded as a distinct FSM state rather than a
    -- separate register so that the one-hot encoding is the SOLE state
    -- representation. This preserves INV-S-HDL-A-4 ("one-hot internal FSM
    -- default") under the new behaviour: there is exactly one register vector
    -- whose width is the number of reachable states.
    --
    -- The 4th codepoint (IDLE_WITH_PENDING) is unreachable — a strobe in IDLE
    -- always promotes to LATCHED (never to PENDING), so the shadow is only
    -- meaningful while LATCHED. The 3-bit one-hot suffices.
    --------------------------------------------------------------------------
    signal state : std_logic_vector(2 downto 0);
    constant ST_IDLE            : std_logic_vector(2 downto 0) := "001";
    constant ST_LATCHED         : std_logic_vector(2 downto 0) := "010";
    constant ST_LATCHED_PENDING : std_logic_vector(2 downto 0) := "100";

begin

    ----------------------------------------------------------------------------
    -- Sequential: one-hot IDLE / LATCHED / LATCHED_PENDING FSM
    --
    -- Same-cycle strobe + ack arbitration (refined ack-wins-from-LATCHED with
    -- depth-1 shadow): in the LATCHED branch, ack consumes the current latched
    -- event while a concurrent strobe captures into the shadow. The net effect
    -- is that next-state stays LATCHED (the shadowed strobe immediately
    -- promotes to live on the same edge). In the LATCHED_PENDING branch, ack
    -- consumes the live event and promotes the shadow; an additional strobe
    -- is dropped (shadow already saturated).
    ----------------------------------------------------------------------------
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                state <= ST_IDLE;
            else
                case state is

                    when ST_IDLE =>
                        -- IDLE: strobe captures into LATCHED; ack is a no-op.
                        -- Concurrent strobe+ack from IDLE: strobe wins (no
                        -- latched state to consume), promotes to LATCHED.
                        if strobe = '1' then
                            state <= ST_LATCHED;
                        end if;

                    when ST_LATCHED =>
                        -- LATCHED + ack (no strobe)             -> IDLE
                        -- LATCHED + strobe (no ack)             -> LATCHED_PENDING
                        -- LATCHED + ack + strobe                -> LATCHED
                        --   (ack consumes the live event; shadow captures the
                        --    strobe; shadow immediately promotes to live ->
                        --    next-state is LATCHED with no shadow held.)
                        -- LATCHED (neither)                     -> LATCHED
                        if ack = '1' and strobe = '1' then
                            state <= ST_LATCHED;
                        elsif ack = '1' then
                            state <= ST_IDLE;
                        elsif strobe = '1' then
                            state <= ST_LATCHED_PENDING;
                        end if;

                    when ST_LATCHED_PENDING =>
                        -- LATCHED_PENDING + ack (no strobe)     -> LATCHED
                        --   (consume live; shadow promotes to live.)
                        -- LATCHED_PENDING + ack + strobe        -> LATCHED
                        --   (consume live; shadow promotes; additional
                        --    strobe is dropped — depth-1 saturated.)
                        -- LATCHED_PENDING + strobe (no ack)     -> LATCHED_PENDING
                        --   (additional strobe dropped.)
                        -- LATCHED_PENDING (neither)             -> LATCHED_PENDING
                        if ack = '1' then
                            state <= ST_LATCHED;
                        end if;

                    when others =>
                        -- Illegal one-hot; recover to IDLE.
                        state <= ST_IDLE;

                end case;
            end if;
        end if;
    end process;

    ----------------------------------------------------------------------------
    -- Combinational outputs
    ----------------------------------------------------------------------------
    latched         <= '1' when (state = ST_LATCHED or state = ST_LATCHED_PENDING) else '0';
    latched_state_q <= '1' when (state = ST_LATCHED or state = ST_LATCHED_PENDING) else '0';
    pending_q       <= '1' when state = ST_LATCHED_PENDING                         else '0';

end architecture rtl;
