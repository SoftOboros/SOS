-- =============================================================================
-- examples/sos_synchronizer/instantiate.vhd
--
-- Minimal VHDL-2008 instantiation example for `sos_synchronizer`,
-- THE canonical CDC primitive in the SOS-08-A L0 catalogue.  Two instances:
--   * `u_sync_1bit` -- WIDTH = 1, STAGES = 2 (canonical 2-FF synchronizer)
--   * `u_sync_data` -- WIDTH = 32, STAGES = 3 (multi-bit Gray-coded bus,
--                                               extra stage for higher MTBF)
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
--   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.9 contract,
--   §12 (g) instantiation-example gate.
--
-- Cited invariants:
--   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
--   INV-S-HDL-1, INV-S-HDL-3, INV-S-HDL-5             (SOS-08 §7)
--   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-5       (SOS-08-A §7)
--
-- The instantiation is illustrative only; it shows the generic override
-- (STAGES and WIDTH both mandatory per INV-S-HDL-A-5, no default), the
-- canonical port set, and the synchronous active-high `rst_dst` wiring
-- (INV-S-HDL-A-1).
--
-- Note: the `d_src` input on each instance is, by construction, from a
-- clock domain different to `clk_dst`.  In this example wrapper both
-- instances share the same `clk_dst` (the destination domain); the
-- source-domain timing is implicit (no `clk_src` port on the primitive --
-- see §6.9 + the primitive's header docstring).
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;

entity sos_synchronizer_example is
  port (
    clk_dst  : in  std_logic;
    rst_dst  : in  std_logic;

    -- Single-bit cross (e.g. async strobe, reset deassert edge, etc.).
    flag_src : in  std_logic;
    flag_dst : out std_logic;

    -- 32-bit Gray-coded bus (e.g. cross-domain FIFO pointer).  Multi-bit
    -- synchronizer use requires Gray coding per §6.9; the primitive
    -- does not enforce it.
    bus_src  : in  std_logic_vector(31 downto 0);
    bus_dst  : out std_logic_vector(31 downto 0)
  );
end entity sos_synchronizer_example;

architecture rtl of sos_synchronizer_example is

  -- Adapters between the example's scalar `flag_*` ports and the
  -- primitive's `std_logic_vector` port surface (WIDTH = 1).
  signal flag_src_v : std_logic_vector(0 downto 0);
  signal flag_dst_v : std_logic_vector(0 downto 0);

begin

  flag_src_v(0) <= flag_src;
  flag_dst     <= flag_dst_v(0);

  -- Canonical 2-FF synchronizer for a single-bit async signal.  This is
  -- the most common use of the primitive -- every `sos_*` primitive that
  -- composes a CDC reset or strobe path instantiates one of these.
  u_sync_1bit : entity work.sos_synchronizer
    generic map (
      STAGES => 2,
      WIDTH  => 1
    )
    port map (
      clk_dst => clk_dst,
      rst_dst => rst_dst,
      d_src   => flag_src_v,
      d_dst   => flag_dst_v
    );

  -- 3-stage synchronizer for a Gray-coded 32-bit bus.  An extra stage
  -- raises the MTBF by orders of magnitude (see MTBF.md) at the cost of
  -- one additional destination-domain clock of latency.
  u_sync_data : entity work.sos_synchronizer
    generic map (
      STAGES => 3,
      WIDTH  => 32
    )
    port map (
      clk_dst => clk_dst,
      rst_dst => rst_dst,
      d_src   => bus_src,
      d_dst   => bus_dst
    );

end architecture rtl;
