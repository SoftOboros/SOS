-- =============================================================================
-- examples/sos_arbiter_priority/instantiate.vhd
--
-- Minimal VHDL-2008 instantiation example for `sos_arbiter_priority` with
-- N_REQS = 4 and PRIORITY_BITS = 3.  Two instances:
--   * `u_strict` -- AGING_ENABLE = 0; strict priority (low-priority
--                   requesters MAY starve under continuous high-priority
--                   contention).
--   * `u_aging`  -- AGING_ENABLE = 1, AGING_THRESHOLD = 128; starved
--                   requesters are promoted after 128 cycles.
--
-- Both use the canonical registered grant shape (GRANT_LATENCY_CYCLES = 1).
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
--   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.4 contract,
--   §12 (g) instantiation-example gate.
--   Per PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23,
--   extended to this primitive per task brief.
--
-- Cited invariants:
--   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
--   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
--   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,      (SOS-08-A §7)
--   INV-S-HDL-A-5
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;

entity sos_arbiter_priority_inst4 is
  port (
    clk                   : in  std_logic;
    rst                   : in  std_logic;
    req                   : in  std_logic_vector(3 downto 0);
    -- Flat 4 * 3 = 12-bit priority vector.
    priority_in           : in  std_logic_vector(11 downto 0);
    grant_strict          : out std_logic_vector(3 downto 0);
    last_winner_id_strict : out std_logic_vector(2 downto 0);  -- clog2(4+1) = 3
    grant_aging           : out std_logic_vector(3 downto 0);
    last_winner_id_aging  : out std_logic_vector(2 downto 0)
  );
end entity sos_arbiter_priority_inst4;

architecture rtl of sos_arbiter_priority_inst4 is
begin

  -- Strict priority: AGING_ENABLE = 0.  AGING_THRESHOLD must still be a valid
  -- positive integer (mandatory generic) but its value does not influence
  -- arbitration under strict mode.
  u_strict : entity work.sos_arbiter_priority
    generic map (
      N_REQS               => 4,
      PRIORITY_BITS        => 3,
      AGING_ENABLE         => 0,
      AGING_THRESHOLD      => 1,
      GRANT_LATENCY_CYCLES => 1
    )
    port map (
      clk            => clk,
      rst            => rst,
      req            => req,
      priority_in    => priority_in,
      grant          => grant_strict,
      last_winner_id => last_winner_id_strict
    );

  -- Aging-enabled: starved requesters promote after AGING_THRESHOLD cycles.
  u_aging : entity work.sos_arbiter_priority
    generic map (
      N_REQS               => 4,
      PRIORITY_BITS        => 3,
      AGING_ENABLE         => 1,
      AGING_THRESHOLD      => 128,
      GRANT_LATENCY_CYCLES => 1
    )
    port map (
      clk            => clk,
      rst            => rst,
      req            => req,
      priority_in    => priority_in,
      grant          => grant_aging,
      last_winner_id => last_winner_id_aging
    );

end architecture rtl;
