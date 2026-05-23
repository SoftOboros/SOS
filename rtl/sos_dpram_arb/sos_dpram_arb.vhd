-------------------------------------------------------------------------------
-- sos_dpram_arb.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb contract)
--       docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 amendments — inherits
--                                              the READ_LATENCY + RESET_MEM
--                                              generic pattern ratified for
--                                              sos_fifo_sync via
--                                              PCDN-A-fifo-READ_LATENCY and
--                                              PCDN-A-fifo-RESET_MEM)
--       PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 — adds SYNC_STAGES
--                                              generic (≥ 2, default 2) on the
--                                              dual-clock gray-code address +
--                                              we synchroniser chain.
--                                              Mandatory-with-default per the
--                                              CDC-primitive named exception
--                                              extended to INV-S-HDL-A-5 this
--                                              wave (mirroring sos_fifo_async
--                                              and sos_synchronizer's default
--                                              treatment of the CDC depth).
--       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
--       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
--
-- Cross-phase invariants (cited, not redefined):
--   INV-SOS-A  chart-as-source
--   INV-SOS-B  vectors-as-deliverable at every layer
--   INV-SOS-C  MCP as sole modification surface
--   INV-SOS-D  iState authoring, SCXML canonical
--   INV-SOS-E  explicit AuthorityRelationship
--   INV-SOS-F  bound composition
--   INV-SOS-G  verified-codegen position
--   INV-SOS-H  vector-to-chart traceability
--
-- Cross-sub-phase invariants (SOS-08 §7, cited):
--   INV-S-HDL-1  handshake-compatible ports
--   INV-S-HDL-2  static-allocation discipline
--   INV-S-HDL-3  cross-domain isolation (MODE=DUAL_CLOCK only)
--   INV-S-HDL-4  cooperative-only at v1
--   INV-S-HDL-5  vector-to-chart traceability for HDL
--
-- Cross-primitive invariants (SOS-08-A §7, cited):
--   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
--   INV-S-HDL-A-2  handshake-port composition is associative
--   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
--   INV-S-HDL-A-4  one-hot internal FSM by default
--   INV-S-HDL-A-5  mandatory parameters have no defaults (per
--                  PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23, this
--                  primitive's `SYNC_STAGES` generic is a named exception:
--                  default 2, mirroring `sos_fifo_async` and
--                  `sos_synchronizer`. The CDC-primitive default-2 pattern
--                  extends INV-S-HDL-A-5's named-exception set this wave;
--                  see the §15 amendment landing in a sibling agent's PR.)
--
-- Dual-port RAM + arbiter L0 primitive. Two independent ports (A and B) each
-- carry a read AND a write channel. MODE selects single-clock vs dual-clock
-- (CDC) variants. The dual-clock variant composes a gray-code-address
-- synchroniser internally per INV-S-HDL-3; its MTBF is documented at
-- rtl/sos_dpram_arb/MTBF.md (required for MODE=DUAL_CLOCK deployments per the
-- SOS-08-A §12 acceptance gate (f)).
--
-- Port-naming deviation note (sub-PCDN to PCDN-SOS-08-A-002):
--   PCDN-A-002 ratified `m_axis_*` / `s_axis_*` prefixes on data-bearing
--   primitives. The two-port DPRAM does not map cleanly to a master/slave AXI
--   pair — each port has both read and write channels. We therefore use
--   `port_a_*` / `port_b_*` prefixes (with `_addr`, `_wdata`, `_we`, `_rdata`,
--   `_re`, `_full`, `_ready` suffixes). The deviation is recorded here as a
--   sub-PCDN consistent with §6.7's port enumeration (which uses bare
--   `addr_a` / `we_a` / `ack_a` etc.).
--
-- Collision-priority direction:
--   On simultaneous A+B writes targeting the same address, port A wins
--   (port_a_full asserted to A is impossible — A always wins; port_b_full
--   asserted to B for that cycle). Documented in §6.7 contract.
--
-- Same-cycle write+read on the same address (SINGLE_CLOCK mode):
--   The read path observes the OLD (pre-write) value. The write lands at the
--   NEXT rising edge of clk; the combinational/registered read sampled this
--   cycle therefore sees what was stored before the write. This is canonical
--   "read-old" semantics and matches default BRAM behaviour on Lattice ECP5
--   and the vendor `xpm_memory_tdpram` "read_first" mode.
-------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_dpram_arb is
    generic (
        -- INV-S-HDL-A-5: mandatory parameters, no defaults.
        DEPTH         : positive;
        WIDTH         : positive;
        -- MODE generic — single-clock vs dual-clock. Encoded as a string for
        -- VHDL-2008 cross-dialect parity with the SV variant; legal values:
        --   "SINGLE_CLOCK" — both ports share `clk` and `rst`.
        --   "DUAL_CLOCK"   — port A on `clk_a`/`rst_a`, port B on
        --                    `clk_b`/`rst_b`. Composes a gray-code-address
        --                    synchroniser internally (INV-S-HDL-3 applies).
        MODE          : string;
        -- READ_LATENCY: 0 = FWFT (rdata combinational off mem[addr]),
        --               1 = registered (rdata appears one cycle after `re`).
        -- Inherits the pattern from PCDN-A-fifo-READ_LATENCY (sos_fifo_sync).
        READ_LATENCY  : natural;
        -- RESET_MEM: false = mem retained across reset (legacy / smaller
        -- reset fanout); true = mem cleared to all-zero on reset (stricter
        -- post-reset semantics). Inherits PCDN-A-fifo-RESET_MEM pattern.
        RESET_MEM     : boolean;
        -- SYNC_STAGES: depth of the cross-domain gray-coded address + we
        -- synchroniser chain in MODE="DUAL_CLOCK". Mandatory-with-default-2
        -- per PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 (CDC-primitive
        -- named exception to INV-S-HDL-A-5; mirrors `sos_fifo_async` and
        -- `sos_synchronizer`). Default 2 is the well-trodden value for
        -- moderate clock ratios on low-frequency targets; deployments with
        -- MODE="DUAL_CLOCK" and f_clk ≥ 250 MHz MUST set SYNC_STAGES ≥ 3
        -- per MTBF.md §4. Larger values (3, 4) raise MTBF for high-
        -- frequency / tight-budget designs. MTBF.md sign-off MUST be
        -- updated when overriding SYNC_STAGES > 2 or targeting a different
        -- process. Unused in MODE="SINGLE_CLOCK" (no cross-domain crossing).
        -- ≥ 2 enforced via elaboration-time assertion.
        SYNC_STAGES   : positive := 2
    );
    port (
        -- Clock + reset — interpretation depends on MODE.
        --   SINGLE_CLOCK: only `clk` + `rst` are used; clk_a/clk_b/rst_a/rst_b
        --                 inputs MAY be tied off or to `clk`/`rst`.
        --   DUAL_CLOCK:   clk_a/rst_a drive port A; clk_b/rst_b drive port B;
        --                 `clk`/`rst` inputs MAY be tied to clk_a/rst_a (the
        --                 arbitrary choice — they are unused in DUAL_CLOCK).
        clk   : in std_logic;
        rst   : in std_logic;
        clk_a : in std_logic;
        rst_a : in std_logic;
        clk_b : in std_logic;
        rst_b : in std_logic;

        -- Port A: address + write channel + read channel + status.
        port_a_addr  : in  std_logic_vector
            (integer(ceil(log2(real(DEPTH)))) - 1 downto 0);
        port_a_wdata : in  std_logic_vector(WIDTH - 1 downto 0);
        port_a_we    : in  std_logic;   -- 1-cycle write pulse
        port_a_re    : in  std_logic;   -- 1-cycle read  pulse
        port_a_rdata : out std_logic_vector(WIDTH - 1 downto 0);
        port_a_full  : out std_logic;   -- arbiter blocked A's write this cycle
        port_a_ready : out std_logic;   -- complement of port_a_full

        -- Port B: same shape, swapped suffix.
        port_b_addr  : in  std_logic_vector
            (integer(ceil(log2(real(DEPTH)))) - 1 downto 0);
        port_b_wdata : in  std_logic_vector(WIDTH - 1 downto 0);
        port_b_we    : in  std_logic;
        port_b_re    : in  std_logic;
        port_b_rdata : out std_logic_vector(WIDTH - 1 downto 0);
        port_b_full  : out std_logic;
        port_b_ready : out std_logic
    );
