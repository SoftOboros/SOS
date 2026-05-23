-------------------------------------------------------------------------------
-- examples/sos_message_channel/instantiate.vhd
--
-- @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (instantiation example)
--       docs/concepts/SOS-08-B-CONCEPTS.md §15 — PCDN-SOS-08-B-005 resolved
--             2026-05-23: chart-derived metadata struct. This example shows
--             the structurally-uniform L1 instantiation; the per-event
--             packed-struct variant interpretation is SOS-08-C's
--             responsibility and not exercised here.
--       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
--       INV-S-HDL-A-5  mandatory parameters, no defaults
--       INV-S-HDL-B-2  L0 non-modification
--       INV-S-HDL-B-3  service-level SVA on every L1 instance
--
-- Minimal instantiation of sos_message_channel showing generic passing and
-- the AXI-Stream + sideband port map. The chart-emitted top-level
-- (SOS-08-C) produces instantiations of this shape automatically, plus the
-- per-event packed-struct encode / decode glue around it.
--
-- Generics:
--   EVENT_ID_WIDTH = 10  (chart ExternalEventName index width)
--   PAYLOAD_WIDTH  = 128 (max chart-event payload width)
--   DEPTH          = 16
--   READ_LATENCY   = 0   (FWFT)
--   RESET_MEM      = false (legacy — mem retained across reset)
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_message_channel_example is
    port (
        clk : in  std_logic;
        rst : in  std_logic;

        -- Producer-side ports. The chart-emitter (SOS-08-C) drives EITHER
        -- the packed bus OR the decomposed sideband; the L1 service
        -- OR-combines them.
        in_tdata     : in  std_logic_vector(137 downto 0);  -- 10 + 128 = 138
        in_tevent_id : in  std_logic_vector(9 downto 0);
        in_tpayload  : in  std_logic_vector(127 downto 0);
        in_tvalid    : in  std_logic;
        in_tready    : out std_logic;

        -- Consumer-side ports.
        out_tdata     : out std_logic_vector(137 downto 0);
        out_tevent_id : out std_logic_vector(9 downto 0);
        out_tpayload  : out std_logic_vector(127 downto 0);
        out_tvalid    : out std_logic;
        out_tready    : in  std_logic
    );
end entity sos_message_channel_example;

architecture rtl of sos_message_channel_example is

    -- Forward declaration of the L1 service. In production builds this
    -- comes from the SOS-08-B service library.
    component sos_message_channel is
        generic (
            EVENT_ID_WIDTH : positive;
            PAYLOAD_WIDTH  : positive;
            DEPTH          : positive;
            READ_LATENCY   : natural;
            RESET_MEM      : boolean
        );
        port (
            clk              : in  std_logic;
            rst              : in  std_logic;
            s_axis_tdata     : in  std_logic_vector;
            s_axis_tevent_id : in  std_logic_vector;
            s_axis_tpayload  : in  std_logic_vector;
            s_axis_tvalid    : in  std_logic;
            s_axis_tready    : out std_logic;
            m_axis_tdata     : out std_logic_vector;
            m_axis_tevent_id : out std_logic_vector;
            m_axis_tpayload  : out std_logic_vector;
            m_axis_tvalid    : out std_logic;
            m_axis_tready    : in  std_logic;
            full             : out std_logic;
            empty            : out std_logic;
            count            : out std_logic_vector
        );
    end component;

    signal full_w  : std_logic;
    signal empty_w : std_logic;
    signal count_w : std_logic_vector(4 downto 0);  -- ceil(log2(16+1)) = 5

begin

    u_msgch : sos_message_channel
        generic map (
            -- INV-S-HDL-A-5: every generic supplied explicitly (no defaults).
            EVENT_ID_WIDTH => 10,
            PAYLOAD_WIDTH  => 128,
            DEPTH          => 16,
            READ_LATENCY   => 0,       -- FWFT
            RESET_MEM      => false    -- legacy: mem not reset
        )
        port map (
            clk              => clk,
            rst              => rst,
            s_axis_tdata     => in_tdata,
            s_axis_tevent_id => in_tevent_id,
            s_axis_tpayload  => in_tpayload,
            s_axis_tvalid    => in_tvalid,
            s_axis_tready    => in_tready,
            m_axis_tdata     => out_tdata,
            m_axis_tevent_id => out_tevent_id,
            m_axis_tpayload  => out_tpayload,
            m_axis_tvalid    => out_tvalid,
            m_axis_tready    => out_tready,
            full             => full_w,
            empty            => empty_w,
            count            => count_w
        );

end architecture rtl;
