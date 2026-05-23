-- =============================================================================
-- examples/sos_tick_gen/instantiate.vhd
--
-- Minimal VHDL-2008 instantiation example for `sos_tick_gen` with
-- PERIOD_CYCLES = 100 and INITIAL_PHASE = 0.
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
--   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.8 contract,
--   §12 (g) instantiation-example gate.
--
-- Cited invariants:
--   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
--   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
--   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,      (SOS-08-A §7)
--   INV-S-HDL-A-5
--
-- The instantiation is illustrative only; it shows the mandatory generic
-- overrides (PERIOD_CYCLES = 100, INITIAL_PHASE = 0; no defaults per
-- INV-S-HDL-A-5), the canonical port set with the modulo `counter`
-- observability port (wave-1 amendment, see RTL header), and the
-- synchronous active-high reset wiring (INV-S-HDL-A-1).
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;

entity sos_tick_gen_inst100 is
  port (
    clk     : in  std_logic;
    rst     : in  std_logic;
    enable  : in  std_logic;
    tick    : out std_logic;
    -- ceil(log2(100)) = 7 bits for the modulo counter.
    counter : out std_logic_vector(6 downto 0)
  );
end entity sos_tick_gen_inst100;

architecture rtl of sos_tick_gen_inst100 is
begin

  -- Mandatory generic overrides; no defaults per INV-S-HDL-A-5.
  u_tg : entity work.sos_tick_gen
    generic map (
      PERIOD_CYCLES => 100,
      INITIAL_PHASE => 0
    )
    port map (
      clk     => clk,
      rst     => rst,
      enable  => enable,
      tick    => tick,
      counter => counter
    );

end architecture rtl;