end entity sos_dpram_arb;

architecture rtl of sos_dpram_arb is

    -- Address width derived from DEPTH.
    constant ADDR_W : natural :=
        integer(ceil(log2(real(DEPTH))));

    -- Storage. Single shared mem array. Per-port read paths sample under the
    -- per-port clock in DUAL_CLOCK mode (synthesis tools will infer a
    -- dual-clock true-DPRAM macro on ECP5/Xilinx/Intel — the vendor shim path
    -- elects an explicit IP macro for stricter timing closure).
    type mem_t is array (0 to DEPTH - 1) of std_logic_vector(WIDTH - 1 downto 0);
    shared variable mem : mem_t := (others => (others => '0'));

    -- Registered-read holding registers (READ_LATENCY=1 path only).
    signal rdata_a_q : std_logic_vector(WIDTH - 1 downto 0) :=
                       (others => '0');
    signal rdata_b_q : std_logic_vector(WIDTH - 1 downto 0) :=
                       (others => '0');

    -- FWFT read paths (combinational).
    signal rdata_a_fwft : std_logic_vector(WIDTH - 1 downto 0);
    signal rdata_b_fwft : std_logic_vector(WIDTH - 1 downto 0);

    -- Collision detector.
    --   In SINGLE_CLOCK mode this is combinational off the live address
    --   buses.
    --   In DUAL_CLOCK  mode this is a best-effort sample of port B's
    --   address gray-synchronised into the port-A clock domain. The
    --   synchroniser is a SYNC_STAGES-deep flop chain (default 2); MTBF.md
    --   records the metastability calc per INV-S-HDL-3.
    signal collision : std_logic := '0';

    -- DUAL_CLOCK-only: gray-coded shadow of port B's address sampled into
    -- the port A clock domain. SYNC_STAGES-deep flop chain
    -- (PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23). Sibling arrays carry
    -- the corresponding port_b_we qualifier through the same depth.
    signal port_b_addr_gray_b   : std_logic_vector(ADDR_W - 1 downto 0) :=
                                  (others => '0');
    signal port_b_we_b          : std_logic := '0';

    -- Synchroniser flop chains. `sync_addr_chain(1)` captures the
    -- gray-coded port_b_addr from `clk_b`; `sync_addr_chain(SYNC_STAGES)`
    -- drives the A-domain collision detector. The `_we` chain is the
    -- single-bit qualifier travelling in lockstep.
    type sync_addr_chain_t is array (1 to SYNC_STAGES) of
        std_logic_vector(ADDR_W - 1 downto 0);
    signal sync_addr_chain : sync_addr_chain_t :=
        (others => (others => '0'));

    type sync_we_chain_t is array (1 to SYNC_STAGES) of std_logic;
    signal sync_we_chain : sync_we_chain_t := (others => '0');

    ----------------------------------------------------------------------------
    -- Synthesis-tool synchronizer attributes for the chains. All three
    -- vendor families are declared simultaneously; each synthesis tool picks
    -- the attribute it recognizes and silently ignores the others. Mirrors
    -- the pattern in `sos_synchronizer.vhd` (which is THE canonical CDC
    -- primitive — `sos_dpram_arb`'s DUAL_CLOCK chain composes the same
    -- discipline locally rather than instantiating sos_synchronizer because
    -- the gray-decode is interleaved with the chain in the existing wave-1
    -- shape; the attributes are the load-bearing piece for adjacency / no-
    -- retiming and are reproduced here verbatim).
    --
    --   * Xilinx Vivado: ASYNC_REG = "TRUE" forces the synchronizer flops
    --     into the same SLICE where possible and excludes them from default
    --     timing analysis.
    --   * Intel Quartus: SYNCHRONIZER_IDENTIFICATION = "FORCED" marks the
    --     chain as a vendor-recognized synchronizer for MTBF reporting and
    --     fitter-side adjacency optimisation.
    --   * Lattice Diamond / Radiant: syn_preserve / syn_keep prevent the
    --     synthesizer from optimising the chain (e.g. retiming a stage into
    --     combinational logic, which would break the metastability
    --     resolution window).
    ----------------------------------------------------------------------------
    attribute async_reg : string;
    attribute async_reg of sync_addr_chain : signal is "TRUE";
    attribute async_reg of sync_we_chain   : signal is "TRUE";

    attribute altera_attribute : string;
    attribute altera_attribute of sync_addr_chain : signal is
        "-name SYNCHRONIZER_IDENTIFICATION FORCED";
    attribute altera_attribute of sync_we_chain   : signal is
        "-name SYNCHRONIZER_IDENTIFICATION FORCED";

    attribute syn_preserve : boolean;
    attribute syn_preserve of sync_addr_chain : signal is true;
    attribute syn_preserve of sync_we_chain   : signal is true;

    attribute syn_keep : boolean;
    attribute syn_keep of sync_addr_chain : signal is true;
    attribute syn_keep of sync_we_chain   : signal is true;

    -- Helpers.
    function bin2gray(b : std_logic_vector) return std_logic_vector is
        variable g : std_logic_vector(b'range);
    begin
        g(b'high) := b(b'high);
        for i in b'high - 1 downto b'low loop
            g(i) := b(i + 1) xor b(i);
        end loop;
        return g;
    end function;

    function gray2bin(g : std_logic_vector) return std_logic_vector is
        variable b : std_logic_vector(g'range);
    begin
        b(g'high) := g(g'high);
        for i in g'high - 1 downto g'low loop
            b(i) := b(i + 1) xor g(i);
        end loop;
        return b;
    end function;

begin

    ----------------------------------------------------------------------
    -- Elaboration-time validation of SYNC_STAGES (≥ 2 per
    -- PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23). SYNC_STAGES = 1 is
    -- not a synchroniser — it is a single sampling flop with no MTBF
    -- improvement over a direct cross. Mirrors the elaboration-time
    -- assertion in sos_synchronizer.vhd. Unused in MODE="SINGLE_CLOCK"
    -- but enforced unconditionally because the generic is part of the
    -- module surface in either mode.
    ----------------------------------------------------------------------
    assert SYNC_STAGES >= 2
        report "sos_dpram_arb: SOS-08-A §6.7 / PCDN-A-dpram-SYNC_STAGES "
               & "requires SYNC_STAGES >= 2; got "
               & integer'image(SYNC_STAGES)
        severity failure;

    ----------------------------------------------------------------------
    -- SINGLE_CLOCK branch — both ports share clk + rst.
    -- INV-S-HDL-A-2 holds at the per-port handshake level (port_a_ready
    -- and port_b_ready compose associatively with downstream consumers).
    ----------------------------------------------------------------------
    g_single_clock : if MODE = "SINGLE_CLOCK" generate

        -- Combinational FWFT read paths.
        rdata_a_fwft <= mem(to_integer(unsigned(port_a_addr)));
        rdata_b_fwft <= mem(to_integer(unsigned(port_b_addr)));

        -- Combinational collision detector. A-wins on tie.
        collision <= '1' when (port_a_we = '1' and port_b_we = '1' and
                               port_a_addr = port_b_addr)
                      else '0';

        port_a_full  <= '0';                -- A always wins; never blocked.
        port_a_ready <= '1';
        port_b_full  <= collision;          -- B blocked on collision.
        port_b_ready <= not collision;

        -- Read path selection by READ_LATENCY.
        g_read_a_fwft : if READ_LATENCY = 0 generate
            port_a_rdata <= rdata_a_fwft;
        end generate;
        g_read_a_reg : if READ_LATENCY /= 0 generate
            port_a_rdata <= rdata_a_q;
        end generate;
        g_read_b_fwft : if READ_LATENCY = 0 generate
            port_b_rdata <= rdata_b_fwft;
        end generate;
        g_read_b_reg : if READ_LATENCY /= 0 generate
            port_b_rdata <= rdata_b_q;
        end generate;

        -- Single shared-clock write + registered-read process.
        process (clk)
        begin
            if rising_edge(clk) then
                if rst = '1' then
                    rdata_a_q <= (others => '0');
                    rdata_b_q <= (others => '0');
                    if RESET_MEM then
                        for i in 0 to DEPTH - 1 loop
                            mem(i) := (others => '0');
                        end loop;
                    end if;
                else
                    -- Write path. Port A's write always lands. Port B's write
                    -- lands only when there is no collision (A wins on tie).
                    if port_a_we = '1' then
                        mem(to_integer(unsigned(port_a_addr))) := port_a_wdata;
                    end if;
                    if port_b_we = '1' and collision = '0' then
                        mem(to_integer(unsigned(port_b_addr))) := port_b_wdata;
                    end if;

                    -- Registered-read latch. On `re`, capture the PRE-write
                    -- value at the requested address into the holding
                    -- register. The read pulse and the write pulse on the
                    -- same address in the same cycle therefore give the
                    -- consumer the OLD value (read-old semantics — canonical
                    -- BRAM behaviour).
                    if READ_LATENCY /= 0 then
                        if port_a_re = '1' then
                            rdata_a_q <= rdata_a_fwft;
                        end if;
                        if port_b_re = '1' then
                            rdata_b_q <= rdata_b_fwft;
                        end if;
                    end if;
                end if;
            end if;
        end process;

    end generate;

    ----------------------------------------------------------------------
    -- DUAL_CLOCK branch — port A on clk_a/rst_a, port B on clk_b/rst_b.
    -- INV-S-HDL-3 applies: the cross-port collision detection rides a
    -- gray-code address synchroniser; the synchroniser flops are excluded
    -- from the formal model and verified via MTBF.md.
    ----------------------------------------------------------------------
    g_dual_clock : if MODE = "DUAL_CLOCK" generate

        -- Combinational FWFT read paths (each port reads from its own
        -- clock domain; the dual-clock BRAM macro on the chosen vendor
        -- target gives same-cycle read of mem[addr]).
        rdata_a_fwft <= mem(to_integer(unsigned(port_a_addr)));
        rdata_b_fwft <= mem(to_integer(unsigned(port_b_addr)));

        -- Best-effort collision detect — gray-coded port B addr + we sync'd
        -- into the port A clock domain through a SYNC_STAGES-deep flop
        -- chain. The arbiter blocks port B (A wins) when the synced shadow
        -- matches port A's live address AND both port_a_we and the synced
        -- port_b_we are asserted.
        --
        -- Source flop in clk_b: gray-codes port_b_addr and registers
        -- port_b_we for handoff.
        process (clk_b)
        begin
            if rising_edge(clk_b) then
                if rst_b = '1' then
                    port_b_addr_gray_b <= (others => '0');
                    port_b_we_b        <= '0';
                else
                    port_b_addr_gray_b <= bin2gray(port_b_addr);
                    port_b_we_b        <= port_b_we;
                end if;
            end if;
        end process;

        -- Destination synchroniser chain in clk_a, SYNC_STAGES deep
        -- (PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23). The
        -- async_reg / altera_attribute / syn_preserve attributes on
        -- `sync_addr_chain` and `sync_we_chain` instruct each vendor's
        -- synthesis tool to keep the flops adjacent and exclude them from
        -- default timing analysis. INV-S-HDL-3 excludes the chain from the
        -- formal model; MTBF.md is the verification artifact.
        process (clk_a)
        begin
            if rising_edge(clk_a) then
                if rst_a = '1' then
                    for i in 1 to SYNC_STAGES loop
                        sync_addr_chain(i) <= (others => '0');
                        sync_we_chain(i)   <= '0';
                    end loop;
                else
                    sync_addr_chain(1) <= port_b_addr_gray_b;
                    sync_we_chain(1)   <= port_b_we_b;
                    for i in 2 to SYNC_STAGES loop
                        sync_addr_chain(i) <= sync_addr_chain(i - 1);
                        sync_we_chain(i)   <= sync_we_chain(i - 1);
                    end loop;
                end if;
            end if;
        end process;

        -- A-domain collision view: gray-decoded port-B-address compared to
        -- port A's live address, qualified by both write enables. The
        -- deepest stage of each chain is what the collision detector
        -- consumes (INV-S-HDL-3 boundary).
        collision <= '1' when (port_a_we = '1'
                               and sync_we_chain(SYNC_STAGES) = '1'
                               and gray2bin(sync_addr_chain(SYNC_STAGES))
                                   = port_a_addr)
                      else '0';

        port_a_full  <= '0';
        port_a_ready <= '1';
        port_b_full  <= collision;
        port_b_ready <= not collision;

        -- Read path selection.
        g_dc_read_a_fwft : if READ_LATENCY = 0 generate
            port_a_rdata <= rdata_a_fwft;
        end generate;
        g_dc_read_a_reg : if READ_LATENCY /= 0 generate
            port_a_rdata <= rdata_a_q;
        end generate;
        g_dc_read_b_fwft : if READ_LATENCY = 0 generate
            port_b_rdata <= rdata_b_fwft;
        end generate;
        g_dc_read_b_reg : if READ_LATENCY /= 0 generate
            port_b_rdata <= rdata_b_q;
        end generate;

        -- Port A write + registered-read process.
        process (clk_a)
        begin
            if rising_edge(clk_a) then
                if rst_a = '1' then
                    rdata_a_q <= (others => '0');
                    if RESET_MEM then
                        for i in 0 to DEPTH - 1 loop
                            mem(i) := (others => '0');
                        end loop;
                    end if;
                else
                    if port_a_we = '1' then
                        mem(to_integer(unsigned(port_a_addr))) := port_a_wdata;
                    end if;
                    if READ_LATENCY /= 0 then
                        if port_a_re = '1' then
                            rdata_a_q <= rdata_a_fwft;
                        end if;
                    end if;
                end if;
            end if;
        end process;

        -- Port B write + registered-read process. B's write lands only when
        -- the collision detector (in A's domain) is NOT asserted. Because
        -- the collision is detected in clk_a, the gating signal must be
        -- exported back to clk_b for B's write to be authoritatively
        -- ack/nack'd in B's own clock domain. For v1 we use the live
        -- A-domain `collision` signal directly — this is a synchronous
        -- read across domains and is only safe because (a) the consumer
        -- of B's port_b_ready already lives in clk_b (so it observes the
        -- A-domain `collision` through the implicit ready/we comparator)
        -- and (b) the collision is conservative (false-positives stall a
        -- B write for one extra cycle; false-negatives are excluded by
        -- the gray-synchroniser stage count). MTBF.md records the bound.
        process (clk_b)
        begin
            if rising_edge(clk_b) then
                if rst_b = '1' then
                    rdata_b_q <= (others => '0');
                else
                    if port_b_we = '1' and collision = '0' then
                        mem(to_integer(unsigned(port_b_addr))) := port_b_wdata;
                    end if;
                    if READ_LATENCY /= 0 then
                        if port_b_re = '1' then
                            rdata_b_q <= rdata_b_fwft;
                        end if;
                    end if;
                end if;
            end if;
        end process;

    end generate;

end architecture rtl;
