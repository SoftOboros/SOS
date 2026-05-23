-------------------------------------------------------------------------------
-- examples/sos_fifo_sync/instantiate.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (instantiation example)
--       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
--       INV-S-HDL-A-5  mandatory parameters, no defaults
--       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — READ_LATENCY generic
--       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — RESET_MEM generic
--
-- Minimal instantiation of sos_fifo_sync. Shows parameter passing and the
-- AXI-Stream-naming port map ratified by PCDN-SOS-08-A-002 (§15 2026-05-23).
-- The chart-emitted top-level (SOS-08-C) produces instantiations of this
-- shape automatically.
--
-- Two example bindings are shown:
--   * u_fifo_fwft   — DEPTH=16, WIDTH=32, READ_LATENCY=0, RESET_MEM=false.
--                     Legacy / smallest-area shape; m_axis_tdata is FWFT.
--   * u_fifo_reg    — DEPTH=16, WIDTH=32, READ_LATENCY=1, RESET_MEM=true.
--                     Registered read output; storage cleared on reset.
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_fifo_sync_example is
    port (
        clk : in  std_logic;
        rst : in  std_logic;

        -- FWFT / no-RESET_MEM channel.
        in_data_a  : in  std_logic_vector(31 downto 0);
        in_valid_a : in  std_logic;
        in_ready_a : out std_logic;

        out_data_a  : out std_logic_vector(31 downto 0);
        out_valid_a : out std_logic;
        out_ready_a : in  std_logic;

        -- Registered-read / RESET_MEM channel.
        in_data_b  : in  std_logic_vector(31 downto 0);
        in_valid_b : in  std_logic;
        in_ready_b : out std_logic;

        out_data_b  : out std_logic_vector(31 downto 0);
        out_valid_b : out std_logic;
        out_ready_b : in  std_logic
    );
end entity sos_fifo_sync_example;

architecture rtl of sos_fifo_sync_example is

    -- Forward declaration of the primitive component. In production builds
    -- this is sourced from the SOS-08-A primitive library; here it is shown
    -- inline for the example.
    component sos_fifo_sync is
        generic (
            DEPTH         : positive;
            WIDTH         : positive;
            READ_LATENCY  : natural;
            RESET_MEM     : boolean
        );
        port (
            clk           : in  std_logic;
            rst           : in  std_logic;
            s_axis_tdata  : in  std_logic_vector;
            s_axis_tvalid : in  std_logic;
            s_axis_tready : out std_logic;
            m_axis_tdata  : out std_logic_vector;
            m_axis_tvalid : out std_logic;
            m_axis_tready : in  std_logic;
            full          : out std_logic;
            empty         : out std_logic;
            count         : out std_logic_vector
        );
    end component;

    signal full_a  : std_logic;
    signal empty_a : std_logic;
    signal count_a : std_logic_vector(4 downto 0);  -- ceil(log2(16+1)) = 5

    signal full_b  : std_logic;
    signal empty_b : std_logic;
    signal count_b : std_logic_vector(4 downto 0);

begin

    -- Example A: legacy FWFT, mem retained across reset.
    u_fifo_fwft : sos_fifo_sync
        generic map (
            -- INV-S-HDL-A-5: every generic supplied explicitly (no defaults).
            DEPTH        => 16,
            WIDTH        => 32,
            READ_LATENCY => 0,        -- FWFT
            RESET_MEM    => false     -- legacy: mem not reset
        )
        port map (
            clk           => clk,
            rst           => rst,
            s_axis_tdata  => in_data_a,
            s_axis_tvalid => in_valid_a,
            s_axis_tready => in_ready_a,
            m_axis_tdata  => out_data_a,
            m_axis_tvalid => out_valid_a,
            m_axis_tready => out_ready_a,
            full          => full_a,
            empty         => empty_a,
            count         => count_a
        );

    -- Example B: registered-read output, mem cleared on reset.
    u_fifo_reg : sos_fifo_sync
        generic map (
            DEPTH        => 16,
            WIDTH        => 32,
            READ_LATENCY => 1,        -- one-cycle registered read latency
            RESET_MEM    => true      -- strict: mem zeroed on reset
        )
        port map (
            clk           => clk,
            rst           => rst,
            s_axis_tdata  => in_data_b,
            s_axis_tvalid => in_valid_b,
            s_axis_tready => in_ready_b,
            m_axis_tdata  => out_data_b,
            m_axis_tvalid => out_valid_b,
            m_axis_tready => out_ready_b,
            full          => full_b,
            empty         => empty_b,
            count         => count_b
        );

end architecture rtl;
