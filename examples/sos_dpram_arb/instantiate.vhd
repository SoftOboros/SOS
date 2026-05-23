-------------------------------------------------------------------------------
-- examples/sos_dpram_arb/instantiate.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (instantiation example)
--       docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 amendments —
--                                              READ_LATENCY + RESET_MEM
--                                              pattern inherited from
--                                              PCDN-A-fifo-* on sos_fifo_sync)
--       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
--       INV-S-HDL-A-5  mandatory parameters, no defaults
--       INV-S-HDL-3    cross-domain isolation (MODE=DUAL_CLOCK only)
--
-- Two example bindings are shown:
--   * u_dpram_single — MODE="SINGLE_CLOCK", DEPTH=64, WIDTH=32,
--                      READ_LATENCY=0, RESET_MEM=false.
--                      Single-clock dual-port RAM with combinational reads.
--   * u_dpram_dual   — MODE="DUAL_CLOCK",   DEPTH=64, WIDTH=32,
--                      READ_LATENCY=1, RESET_MEM=true.
--                      Dual-clock CDC variant with registered reads and
--                      mem zeroed on reset. MTBF.md sign-off REQUIRED at
--                      deployment time per SOS-08-A §12 (f).
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_dpram_arb_example is
    port (
        clk   : in std_logic;
        rst   : in std_logic;
        clk_a : in std_logic;
        rst_a : in std_logic;
        clk_b : in std_logic;
        rst_b : in std_logic;

        -- SINGLE_CLOCK instance ports.
        sc_port_a_addr  : in  std_logic_vector(5 downto 0);
        sc_port_a_wdata : in  std_logic_vector(31 downto 0);
        sc_port_a_we    : in  std_logic;
        sc_port_a_re    : in  std_logic;
        sc_port_a_rdata : out std_logic_vector(31 downto 0);
        sc_port_a_full  : out std_logic;
        sc_port_a_ready : out std_logic;

        sc_port_b_addr  : in  std_logic_vector(5 downto 0);
        sc_port_b_wdata : in  std_logic_vector(31 downto 0);
        sc_port_b_we    : in  std_logic;
        sc_port_b_re    : in  std_logic;
        sc_port_b_rdata : out std_logic_vector(31 downto 0);
        sc_port_b_full  : out std_logic;
        sc_port_b_ready : out std_logic;

        -- DUAL_CLOCK instance ports.
        dc_port_a_addr  : in  std_logic_vector(5 downto 0);
        dc_port_a_wdata : in  std_logic_vector(31 downto 0);
        dc_port_a_we    : in  std_logic;
        dc_port_a_re    : in  std_logic;
        dc_port_a_rdata : out std_logic_vector(31 downto 0);
        dc_port_a_full  : out std_logic;
        dc_port_a_ready : out std_logic;

        dc_port_b_addr  : in  std_logic_vector(5 downto 0);
        dc_port_b_wdata : in  std_logic_vector(31 downto 0);
        dc_port_b_we    : in  std_logic;
        dc_port_b_re    : in  std_logic;
        dc_port_b_rdata : out std_logic_vector(31 downto 0);
        dc_port_b_full  : out std_logic;
        dc_port_b_ready : out std_logic
    );
end entity sos_dpram_arb_example;

architecture rtl of sos_dpram_arb_example is

    component sos_dpram_arb is
        generic (
            DEPTH         : positive;
            WIDTH         : positive;
            MODE          : string;
            READ_LATENCY  : natural;
            RESET_MEM     : boolean
        );
        port (
            clk   : in std_logic;
            rst   : in std_logic;
            clk_a : in std_logic;
            rst_a : in std_logic;
            clk_b : in std_logic;
            rst_b : in std_logic;

            port_a_addr  : in  std_logic_vector;
            port_a_wdata : in  std_logic_vector;
            port_a_we    : in  std_logic;
            port_a_re    : in  std_logic;
            port_a_rdata : out std_logic_vector;
            port_a_full  : out std_logic;
            port_a_ready : out std_logic;

            port_b_addr  : in  std_logic_vector;
            port_b_wdata : in  std_logic_vector;
            port_b_we    : in  std_logic;
            port_b_re    : in  std_logic;
            port_b_rdata : out std_logic_vector;
            port_b_full  : out std_logic;
            port_b_ready : out std_logic
        );
    end component;

begin

    -- Example A: SINGLE_CLOCK — both ports on `clk`. MTBF treatment N/A.
    u_dpram_single : sos_dpram_arb
        generic map (
            -- INV-S-HDL-A-5: every generic supplied explicitly (no defaults).
            DEPTH        => 64,
            WIDTH        => 32,
            MODE         => "SINGLE_CLOCK",
            READ_LATENCY => 0,        -- FWFT
            RESET_MEM    => false     -- legacy: mem not reset
        )
        port map (
            clk   => clk,
            rst   => rst,
            clk_a => clk,             -- tied; unused in SINGLE_CLOCK
            rst_a => rst,
            clk_b => clk,
            rst_b => rst,

            port_a_addr  => sc_port_a_addr,
            port_a_wdata => sc_port_a_wdata,
            port_a_we    => sc_port_a_we,
            port_a_re    => sc_port_a_re,
            port_a_rdata => sc_port_a_rdata,
            port_a_full  => sc_port_a_full,
            port_a_ready => sc_port_a_ready,

            port_b_addr  => sc_port_b_addr,
            port_b_wdata => sc_port_b_wdata,
            port_b_we    => sc_port_b_we,
            port_b_re    => sc_port_b_re,
            port_b_rdata => sc_port_b_rdata,
            port_b_full  => sc_port_b_full,
            port_b_ready => sc_port_b_ready
        );

    -- Example B: DUAL_CLOCK — port A on clk_a/rst_a, port B on clk_b/rst_b.
    -- MTBF.md sign-off REQUIRED at deployment time (SOS-08-A §12 (f)).
    u_dpram_dual : sos_dpram_arb
        generic map (
            DEPTH        => 64,
            WIDTH        => 32,
            MODE         => "DUAL_CLOCK",
            READ_LATENCY => 1,        -- registered read on each port
            RESET_MEM    => true      -- strict: mem zeroed on reset
        )
        port map (
            clk   => clk_a,           -- tied to clk_a; unused in DUAL_CLOCK
            rst   => rst_a,
            clk_a => clk_a,
            rst_a => rst_a,
            clk_b => clk_b,
            rst_b => rst_b,

            port_a_addr  => dc_port_a_addr,
            port_a_wdata => dc_port_a_wdata,
            port_a_we    => dc_port_a_we,
            port_a_re    => dc_port_a_re,
            port_a_rdata => dc_port_a_rdata,
            port_a_full  => dc_port_a_full,
            port_a_ready => dc_port_a_ready,

            port_b_addr  => dc_port_b_addr,
            port_b_wdata => dc_port_b_wdata,
            port_b_we    => dc_port_b_we,
            port_b_re    => dc_port_b_re,
            port_b_rdata => dc_port_b_rdata,
            port_b_full  => dc_port_b_full,
            port_b_ready => dc_port_b_ready
        );

end architecture rtl;
