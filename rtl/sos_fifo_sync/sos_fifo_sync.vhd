-------------------------------------------------------------------------------
-- sos_fifo_sync.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (sos_fifo_sync contract)
--       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
--       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
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
--   INV-S-HDL-3  cross-domain isolation (N/A — single domain)
--   INV-S-HDL-4  cooperative-only at v1
--   INV-S-HDL-5  vector-to-chart traceability for HDL
--
-- Cross-primitive invariants (SOS-08-A §7, cited):
--   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
--   INV-S-HDL-A-2  handshake-port composition is associative
--   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
--   INV-S-HDL-A-4  one-hot internal FSM by default
--   INV-S-HDL-A-5  mandatory parameters have no defaults
--
-- Single-clock-domain FIFO. Portable VHDL-2008 RTL. Vendor shims live in
-- sibling vendor_<vendor>.sv files; this file is the -Dvendor=portable path.
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_fifo_sync is
    generic (
        -- INV-S-HDL-A-5: mandatory parameters, no defaults.
        DEPTH : positive;
        WIDTH : positive
    );
    port (
        -- Clock + sync active-high reset (INV-S-HDL-A-1 / PCDN-A-003).
        clk : in  std_logic;
        rst : in  std_logic;

        -- Slave AXI-Stream ingress (producer drives, FIFO accepts).
        s_axis_tdata  : in  std_logic_vector(WIDTH - 1 downto 0);
        s_axis_tvalid : in  std_logic;
        s_axis_tready : out std_logic;

        -- Master AXI-Stream egress (FIFO presents, consumer accepts).
        m_axis_tdata  : out std_logic_vector(WIDTH - 1 downto 0);
        m_axis_tvalid : out std_logic;
        m_axis_tready : in  std_logic;

        -- Observability outputs (bare names — not handshake-faced).
        full  : out std_logic;
        empty : out std_logic;
        -- count is wide enough to represent DEPTH (so 0..DEPTH inclusive).
        -- Width = max(1, ceil(log2(DEPTH+1))).
        count : out std_logic_vector
            (integer(ceil(log2(real(DEPTH + 1)))) - 1 downto 0)
    );
end entity sos_fifo_sync;

architecture rtl of sos_fifo_sync is

    -- Pointer + counter widths derived from generics.
    -- PTR_W = ceil(log2(DEPTH))   — index into storage [0 .. DEPTH-1].
    -- CNT_W = ceil(log2(DEPTH+1)) — fill count [0 .. DEPTH] inclusive.
    constant PTR_W : natural :=
        integer(ceil(log2(real(DEPTH))));
    constant CNT_W : natural :=
        integer(ceil(log2(real(DEPTH + 1))));

    -- Storage. Register-file shape; synthesis will infer LUT-RAM for small
    -- DEPTH and BRAM for large DEPTH on most targets (vendor-shim file
    -- selects optimised BRAM macros when -Dvendor=<x> is set).
    type mem_t is array (0 to DEPTH - 1) of std_logic_vector(WIDTH - 1 downto 0);
    signal mem : mem_t := (others => (others => '0'));

    signal wr_ptr   : unsigned(PTR_W - 1 downto 0) := (others => '0');
    signal rd_ptr   : unsigned(PTR_W - 1 downto 0) := (others => '0');
    signal fill     : unsigned(CNT_W - 1 downto 0) := (others => '0');

    signal full_q   : std_logic := '0';
    signal empty_q  : std_logic := '1';

    -- Internal handshake helpers.
    signal do_write : std_logic;
    signal do_read  : std_logic;

begin

    -- Combinational handshake decode.
    s_axis_tready <= not full_q;
    m_axis_tvalid <= not empty_q;

    do_write <= s_axis_tvalid and (not full_q);
    do_read  <= m_axis_tready and (not empty_q);

    -- Read data is the entry currently at rd_ptr (FWFT-style — m_axis_tdata
    -- presented combinationally so the consumer can latch it the same cycle
    -- it asserts tready).
    m_axis_tdata <= mem(to_integer(rd_ptr)) when empty_q = '0'
                    else (others => '0');

    -- Pointer + fill update.
    process (clk)
        variable next_fill : unsigned(CNT_W - 1 downto 0);
    begin
        if rising_edge(clk) then
            if rst = '1' then
                wr_ptr  <= (others => '0');
                rd_ptr  <= (others => '0');
                fill    <= (others => '0');
                full_q  <= '0';
                empty_q <= '1';
                -- mem contents intentionally not reset (saves area; INV-S-HDL-A-1
                -- mandates reset for state machine + observability, not storage).
            else
                next_fill := fill;

                if do_write = '1' then
                    mem(to_integer(wr_ptr)) <= s_axis_tdata;
                    if to_integer(wr_ptr) = DEPTH - 1 then
                        wr_ptr <= (others => '0');
                    else
                        wr_ptr <= wr_ptr + 1;
                    end if;
                    next_fill := next_fill + 1;
                end if;

                if do_read = '1' then
                    if to_integer(rd_ptr) = DEPTH - 1 then
                        rd_ptr <= (others => '0');
                    else
                        rd_ptr <= rd_ptr + 1;
                    end if;
                    next_fill := next_fill - 1;
                end if;

                fill <= next_fill;

                if next_fill = DEPTH then
                    full_q <= '1';
                else
                    full_q <= '0';
                end if;

                if next_fill = 0 then
                    empty_q <= '1';
                else
                    empty_q <= '0';
                end if;
            end if;
        end if;
    end process;

    full  <= full_q;
    empty <= empty_q;
    count <= std_logic_vector(fill);

end architecture rtl;
