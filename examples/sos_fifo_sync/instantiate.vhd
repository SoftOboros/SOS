-------------------------------------------------------------------------------
-- examples/sos_fifo_sync/instantiate.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (instantiation example)
--       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
--       INV-S-HDL-A-5  mandatory parameters, no defaults
--
-- Minimal instantiation of sos_fifo_sync. Shows parameter passing and the
-- AXI-Stream-naming port map ratified by PCDN-SOS-08-A-002 (§15 2026-05-23).
-- The chart-emitted top-level (SOS-08-C) produces instantiations of this
-- shape automatically.
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_fifo_sync_example is
    port (
        clk : in  std_logic;
        rst : in  std_logic;

        in_data  : in  std_logic_vector(31 downto 0);
        in_valid : in  std_logic;
        in_ready : out std_logic;

        out_data  : out std_logic_vector(31 downto 0);
        out_valid : out std_logic;
        out_ready : in  std_logic
    );
end entity sos_fifo_sync_example;

architecture rtl of sos_fifo_sync_example is

    -- Forward declaration of the primitive component. In production builds
    -- this is sourced from the SOS-08-A primitive library; here it is shown
    -- inline for the example.
    component sos_fifo_sync is
        generic (
            DEPTH : positive;
            WIDTH : positive
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

    signal full_q  : std_logic;
    signal empty_q : std_logic;
    signal count_q : std_logic_vector(4 downto 0);  -- ceil(log2(16+1)) = 5

begin

    u_fifo : sos_fifo_sync
        generic map (
            -- INV-S-HDL-A-5: both parameters supplied explicitly.
            DEPTH => 16,
            WIDTH => 32
        )
        port map (
            clk           => clk,
            rst           => rst,
            s_axis_tdata  => in_data,
            s_axis_tvalid => in_valid,
            s_axis_tready => in_ready,
            m_axis_tdata  => out_data,
            m_axis_tvalid => out_valid,
            m_axis_tready => out_ready,
            full          => full_q,
            empty         => empty_q,
            count         => count_q
        );

end architecture rtl;
