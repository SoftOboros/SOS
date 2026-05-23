-------------------------------------------------------------------------------
-- examples/sos_dpram_arb/instantiate.vhd
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (instantiation example)
--       docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 amendments —
--                                              READ_LATENCY + RESET_MEM
--                                              pattern inherited from
--                                              PCDN-A-fifo-* on sos_fifo_sync)
--       PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 — adds the
--                                              `u_dpram_safety_critical`
--                                              third instance which exercises
--                                              SYNC_STAGES=3 per MTBF.md §4's
--                                              "deployments at f_clk >= 250
--                                              MHz on ECP5-class targets MUST
--                                              use SYNC_STAGES >= 3"
--                                              prescription.
--       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
--       INV-S-HDL-A-5  mandatory parameters, no defaults (SYNC_STAGES is the
--                      CDC-primitive named-exception default of 2 per
--                      PCDN-A-dpram-SYNC_STAGES — the named-exception set on
--                      INV-S-HDL-A-5 extends this wave from GRANT_LATENCY_CYCLES
--                      to also cover SYNC_STAGES on CDC primitives.)
--       INV-S-HDL-3    cross-domain isolation (MODE=DUAL_CLOCK only)
--
-- Three example bindings are shown:
--   * u_dpram_single — MODE="SINGLE_CLOCK", DEPTH=64, WIDTH=32,
--                      READ_LATENCY=0, RESET_MEM=false.
--                      Single-clock dual-port RAM with combinational reads.
--   * u_dpram_dual   — MODE="DUAL_CLOCK",   DEPTH=64, WIDTH=32,
--                      READ_LATENCY=1, RESET_MEM=true, SYNC_STAGES=2 (default
--                      via omission). MTBF.md sign-off REQUIRED at deployment
--                      time per SOS-08-A §12 (f). Use this shape on low-
--                      frequency targets (f_clk <= ~50 MHz on ECP5-class τ).
--   * u_dpram_safety_critical
--                    — MODE="DUAL_CLOCK", DEPTH=64, WIDTH=32, READ_LATENCY=1,
--                      RESET_MEM=true, SYNC_STAGES=3. Use SYNC_STAGES=3 for
--                      safety-critical deployments at f_clk >= 250 MHz on
--                      ECP5-class targets per MTBF.md §4 worked example
--                      (SYNC_STAGES=3 raises per-bit MTBF from ~258 s at
--                      STAGES=2 to ~5.7e6 s, lifting the aggregate above the
--                      10⁶ s ECP5 safety threshold).
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
        dc_port_b_ready : out std_logic;

        -- DUAL_CLOCK safety-critical instance ports (SYNC_STAGES=3 per
        -- PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 + MTBF.md §4).
        sc_dc_port_a_addr  : in  std_logic_vector(5 downto 0);
        sc_dc_port_a_wdata : in  std_logic_vector(31 downto 0);
        sc_dc_port_a_we    : in  std_logic;
        sc_dc_port_a_re    : in  std_logic;
        sc_dc_port_a_rdata : out std_logic_vector(31 downto 0);
        sc_dc_port_a_full  : out std_logic;
        sc_dc_port_a_ready : out std_logic;

        sc_dc_port_b_addr  : in  std_logic_vector(5 downto 0);
        sc_dc_port_b_wdata : in  std_logic_vector(31 downto 0);
        sc_dc_port_b_we    : in  std_logic;
        sc_dc_port_b_re    : in  std_logic;
        sc_dc_port_b_rdata : out std_logic_vector(31 downto 0);
        sc_dc_port_b_full  : out std_logic;
        sc_dc_port_b_ready : out std_logic
    );
end entity sos_dpram_arb_example;

architecture rtl of sos_dpram_arb_example is

    component sos_dpram_arb is
        generic (
            DEPTH         : positive;
            WIDTH         : positive;
            MODE          : string;
            READ_LATENCY  : natural;
            RESET_MEM     : boolean;
            -- PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 — default 2 here
            -- documents the CDC-primitive named-exception default; explicit
            -- instances below either accept the default (u_dpram_single,
            -- u_dpram_dual) or override (u_dpram_safety_critical => 3).
            SYNC_STAGES   : positive := 2
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
    -- SYNC_STAGES omitted → accepts the CDC-primitive default of 2 (per
    -- PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23). Suitable for low-
    -- frequency deployments (f_clk <= ~50 MHz on ECP5-class τ); MTBF.md §4
    -- documents the per-frequency MTBF floor.
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

    -- Example C: DUAL_CLOCK safety-critical — use SYNC_STAGES=3 for safety-
    -- critical deployments at f_clk >= 250 MHz on ECP5-class targets per
    -- PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 and MTBF.md §4 worked
    -- example. The third synchroniser stage raises the per-bit MTBF from
    -- ~258 s at STAGES=2 (4.85e8 / 1.875e6) to ~5.7e6 s (exp(30) ≈ 1.07e13
    -- divided by the same denominator) — a 22000x improvement that brings
    -- the aggregate bus MTBF above the safety threshold for the worked
    -- example. MTBF.md sign-off REQUIRED with the per-deployment numbers.
    u_dpram_safety_critical : sos_dpram_arb
        generic map (
            DEPTH        => 64,
            WIDTH        => 32,
            MODE         => "DUAL_CLOCK",
            READ_LATENCY => 1,        -- registered read on each port
            RESET_MEM    => true,     -- strict: mem zeroed on reset
            SYNC_STAGES  => 3         -- safety-critical at >= 250 MHz / ECP5
        )
        port map (
            clk   => clk_a,           -- tied to clk_a; unused in DUAL_CLOCK
            rst   => rst_a,
            clk_a => clk_a,
            rst_a => rst_a,
            clk_b => clk_b,
            rst_b => rst_b,

            port_a_addr  => sc_dc_port_a_addr,
            port_a_wdata => sc_dc_port_a_wdata,
            port_a_we    => sc_dc_port_a_we,
            port_a_re    => sc_dc_port_a_re,
            port_a_rdata => sc_dc_port_a_rdata,
            port_a_full  => sc_dc_port_a_full,
            port_a_ready => sc_dc_port_a_ready,

            port_b_addr  => sc_dc_port_b_addr,
            port_b_wdata => sc_dc_port_b_wdata,
            port_b_we    => sc_dc_port_b_we,
            port_b_re    => sc_dc_port_b_re,
            port_b_rdata => sc_dc_port_b_rdata,
            port_b_full  => sc_dc_port_b_full,
            port_b_ready => sc_dc_port_b_ready
        );

end architecture rtl;
