-------------------------------------------------------------------------------
-- sos_message_channel_async.vhd
--
-- @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (CDC variant of message channel)
--       docs/concepts/SOS-08-B-CONCEPTS.md §15 — 2026-05-24 amendment: TWO
--             sibling variants (`sos_message_channel` single-clock baseline +
--             `sos_message_channel_async` CDC variant).
--       docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (composed sos_fifo_async L0)
--
-- Cross-phase invariants (cited, not redefined):
--   INV-SOS-A  chart-as-source
--   INV-SOS-B  vectors-as-deliverable at every layer
--   INV-SOS-C  bootstrap-vs-general framing
--   INV-SOS-D  verified-codegen position
--   INV-SOS-E  authority relationships
--   INV-SOS-F  iState authoring surface
--   INV-SOS-G  bounded-reachability discharge
--   INV-SOS-H  vector-to-chart traceability
--
-- Cross-sub-phase invariants (SOS-08 §7, cited):
--   INV-S-HDL-1  handshake-compatible ports
--   INV-S-HDL-2  static-allocation discipline
--   INV-S-HDL-3  cross-domain isolation (operational via inner sos_fifo_async)
--   INV-S-HDL-4  cooperative-only at v1
--   INV-S-HDL-5  vector-to-chart traceability for HDL
--
-- Byte-equivalent semantics to the SystemVerilog sibling in
-- sos_message_channel_async.sv.
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_message_channel_async is
    generic (
        -- INV-S-HDL-A-5: mandatory generics, no defaults (SYNC_STAGES
        -- excepted per sos_fifo_async precedent).
        EVENT_ID_WIDTH : positive;
        PAYLOAD_WIDTH  : positive;
        -- DEPTH MUST be a power of two AND >= 4 (sos_fifo_async constraint).
        DEPTH          : positive;
        READ_LATENCY   : natural;
        RESET_MEM      : boolean;
        SYNC_STAGES    : positive := 2
    );
    port (
        -- Write (producer) domain.
        wr_clk : in  std_logic;
        wr_rst : in  std_logic;

        s_axis_tdata     : in  std_logic_vector
            (EVENT_ID_WIDTH + PAYLOAD_WIDTH - 1 downto 0);
        s_axis_tevent_id : in  std_logic_vector(EVENT_ID_WIDTH - 1 downto 0);
        s_axis_tpayload  : in  std_logic_vector(PAYLOAD_WIDTH - 1 downto 0);
        s_axis_tvalid    : in  std_logic;
        s_axis_tready    : out std_logic;

        wr_full  : out std_logic;
        wr_count : out std_logic_vector
            (integer(ceil(log2(real(DEPTH + 1)))) - 1 downto 0);

        -- Read (consumer) domain.
        rd_clk : in  std_logic;
        rd_rst : in  std_logic;

        m_axis_tdata     : out std_logic_vector
            (EVENT_ID_WIDTH + PAYLOAD_WIDTH - 1 downto 0);
        m_axis_tevent_id : out std_logic_vector(EVENT_ID_WIDTH - 1 downto 0);
        m_axis_tpayload  : out std_logic_vector(PAYLOAD_WIDTH - 1 downto 0);
        m_axis_tvalid    : out std_logic;
        m_axis_tready    : in  std_logic;

        rd_empty : out std_logic;
        rd_count : out std_logic_vector
            (integer(ceil(log2(real(DEPTH + 1)))) - 1 downto 0)
    );
end entity sos_message_channel_async;

architecture rtl of sos_message_channel_async is

    constant TDATA_WIDTH : positive := EVENT_ID_WIDTH + PAYLOAD_WIDTH;

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

    signal fifo_in_tdata  : std_logic_vector(TDATA_WIDTH - 1 downto 0);
    signal fifo_out_tdata : std_logic_vector(TDATA_WIDTH - 1 downto 0);

begin

    fifo_in_tdata <=
        s_axis_tdata or (s_axis_tevent_id & s_axis_tpayload);

    m_axis_tdata     <= fifo_out_tdata;
    m_axis_tevent_id <= fifo_out_tdata(TDATA_WIDTH - 1 downto PAYLOAD_WIDTH);
    m_axis_tpayload  <= fifo_out_tdata(PAYLOAD_WIDTH - 1 downto 0);

    -- L0 composition (INV-S-HDL-B-2 — no L0 modification): one
    -- sos_fifo_async crosses wr_clk → rd_clk.
    u_fifo : sos_fifo_async
        generic map (
            DEPTH        => DEPTH,
            WIDTH        => TDATA_WIDTH,
            READ_LATENCY => READ_LATENCY,
            RESET_MEM    => RESET_MEM,
            SYNC_STAGES  => SYNC_STAGES
        )
        port map (
            wr_clk        => wr_clk,
            wr_rst        => wr_rst,
            s_axis_tdata  => fifo_in_tdata,
            s_axis_tvalid => s_axis_tvalid,
            s_axis_tready => s_axis_tready,
            wr_full       => wr_full,
            wr_count      => wr_count,
            rd_clk        => rd_clk,
            rd_rst        => rd_rst,
            m_axis_tdata  => fifo_out_tdata,
            m_axis_tvalid => m_axis_tvalid,
            m_axis_tready => m_axis_tready,
            rd_empty      => rd_empty,
            rd_count      => rd_count
        );

end architecture rtl;
