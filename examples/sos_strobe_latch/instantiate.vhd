--------------------------------------------------------------------------------
-- instantiate.vhd - sos_strobe_latch instantiation example (parameterless)
--
-- @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10 ("Instantiation example")
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
--
-- PCDN-A-strobe-pending-shadow resolved 2026-05-23 (§15): instantiation
-- surface now includes the `pending_q` observability port, exposing the
-- depth-1 strobe shadow register added by the PCDN resolution. The
-- instantiation has no `generic map` clause (the primitive is still
-- parameterless; INV-S-HDL-A-5 vacuously satisfied) and adds one extra
-- port wire compared to the pre-shadow shape.
--
-- Single-instance instantiation. sos_strobe_latch has NO user-facing
-- generics -- see the primitive's header for the INV-S-HDL-A-5
-- vacuously-satisfied rationale. The example documents the
-- lack-of-parameterization explicitly: there is no `generic map` clause
-- because the entity declares no generics.
--
-- If a future deployment wires a `RESET_VALUE` generic (default IDLE) to
-- allow latched-on-reset behaviour, this example becomes the natural
-- migration test bed -- but adding such a generic is a §15 amendment to
-- SOS-08-A §6.10 (Standards Action). Likewise, widening the shadow depth
-- beyond 1 is a §15 amendment.
--
-- Hybrid handshake (per §15 2026-05-23 amendments):
--   producer drives `strobe` as a 1-cycle pulse;
--   consumer observes `latched` as a level-held signal;
--   consumer observes `pending_q` as a level-held shadow indicator;
--   consumer drives `ack` as a 1-cycle pulse to clear.
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_strobe_latch_example is
    port (
        clk             : in  std_logic;
        rst             : in  std_logic;
        strobe          : in  std_logic;
        ack             : in  std_logic;
        latched         : out std_logic;
        pending_q       : out std_logic;
        latched_state_q : out std_logic
    );
end entity sos_strobe_latch_example;

architecture rtl of sos_strobe_latch_example is
begin

    -- No generic map clause -- the primitive has no user-facing generics
    -- (INV-S-HDL-A-5 vacuously satisfied).
    u_strobe_latch : entity work.sos_strobe_latch
        port map (
            clk             => clk,
            rst             => rst,
            strobe          => strobe,
            ack             => ack,
            latched         => latched,
            pending_q       => pending_q,
            latched_state_q => latched_state_q
        );

end architecture rtl;
