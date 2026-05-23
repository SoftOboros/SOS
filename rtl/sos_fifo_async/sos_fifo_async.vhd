-------------------------------------------------------------------------------
-- sos_fifo_async.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (sos_fifo_async contract)
--       docs/concepts/SOS-08-A-CONCEPTS.md §15  (2026-05-23 ratification +
--                                                impl wave-1 PCDN amendments)
--       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
--       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
--       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — adds READ_LATENCY
--                                  generic (0 = FWFT, 1 = registered read),
--                                  inherited pattern from sos_fifo_sync.
--       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — adds RESET_MEM
--                                  generic (false = legacy, true = clear mem),
--                                  inherited pattern from sos_fifo_sync.
--       PCDN-A-bind-form          resolved 2026-05-23 — module-type bind.
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
--   INV-S-HDL-3  cross-domain isolation — applies here; synchronizer flop
--                chains on the gray-coded pointer crossings are excluded
--                from formal proof. MTBF sign-off lives at MTBF.md.
--   INV-S-HDL-4  cooperative-only at v1
--   INV-S-HDL-5  vector-to-chart traceability for HDL
--
-- Cross-primitive invariants (SOS-08-A §7, cited):
--   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
--                  (per-side: wr_rst is sync-to-wr_clk, rd_rst sync-to-rd_clk)
--   INV-S-HDL-A-2  handshake-port composition is associative
--   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
--   INV-S-HDL-A-4  one-hot internal FSM by default (no internal FSM here)
--   INV-S-HDL-A-5  mandatory parameters have no defaults (SYNC_STAGES is the
--                  documented exception — default 2, the well-trodden value)
--
-- Cross-clock-domain FIFO. Portable VHDL-2008 RTL. Two clock domains
-- (wr_clk producer side, rd_clk consumer side). Gray-coded pointers cross
-- between the domains via SYNC_STAGES-deep flop synchronizers per the
-- canonical CDC FIFO architecture; storage MAY be inferred LUT-RAM or BRAM
-- depending on DEPTH. Vendor shims live in sibling vendor_<vendor>.sv files;
-- this file is the -Dvendor=portable path.
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_fifo_async is
    generic (
        -- INV-S-HDL-A-5: mandatory parameters, no defaults.
        --   DEPTH MUST be a power of two (gray-coded wraparound exploited).
        DEPTH         : positive;
        WIDTH         : positive;
        -- PCDN-A-fifo-READ_LATENCY (2026-05-23): 0 = FWFT (combinational
        -- m_axis_tdata = mem[rd_ptr] while !empty); 1 = registered read
        -- (data appears one cycle after the tready+tvalid handshake).
        READ_LATENCY  : natural;
        -- PCDN-A-fifo-RESET_MEM (2026-05-23): false = mem retained across
        -- reset (legacy, smaller reset fanout); true = mem cleared to
        -- all-zero on wr_rst (the writer owns the storage), stricter
        -- semantics, larger reset fanout. The reader-side rd_rst does NOT
        -- clear mem regardless of RESET_MEM (mem is a wr_clk-clocked array).
        RESET_MEM     : boolean;
        -- SYNC_STAGES is the canonical CDC parameter. Default 2 is the
        -- well-trodden value for moderate clock ratios; larger values
        -- (3, 4) raise MTBF for high-frequency / tight-budget designs.
        -- Documented in MTBF.md; build wrappers MUST re-sign-off MTBF.md
        -- when overriding SYNC_STAGES > 2 or targeting a different process.
        SYNC_STAGES   : positive := 2
    );
    port (
        -- Write (producer) clock domain (INV-S-HDL-A-1: sync active-high reset).
        wr_clk : in  std_logic;
        wr_rst : in  std_logic;

        -- Slave AXI-Stream ingress (producer drives, FIFO accepts).
        s_axis_tdata  : in  std_logic_vector(WIDTH - 1 downto 0);
        s_axis_tvalid : in  std_logic;
        s_axis_tready : out std_logic;

        -- Write-side observability (bare names — not handshake-faced).
        wr_full  : out std_logic;
        -- wr_count is the producer-domain view of fill. Wide enough to
        -- represent 0..DEPTH inclusive: ceil(log2(DEPTH+1)) bits.
        wr_count : out std_logic_vector
            (integer(ceil(log2(real(DEPTH + 1)))) - 1 downto 0);

        -- Read (consumer) clock domain (INV-S-HDL-A-1: sync active-high reset).
        rd_clk : in  std_logic;
        rd_rst : in  std_logic;

        -- Master AXI-Stream egress (FIFO presents, consumer accepts).
        m_axis_tdata  : out std_logic_vector(WIDTH - 1 downto 0);
        m_axis_tvalid : out std_logic;
        m_axis_tready : in  std_logic;

        -- Read-side observability.
        rd_empty : out std_logic;
        rd_count : out std_logic_vector
            (integer(ceil(log2(real(DEPTH + 1)))) - 1 downto 0)
    );
