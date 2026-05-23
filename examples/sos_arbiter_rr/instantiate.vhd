-- =============================================================================
-- examples/sos_arbiter_rr/instantiate.vhd
--
-- Minimal VHDL-2008 instantiation example for `sos_arbiter_rr` with
-- N_REQS = 4.
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
--   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.3 contract,
--   §12 (g) instantiation-example gate.
--
-- Cited invariants:
--   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
--   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
--   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,      (SOS-08-A §7)
--   INV-S-HDL-A-5
--
-- The instantiation is illustrative only; it shows the parameter override
-- (N_REQS = 4, no default per INV-S-HDL-A-5), the canonical port set, and
-- the synchronous active-high reset wiring (INV-S-HDL-A-1).
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;

entity sos_arbiter_rr_inst4 is
  port (
    clk            : in  std_logic;
    rst            : in  std_logic;
    req            : in  std_logic_vector(3 downto 0);
    grant          : out std_logic_vector(3 downto 0);
    last_winner_id : out std_logic_vector(2 downto 0)  -- clog2(4+1) = 3
  );
end entity sos_arbiter_rr_inst4;

architecture rtl of sos_arbiter_rr_inst4 is
begin

  u_rr : entity work.sos_arbiter_rr
    generic map (
      N_REQS => 4
    )
    port map (
      clk            => clk,
      rst            => rst,
      req            => req,
      grant          => grant,
      last_winner_id => last_winner_id
    );

end architecture rtl;
