-------------------------------------------------------------------------------
-- examples/sos_fifo_async/instantiate.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (instantiation example)
--       docs/concepts/SOS-08-A-CONCEPTS.md §15  (2026-05-23 ratification +
--                                                impl wave-1 PCDN amendments)
--       INV-S-HDL-A-1  sync active-high reset per side + AXI-Stream naming
--       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
--       INV-S-HDL-A-5  mandatory parameters, no defaults (SYNC_STAGES is
--                      the documented exception, default 2)
--       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — READ_LATENCY generic
--       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — RESET_MEM generic
--
-- Minimal instantiation of sos_fifo_async. Two independent clock domains
-- (clk_a producer, clk_b consumer) with their own resets, AXI-Stream-naming
-- port map ratified by PCDN-SOS-08-A-002, and the SOS-08-A §6.1 canonical
-- shape (DEPTH=16, WIDTH=32, READ_LATENCY=0, RESET_MEM=false, SYNC_STAGES=2).
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_fifo_async_example is
    port (
        -- Producer (write) domain.
        clk_a    : in  std_logic;
        rst_a    : in  std_logic;
        in_data  : in  std_logic_vector(31 downto 0);
        in_valid : in  std_logic;
        in_ready : out std_logic;
        a_full   : out std_logic;

        -- Consumer (read) domain.
        clk_b     : in  std_logic;
        rst_b     : in  std_logic;
        out_data  : out std_logic_vector(31 downto 0);
        out_valid : out std_logic;
        out_ready : in  std_logic;
        b_empty   : out std_logic
    );
end entity sos_fifo_async_example;

architecture rtl of sos_fifo_async_example is

    -- Forward declaration of the primitive component. In production builds
    -- this is sourced from the SOS-08-A primitive library; here it is shown
    -- inline for the example.
    component sos_fifo_async is
        generic (
            DEPTH         : positive;
            WIDTH         : positive;
            READ_LATENCY  : natural;
            RESET_MEM     : boolean;
            SYNC_STAGES   : positive := 2
        );
        port (
            wr_clk        : in  std_logic;
            wr_rst        : in  std_logic;
            s_axis_tdata  : in  std_logic_vector;
            s_axis_tvalid : in  std_logic;
            s_axis_tready : out std_logic;
            wr_full       : out std_logic;
            wr_count      : out std_logic_vector;
            rd_clk        : in  std_logic;
            rd_rst        : in  std_logic;
            m_axis_tdata  : out std_logic_vector;
            m_axis_tvalid : out std_logic;
            m_axis_tready : in  std_logic;
            rd_empty      : out std_logic;
            rd_count      : out std_logic_vector
        );
    end component;

    -- ceil(log2(16+1)) = 5 bits per side count.
    signal count_a : std_logic_vector(4 downto 0);
    signal count_b : std_logic_vector(4 downto 0);

begin

    -- SOS-08-A §6.1 canonical instantiation. Every generic supplied
    -- explicitly per INV-S-HDL-A-5; SYNC_STAGES is the documented
    -- exception (default 2) but spelled out here for clarity at the
    -- build wrapper.
    u_evt_fifo : sos_fifo_async
        generic map (
            DEPTH        => 16,
            WIDTH        => 32,
            READ_LATENCY => 0,        -- FWFT
            RESET_MEM    => false,    -- legacy: mem not reset
            SYNC_STAGES  => 2         -- well-trodden CDC depth — see MTBF.md
        )
        port map (
            wr_clk        => clk_a,
            wr_rst        => rst_a,

            s_axis_tdata  => in_data,
            s_axis_tvalid => in_valid,
            s_axis_tready => in_ready,

            wr_full       => a_full,
            wr_count      => count_a,

            rd_clk        => clk_b,
            rd_rst        => rst_b,

            m_axis_tdata  => out_data,
            m_axis_tvalid => out_valid,
            m_axis_tready => out_ready,

            rd_empty      => b_empty,
            rd_count      => count_b
        );

end architecture rtl;
