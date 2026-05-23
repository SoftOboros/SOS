-- =============================================================================
-- examples/sos_mailbox/instantiate.vhd
--
-- Minimal VHDL-2008 instantiation example for sos_mailbox.
--
-- Parameters per the task brief:
--   NUM_PRIO              = 8
--   DEPTH                 = 16
--   WIDTH                 = 32
--   READ_LATENCY          = 0  (FWFT)
--   RESET_MEM             = false  (legacy: mem retained across reset)
--   AGING_ENABLE          = 1  (starved low lanes promote)
--   AGING_THRESHOLD       = 128
--   GRANT_LATENCY_CYCLES  = 1  (canonical registered grant)
--
-- @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.1 (instantiation surface)
--       docs/concepts/SOS-08-B-CONCEPTS.md §15  (2026-05-23 ratification:
--                                               PCDN-SOS-08-B-001 NUM_PRIO
--                                               default 8; PCDN-SOS-08-B-006
--                                               level-sensitive irq_non_empty)
--       docs/concepts/SOS-08-A-CONCEPTS.md §6.2, §6.4 (composed L0 contracts)
--
-- Cited invariants:
--   INV-SOS-A, INV-SOS-E                                  (SOS-07 §6)
--   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
--   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,          (SOS-08-A §7)
--   INV-S-HDL-A-5
--   INV-S-HDL-B-1, INV-S-HDL-B-2, INV-S-HDL-B-3,          (SOS-08-B §7)
--   INV-S-HDL-B-4, INV-S-HDL-B-5
--
-- ceil(log2(8)) = 3 so s_axis_tprio / m_axis_tprio are 3-bit sidebands.
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;

entity sos_mailbox_example is
  port (
    clk        : in  std_logic;
    rst        : in  std_logic;

    -- Producer surface.
    in_msg     : in  std_logic_vector(31 downto 0);
    in_prio    : in  std_logic_vector(2 downto 0);
    in_valid   : in  std_logic;
    in_ready   : out std_logic;

    -- Consumer surface.
    out_msg    : out std_logic_vector(31 downto 0);
    out_prio   : out std_logic_vector(2 downto 0);
    out_valid  : out std_logic;
    out_ready  : in  std_logic;

    -- Level-sensitive IRQ.
    irq        : out std_logic
  );
end entity sos_mailbox_example;

architecture rtl of sos_mailbox_example is
begin

  u_mailbox : entity work.sos_mailbox
    generic map (
      -- Per PCDN-SOS-08-B-001: default NUM_PRIO = 8 (matches chart MAX_PRIO).
      NUM_PRIO             => 8,
      -- INV-S-HDL-A-5: every other generic supplied explicitly.
      DEPTH                => 16,
      WIDTH                => 32,
      READ_LATENCY         => 0,
      RESET_MEM            => false,
      AGING_ENABLE         => 1,
      AGING_THRESHOLD      => 128,
      GRANT_LATENCY_CYCLES => 1
    )
    port map (
      clk            => clk,
      rst            => rst,

      s_axis_tdata   => in_msg,
      s_axis_tprio   => in_prio,
      s_axis_tvalid  => in_valid,
      s_axis_tready  => in_ready,

      m_axis_tdata   => out_msg,
      m_axis_tprio   => out_prio,
      m_axis_tvalid  => out_valid,
      m_axis_tready  => out_ready,

      irq_non_empty  => irq
    );

end architecture rtl;
