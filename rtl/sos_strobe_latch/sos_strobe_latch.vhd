--------------------------------------------------------------------------------
-- sos_strobe_latch.vhd - L0 primitive: pulse-to-level + ack
--
-- @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
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
--   INV-S-HDL-A-4 one-hot internal FSM default  (SOS-08-A §7) — IDLE/LATCHED one-hot
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
--   The §6.10 contract literal "pulse-to-level + ack" describes exactly this
--   shape: strobe (pulse) -> latched (level) -> ack (pulse).
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
--   §6.10 (Standards Action per §5.2/§5.1 enum policy). Flagged as an
--   open question in the implementer's report.
--
-- Behaviour (per §6.10):
--   * `strobe` asserted for one cycle while latched=0 captures the event:
--     next cycle, latched goes high and stays high.
--   * `ack` asserted for one cycle while latched=1 clears the latched state:
--     next cycle, latched goes low.
--   * Re-strobing while latched=1 is absorbed (no double-latch, no counter).
--     INV-S-HDL-A-4 one-hot guarantees the FSM cannot leave LATCHED via the
--     strobe path; only ack transitions out of LATCHED.
--   * Same-cycle strobe + ack arbitration (canonical "ack-wins-on-same-cycle
--     from LATCHED" semantic, per task brief):
--       - From IDLE: strobe sets latched=1 next cycle; ack is a no-op
--         (no latched state to clear; spec property `every_strobe_latched`
--         holds — strobe in IDLE always latches by next cycle).
--       - From LATCHED: ack clears to IDLE next cycle; the same-cycle strobe
--         is dropped (no re-latch). Justification: §6.10 property
--         `every_ack_clears` is the load-bearing safety claim (ack must
--         clear when observed in LATCHED); pairing it with a pending-strobe
--         shadow would require either (a) a second register growing the
--         primitive past its "1-bit" identity, or (b) prioritising the
--         re-latch which would violate `every_ack_clears`'s ##1 !level
--         guarantee. The canonical choice is ack-wins; producers SHOULD
--         re-strobe on the next cycle if the event was meant to survive.
--   * Synchronous active-high `rst` returns FSM to IDLE, clears `latched`,
--     and is the recovery path for any illegal one-hot state.
--
-- Observability:
--   * `latched_state_q` is the registered version of `latched` (combinationally
--     == `latched`). Exposed so external monitors / SVA can observe the FSM
--     state without inferring it from the output port. 1-bit because there
--     are only two states (IDLE=0, LATCHED=1); a 2-bit one-hot encoding is
--     used INTERNALLY (signal `state`) to honour INV-S-HDL-A-4, but the
--     external observability port is the boolean reduction.
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
        latched_state_q : out std_logic   -- observability: registered FSM state
    );
end entity sos_strobe_latch;

architecture rtl of sos_strobe_latch is

    --------------------------------------------------------------------------
    -- Internal FSM (one-hot per INV-S-HDL-A-4).
    --   state(0) = IDLE     -> latched=0
    --   state(1) = LATCHED  -> latched=1
    --
    -- Even though there are only two states, the explicit one-hot encoding
    -- mirrors sos_mutex's IDLE/HELD shape and keeps the synthesis-tool
    -- one-hot optimisation discipline uniform across the L0 library
    -- (INV-S-HDL-A-4 default + SOS-08 PCDN-002 ratified one-hot at v1).
    --------------------------------------------------------------------------
    signal state       : std_logic_vector(1 downto 0);
    constant ST_IDLE    : std_logic_vector(1 downto 0) := "01";
    constant ST_LATCHED : std_logic_vector(1 downto 0) := "10";

begin

    ----------------------------------------------------------------------------
    -- Sequential: one-hot IDLE <-> LATCHED FSM
    --
    -- Same-cycle strobe + ack arbitration (canonical "ack-wins-on-same-cycle
    -- from LATCHED" semantic): the LATCHED-branch checks `ack` first and
    -- transitions to IDLE if asserted, regardless of `strobe`. The strobe is
    -- dropped in that case. From IDLE, `strobe` drives the capture and `ack`
    -- is a no-op (there is no latched state to clear).
    ----------------------------------------------------------------------------
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                state <= ST_IDLE;
            else
                case state is

                    when ST_IDLE =>
                        -- IDLE: strobe captures; ack is a no-op.
                        if strobe = '1' then
                            state <= ST_LATCHED;
                        end if;
                        -- If strobe AND ack arrive same-cycle from IDLE:
                        -- strobe wins (latches the event); ack is no-op
                        -- (no latched state present to clear).

                    when ST_LATCHED =>
                        -- LATCHED: ack clears regardless of strobe
                        -- (canonical "ack-wins-on-same-cycle" — task brief).
                        -- Re-strobe absorbed (no double-latch).
                        if ack = '1' then
                            state <= ST_IDLE;
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
    latched         <= '1' when state = ST_LATCHED else '0';
    latched_state_q <= '1' when state = ST_LATCHED else '0';

end architecture rtl;