end entity sos_fifo_async;

architecture rtl of sos_fifo_async is

    -- Pointer + counter widths. PTR_W is wide enough to index DEPTH; we
    -- carry one extra MSB on each pointer (PTR_W+1 total bits) so that
    -- full vs empty can be distinguished after gray-coding (the canonical
    -- CDC FIFO trick: when all PTR_W+1 bits of the synced pointers are
    -- equal -> empty; when the top two bits differ and the rest match
    -- -> full).
    constant PTR_W : natural :=
        integer(ceil(log2(real(DEPTH))));
    constant CNT_W : natural :=
        integer(ceil(log2(real(DEPTH + 1))));

    -- Storage. Register-file shape; synthesis infers LUT-RAM for small
    -- DEPTH and BRAM for large DEPTH. The mem array is clocked on wr_clk
    -- (the writer owns the storage; the reader does a combinational
    -- mem(rd_ptr) read or latches via rdata_q).
    type mem_t is array (0 to DEPTH - 1) of std_logic_vector(WIDTH - 1 downto 0);
    signal mem : mem_t := (others => (others => '0'));

    -- Binary pointers — PTR_W+1 bits each so the extra MSB distinguishes
    -- full from empty after gray-coding (canonical CDC FIFO pattern).
    signal wr_ptr_bin       : unsigned(PTR_W downto 0) := (others => '0');
    signal rd_ptr_bin       : unsigned(PTR_W downto 0) := (others => '0');

    -- Gray-coded versions of the pointers, registered in their own
    -- domain. The gray-coded form is what crosses the clock-domain
    -- boundary (single-bit transitions per increment → safe for
    -- multi-FF synchronization).
    signal wr_ptr_gray      : std_logic_vector(PTR_W downto 0) := (others => '0');
    signal rd_ptr_gray      : std_logic_vector(PTR_W downto 0) := (others => '0');

    -- Synchronizer flop chains (SYNC_STAGES deep) for cross-domain pointer
    -- delivery. Synthesis attributes are emitted by the vendor-IP shim
    -- path; the portable RTL relies on the back-end's CDC analysis.
    type sync_chain_t is array (1 to SYNC_STAGES) of
        std_logic_vector(PTR_W downto 0);
    signal wr_ptr_gray_synced : sync_chain_t := (others => (others => '0'));
    signal rd_ptr_gray_synced : sync_chain_t := (others => (others => '0'));

    -- Far-side pointers, recovered (still gray) in the local domain after
    -- the SYNC_STAGES-deep crossing. wr_ptr_gray_at_rd lives in rd_clk
    -- domain; rd_ptr_gray_at_wr lives in wr_clk domain.
    signal wr_ptr_gray_at_rd : std_logic_vector(PTR_W downto 0);
    signal rd_ptr_gray_at_wr : std_logic_vector(PTR_W downto 0);

    -- Status flops, owned by their local domain.
    signal wr_full_q   : std_logic := '0';
    signal rd_empty_q  : std_logic := '1';

    -- Per-domain fill counts, computed locally from the local pointer +
    -- the synchronized far-side pointer. Conservative: wr_count may show
    -- "fuller" than ground truth (slow rd_ptr crossing); rd_count may show
    -- "emptier" than ground truth (slow wr_ptr crossing).
    signal wr_count_q  : unsigned(CNT_W - 1 downto 0) := (others => '0');
    signal rd_count_q  : unsigned(CNT_W - 1 downto 0) := (others => '0');

    -- Registered-read holding register (READ_LATENCY=1 only).
    signal rdata_q : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');

    -- Combinational helpers.
    signal do_write : std_logic;
    signal do_read  : std_logic;

    -- Recovered binary copies of the synchronized far-side pointers (used
    -- to compute local count_q). Gray-to-binary conversion is a
    -- combinational XOR-prefix reduction.
    function gray_to_bin (g : std_logic_vector) return unsigned is
        variable b : unsigned(g'range);
    begin
        b(b'high) := unsigned(g(g'high downto g'high));
        for i in g'high - 1 downto g'low loop
            b(i) := b(i + 1) xor g(i);
        end loop;
        return b;
    end function;

    function bin_to_gray (b : unsigned) return std_logic_vector is
        variable g : std_logic_vector(b'range);
    begin
        for i in b'range loop
            if i = b'high then
                g(i) := b(i);
            else
                g(i) := b(i) xor b(i + 1);
            end if;
        end loop;
        return g;
    end function;

    -- Write-side: comparison of own gray pointer's next value against the
    -- synchronized read pointer for the full-detection trick (top two bits
    -- differ + rest match -> full).
    function would_be_full (
        w_next : std_logic_vector;
        r_sync : std_logic_vector
    ) return std_logic is
    begin
        if (w_next(w_next'high)     /= r_sync(r_sync'high)) and
           (w_next(w_next'high - 1) /= r_sync(r_sync'high - 1)) and
           (w_next(w_next'high - 2 downto w_next'low) =
            r_sync(r_sync'high - 2 downto r_sync'low)) then
            return '1';
        else
            return '0';
        end if;
    end function;

begin

    ------------------------------------------------------------------
    -- Synchronizer chains. INV-S-HDL-3 excludes these from formal
    -- proof; MTBF sign-off lives at rtl/sos_fifo_async/MTBF.md.
    ------------------------------------------------------------------
    -- wr_ptr_gray → rd_clk domain.
    sync_wr_to_rd : process (rd_clk)
    begin
        if rising_edge(rd_clk) then
            if rd_rst = '1' then
                for i in 1 to SYNC_STAGES loop
                    wr_ptr_gray_synced(i) <= (others => '0');
                end loop;
            else
                wr_ptr_gray_synced(1) <= wr_ptr_gray;
                for i in 2 to SYNC_STAGES loop
                    wr_ptr_gray_synced(i) <= wr_ptr_gray_synced(i - 1);
                end loop;
            end if;
        end if;
    end process;
    wr_ptr_gray_at_rd <= wr_ptr_gray_synced(SYNC_STAGES);

    -- rd_ptr_gray → wr_clk domain.
    sync_rd_to_wr : process (wr_clk)
    begin
        if rising_edge(wr_clk) then
            if wr_rst = '1' then
                for i in 1 to SYNC_STAGES loop
                    rd_ptr_gray_synced(i) <= (others => '0');
                end loop;
            else
                rd_ptr_gray_synced(1) <= rd_ptr_gray;
                for i in 2 to SYNC_STAGES loop
                    rd_ptr_gray_synced(i) <= rd_ptr_gray_synced(i - 1);
                end loop;
            end if;
        end if;
    end process;
    rd_ptr_gray_at_wr <= rd_ptr_gray_synced(SYNC_STAGES);

    ------------------------------------------------------------------
    -- Handshake decode.
    ------------------------------------------------------------------
    s_axis_tready <= not wr_full_q;
    do_write      <= s_axis_tvalid and (not wr_full_q);
    do_read       <= m_axis_tready and (not rd_empty_q);

    ------------------------------------------------------------------
    -- Read path. Selected by READ_LATENCY generic (mirrors sos_fifo_sync).
    --   READ_LATENCY = 0: FWFT — m_axis_tdata is mem(rd_ptr) combinational.
    --   READ_LATENCY = 1: Registered — m_axis_tdata is rdata_q (latched on
    --                     handshake; popped value visible cycle AFTER).
    ------------------------------------------------------------------
    g_read_fwft : if READ_LATENCY = 0 generate
        m_axis_tvalid <= not rd_empty_q;
        m_axis_tdata  <= mem(to_integer(rd_ptr_bin(PTR_W - 1 downto 0)))
                            when rd_empty_q = '0'
                            else (others => '0');
    end generate;

    g_read_reg : if READ_LATENCY /= 0 generate
        m_axis_tvalid <= not rd_empty_q;
        m_axis_tdata  <= rdata_q;
    end generate;

    ------------------------------------------------------------------
    -- Write-side state. Owned by wr_clk; reads wr_ptr_gray_at_rd
    -- (the synchronized far-side rd pointer) for full detection.
    ------------------------------------------------------------------
    process (wr_clk)
        variable next_wr_bin  : unsigned(PTR_W downto 0);
        variable next_wr_gray : std_logic_vector(PTR_W downto 0);
        variable rd_bin_sync  : unsigned(PTR_W downto 0);
        variable fill_w       : unsigned(PTR_W + 1 downto 0);
    begin
        if rising_edge(wr_clk) then
            if wr_rst = '1' then
                wr_ptr_bin  <= (others => '0');
                wr_ptr_gray <= (others => '0');
                wr_full_q   <= '0';
                wr_count_q  <= (others => '0');
                if RESET_MEM then
                    for i in 0 to DEPTH - 1 loop
                        mem(i) <= (others => '0');
                    end loop;
                end if;
            else
                next_wr_bin := wr_ptr_bin;
                if do_write = '1' then
                    mem(to_integer(wr_ptr_bin(PTR_W - 1 downto 0)))
                        <= s_axis_tdata;
                    next_wr_bin := wr_ptr_bin + 1;
                end if;
                next_wr_gray := bin_to_gray(next_wr_bin);

                wr_ptr_bin  <= next_wr_bin;
                wr_ptr_gray <= next_wr_gray;

                -- Full detection: next gray write-pointer matches the
                -- synced read-pointer with the top two bits inverted.
                wr_full_q <= would_be_full(next_wr_gray, rd_ptr_gray_at_wr);

                -- Conservative producer-side count. Recover the binary
                -- form of the synced (older) rd pointer to compute fill.
                rd_bin_sync := gray_to_bin(rd_ptr_gray_at_wr);
                -- Modulo-2*DEPTH subtraction; PTR_W+1 carries it cleanly.
                fill_w := resize(next_wr_bin, PTR_W + 2)
                          - resize(rd_bin_sync, PTR_W + 2);
                wr_count_q <= resize(fill_w, CNT_W);
            end if;
        end if;
    end process;

    ------------------------------------------------------------------
    -- Read-side state. Owned by rd_clk; reads rd_ptr_gray_at_wr's
    -- mirror wr_ptr_gray_at_rd for empty detection.
    ------------------------------------------------------------------
    process (rd_clk)
        variable next_rd_bin  : unsigned(PTR_W downto 0);
        variable next_rd_gray : std_logic_vector(PTR_W downto 0);
        variable wr_bin_sync  : unsigned(PTR_W downto 0);
        variable fill_r       : unsigned(PTR_W + 1 downto 0);
    begin
        if rising_edge(rd_clk) then
            if rd_rst = '1' then
                rd_ptr_bin  <= (others => '0');
                rd_ptr_gray <= (others => '0');
                rd_empty_q  <= '1';
                rd_count_q  <= (others => '0');
                rdata_q     <= (others => '0');
            else
                next_rd_bin := rd_ptr_bin;
                if do_read = '1' then
                    next_rd_bin := rd_ptr_bin + 1;
                    if READ_LATENCY /= 0 then
                        rdata_q <= mem(to_integer(
                            rd_ptr_bin(PTR_W - 1 downto 0)));
                    end if;
                end if;
                next_rd_gray := bin_to_gray(next_rd_bin);

                rd_ptr_bin  <= next_rd_bin;
                rd_ptr_gray <= next_rd_gray;

                -- Empty detection: next gray read-pointer matches the
                -- synced write-pointer in ALL bits.
                if next_rd_gray = wr_ptr_gray_at_rd then
                    rd_empty_q <= '1';
                else
                    rd_empty_q <= '0';
                end if;

                -- Conservative consumer-side count.
                wr_bin_sync := gray_to_bin(wr_ptr_gray_at_rd);
                fill_r := resize(wr_bin_sync, PTR_W + 2)
                          - resize(next_rd_bin, PTR_W + 2);
                rd_count_q <= resize(fill_r, CNT_W);
            end if;
        end if;
    end process;

    ------------------------------------------------------------------
    -- Outputs.
    ------------------------------------------------------------------
    wr_full  <= wr_full_q;
    rd_empty <= rd_empty_q;
    wr_count <= std_logic_vector(wr_count_q);
    rd_count <= std_logic_vector(rd_count_q);

end architecture rtl;
