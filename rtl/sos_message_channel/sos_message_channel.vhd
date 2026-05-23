-------------------------------------------------------------------------------
-- sos_message_channel.vhd
--
-- @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (sos_message_channel contract)
--       docs/concepts/SOS-08-B-CONCEPTS.md §5  (frozen decisions)
--       docs/concepts/SOS-08-B-CONCEPTS.md §7  (cross-service invariants)
--       docs/concepts/SOS-08-B-CONCEPTS.md §15 — PCDN-SOS-08-B-005 resolved
--             2026-05-23: chart-derived metadata struct (one packed-struct
--             variant per ExternalEventName ID, encoded as a tagged union
--             {event_id, packed_payload_variant}). The L1 service itself is
--             structurally uniform; the per-event packed-struct variant
--             interpretation is SOS-08-C's responsibility — this L1 module
--             treats `payload` as opaque bits at the SOS-08-B layer.
--       docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (composed sos_fifo_sync L0)
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
--   INV-S-HDL-3  cross-domain isolation (N/A — single-clock variant; CDC
--                variant is a future §15 amendment)
--   INV-S-HDL-4  cooperative-only at v1
--   INV-S-HDL-5  vector-to-chart traceability for HDL
--
-- Cross-service invariants (SOS-08-B §7, cited):
--   INV-S-HDL-B-1  vocabulary mirror discipline (send / receive verbs)
--   INV-S-HDL-B-2  L0 non-modification (sos_fifo_sync accepted as-is)
--   INV-S-HDL-B-3  service-level SVA on every L1 instance
--   INV-S-HDL-B-4  vendor-IP pass-through (inherited from sos_fifo_sync)
--   INV-S-HDL-B-5  chart-vocabulary failure rendering
--
-- Cross-primitive invariants (SOS-08-A §7, cited):
--   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
--   INV-S-HDL-A-2  handshake-port composition is associative
--   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
--   INV-S-HDL-A-4  one-hot internal FSM by default
--   INV-S-HDL-A-5  mandatory parameters have no defaults
--
-- Byte-equivalent semantics to the SystemVerilog sibling in
-- sos_message_channel.sv. The L1 service composes a single sos_fifo_sync of
-- WIDTH = EVENT_ID_WIDTH + PAYLOAD_WIDTH carrying the packed
-- {event_id, payload} word. Per PCDN-005 the payload bits are opaque at this
-- layer; SOS-08-C emits the per-event packed-struct variant interpretation
-- as a chart-derived metadata struct.
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_message_channel is
    generic (
        -- INV-S-HDL-A-5: mandatory generics, no defaults.
        -- EVENT_ID_WIDTH — chart ExternalEventName index width (8..12 typ).
        EVENT_ID_WIDTH : positive;
        -- PAYLOAD_WIDTH — max chart-event payload width; opaque at this layer.
        PAYLOAD_WIDTH  : positive;
        -- Forwarded to the inner sos_fifo_sync (PCDN-A-fifo-* generics).
        DEPTH          : positive;
        READ_LATENCY   : natural;
        RESET_MEM      : boolean
    );
    port (
        -- Clock + sync active-high reset (INV-S-HDL-A-1).
        clk : in  std_logic;
        rst : in  std_logic;

        -- Slave AXI-Stream ingress (producer -> service). Two parallel
        -- representations; the chart-emitter (SOS-08-C) drives exactly one
        -- and ties the other off.
        s_axis_tdata     : in  std_logic_vector
            (EVENT_ID_WIDTH + PAYLOAD_WIDTH - 1 downto 0);
        s_axis_tevent_id : in  std_logic_vector(EVENT_ID_WIDTH - 1 downto 0);
        s_axis_tpayload  : in  std_logic_vector(PAYLOAD_WIDTH - 1 downto 0);
        s_axis_tvalid    : in  std_logic;
        s_axis_tready    : out std_logic;

        -- Master AXI-Stream egress (service -> consumer). The packed bus and
        -- the decomposed sideband are driven from the same FIFO output word.
        m_axis_tdata     : out std_logic_vector
            (EVENT_ID_WIDTH + PAYLOAD_WIDTH - 1 downto 0);
        m_axis_tevent_id : out std_logic_vector(EVENT_ID_WIDTH - 1 downto 0);
        m_axis_tpayload  : out std_logic_vector(PAYLOAD_WIDTH - 1 downto 0);
        m_axis_tvalid    : out std_logic;
        m_axis_tready    : in  std_logic;

        -- Observability outputs from the underlying sos_fifo_sync. count is
        -- wide enough to represent DEPTH inclusive.
        full  : out std_logic;
        empty : out std_logic;
        count : out std_logic_vector
            (integer(ceil(log2(real(DEPTH + 1)))) - 1 downto 0)
    );
end entity sos_message_channel;

architecture rtl of sos_message_channel is

    constant TDATA_WIDTH : positive := EVENT_ID_WIDTH + PAYLOAD_WIDTH;

    -- Component declaration for sos_fifo_sync (sourced from the SOS-08-A
    -- primitive library in production builds).
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

    -- Producer-side packed-input bus. The OR-combine accepts either the
    -- packed-bus producer representation OR the decomposed sideband; the
    -- chart-emitter (SOS-08-C) ties off whichever it does not drive.
    signal fifo_in_tdata  : std_logic_vector(TDATA_WIDTH - 1 downto 0);

    -- Consumer-side packed-output bus from the FIFO; fanned out to both
    -- representations on the master side.
    signal fifo_out_tdata : std_logic_vector(TDATA_WIDTH - 1 downto 0);

begin

    -- Producer-side pack. {event_id, payload} with event_id in the high
    -- bits, payload in the low bits — canonical {tag, value} for a
    -- tagged-union encoding.
    fifo_in_tdata <=
        s_axis_tdata or (s_axis_tevent_id & s_axis_tpayload);

    -- Consumer-side unpack. Drive both packed and decomposed
    -- representations from the same FIFO output word.
    m_axis_tdata     <= fifo_out_tdata;
    m_axis_tevent_id <= fifo_out_tdata(TDATA_WIDTH - 1 downto PAYLOAD_WIDTH);
    m_axis_tpayload  <= fifo_out_tdata(PAYLOAD_WIDTH - 1 downto 0);

    -- L0 composition (INV-S-HDL-B-2 — no L0 modification): one sos_fifo_sync
    -- of WIDTH = EVENT_ID_WIDTH + PAYLOAD_WIDTH carries the packed message.
    -- The L1 inherits the L0's five SVA properties transparently; the
    -- service-level SVA properties layered on top live in
    -- sos_message_channel_sva.sv.
    u_fifo : sos_fifo_sync
        generic map (
            DEPTH        => DEPTH,
            WIDTH        => TDATA_WIDTH,
            READ_LATENCY => READ_LATENCY,
            RESET_MEM    => RESET_MEM
        )
        port map (
            clk           => clk,
            rst           => rst,
            s_axis_tdata  => fifo_in_tdata,
            s_axis_tvalid => s_axis_tvalid,
            s_axis_tready => s_axis_tready,
            m_axis_tdata  => fifo_out_tdata,
            m_axis_tvalid => m_axis_tvalid,
            m_axis_tready => m_axis_tready,
            full          => full,
            empty         => empty,
            count         => count
        );

end architecture rtl;
