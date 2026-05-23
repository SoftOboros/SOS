-- =============================================================================
-- sos_synchronizer.vhd  --  L0 N-FF clock-domain crossing synchronizer
--                          (portable VHDL-2008)
--
--   THE canonical CDC primitive in the SOS-08-A L0 catalogue.  Every other
--   primitive that crosses clock domains either composes this primitive
--   internally (e.g. `sos_fifo_async`'s gray-pointer chains, `sos_dpram_arb`'s
--   dual-clock cross-port handshake) or names this primitive as the
--   caller-side responsibility on its reset/strobe paths (INV-S-HDL-A-1,
--   §6.5/§6.8/§6.10 MTBF-treatment notes).
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.9
--   Per 2026-05-23 ratification (§15) plus the same date's impl wave-1 PCDN
--   amendments: portable-RTL face carries the vendor synthesis attributes
--   for all three target families (Xilinx ASYNC_REG, Intel
--   altera_attribute SYNCHRONIZER_IDENTIFICATION FORCED, Lattice
--   syn_preserve) declared simultaneously; the synthesis tool picks the
--   attribute family it recognizes and ignores the others.  This makes
--   the portable face self-contained — no vendor-shim wrapper is needed
--   for "just give me a safe synchronizer" sites; the vendor-IP shim path
--   exists for callers who want xpm_cdc_single / altera_std_synchronizer /
--   vendor-curated alternatives (PCDN-A-fifo-RESET_MEM-style opt-in).
--
--   Mandatory `STAGES` and `WIDTH`, no defaults (INV-S-HDL-A-5; the lone
--   GRANT_LATENCY_CYCLES exception applies to `sos_arbiter_rr` only).
--   `STAGES` ≥ 2 enforced via an elaboration-time assertion; `WIDTH` ≥ 1
--   is the natural VHDL `positive` domain.  Synchronous active-high
--   `rst_dst` on the destination domain (PCDN-A-003, INV-S-HDL-A-1) clears
--   the entire flop chain; there is no source-side reset port because the
--   source-domain signal is treated as asynchronous to this primitive.
--
-- Cited invariants (this primitive does not redefine them):
--   INV-SOS-A  chart-as-source                     (SOS-07 §6)
--   INV-SOS-B  vectors-as-deliverable              (SOS-07 §6)
--   INV-SOS-E  explicit AuthorityRelationship      (SOS-07 §6)
--   INV-SOS-G  verified-codegen position           (SOS-07 §6)
--   INV-SOS-H  vector-to-chart traceability        (SOS-07 §6)
--   INV-S-HDL-1 handshake-compatible ports         (SOS-08 §7)
--   INV-S-HDL-2 static-allocation discipline       (SOS-08 §7)
--   INV-S-HDL-3 cross-domain isolation             (SOS-08 §7;
--                  this primitive IS the cross-domain isolation primitive
--                  — its flop chain is the very thing INV-S-HDL-3 excludes
--                  from the formal model.  MTBF sign-off lives at
--                  `rtl/sos_synchronizer/MTBF.md` per PCDN-A-006.)
--   INV-S-HDL-4 cooperative-only at v1             (SOS-08 §7)
--   INV-S-HDL-5 vector-to-chart traceability (HDL) (SOS-08 §7)
--   INV-S-HDL-A-1 uniform sync active-high reset   (SOS-08-A §7)
--   INV-S-HDL-A-2 handshake associativity          (SOS-08-A §7;
--                  this primitive is a pure data-crossing — no handshake;
--                  associativity holds trivially.)
--   INV-S-HDL-A-3 vendor-shim byte-identical wrap  (SOS-08-A §7;
--                  portable face here, vendor shims compose elsewhere.)
--   INV-S-HDL-A-4 one-hot internal FSM by default  (SOS-08-A §7;
--                  N/A — no FSM, just a flop chain.)
--   INV-S-HDL-A-5 mandatory parameters, no default (SOS-08-A §7)
--
-- Behavioural contract:
--   `STAGES` flip-flops in series on `clk_dst`, no combinational logic
--   between them.  The source-domain signal `d_src` is sampled into the
--   first flop on every rising edge of `clk_dst`; the destination-domain
--   output `d_dst` is the registered output of the last flop.  `rst_dst`
--   clears all flops to 0.  Multi-bit `WIDTH > 1` is permitted ONLY when
--   the caller guarantees Gray coding upstream (one-bit-changes-per
--   source-domain transition); the primitive does not enforce this and
--   the failure mode under non-Gray multi-bit input is silent bit-skew
--   on the destination side.  Single-bit `WIDTH = 1` is unconditionally
--   safe.
--
-- Latency:
--   `d_dst` reflects a stable `d_src` value `STAGES` `clk_dst` cycles
--   after the source-domain transition completes.  The first `STAGES-1`
--   stages may carry metastable values; the verification claim that the
--   probability of metastability propagating past the final stage is
--   below the target MTBF is recorded in `MTBF.md`, NOT as an SVA
--   property (INV-S-HDL-3 + PCDN-A-006).
--
-- Resource cost:
--   `STAGES * WIDTH` destination-domain flip-flops.  Zero combinational
--   logic on the synchronizer path; the synthesis-tool attributes below
--   instruct the place-and-route tool to keep the flops physically
--   adjacent (improves metastability resolution time).
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

entity sos_synchronizer is
  generic (
    -- Mandatory; no default per INV-S-HDL-A-5.  ≥ 2 enforced below.
    STAGES : positive;
    -- Mandatory; no default per INV-S-HDL-A-5.  ≥ 1 is the natural
    -- `positive` domain.  Multi-bit users MUST Gray-code upstream
    -- (§6.9 caller responsibility).
    WIDTH  : positive
  );
  port (
    -- Destination-domain clock.  The source-domain clock is not a port
    -- of this primitive: the source-domain signal is treated as
    -- asynchronous to `clk_dst` by construction (this is THE CDC
    -- primitive — the whole point is that the source-domain timing is
    -- not modelled here).
    clk_dst : in  std_logic;
    -- Destination-domain synchronous active-high reset (INV-S-HDL-A-1,
    -- PCDN-A-003).  Source-side reset, if any, is the caller's
    -- responsibility — typically a second `sos_synchronizer` on the
    -- deassert edge of the source-side reset.
    rst_dst : in  std_logic;
    -- Source-domain data.  Asynchronous to `clk_dst`.  Multi-bit users
    -- MUST Gray-code (§6.9 docstring).
    d_src   : in  std_logic_vector(WIDTH - 1 downto 0);
    -- Destination-domain data.  Registered output of the last flop in
    -- the chain.
    d_dst   : out std_logic_vector(WIDTH - 1 downto 0)
  );
end entity sos_synchronizer;

architecture rtl of sos_synchronizer is

  ----------------------------------------------------------------------------
  -- Synchronizer flop chain.  `sync_chain(1)` captures `d_src`;
  -- `sync_chain(STAGES)` drives `d_dst`.
  ----------------------------------------------------------------------------
  type sync_chain_t is array (1 to STAGES) of
    std_logic_vector(WIDTH - 1 downto 0);
  signal sync_chain : sync_chain_t := (others => (others => '0'));

  ----------------------------------------------------------------------------
  -- Synthesis-tool synchronizer attributes.  All three vendor families are
  -- declared simultaneously; each synthesis tool picks the attribute it
  -- recognizes and silently ignores the others (this is the documented
  -- behaviour of every mainstream synthesis tool — unknown VHDL attributes
  -- elaborate cleanly and are ignored).  This makes the portable face
  -- self-contained for the common case; vendor-shim wrappers exist for
  -- callers wanting xpm_cdc_single / altera_std_synchronizer / vendor
  -- curated alternatives.
  --
  --   * Xilinx Vivado: ASYNC_REG = "TRUE" forces the synchronizer flops to
  --     be placed in the same SLICE (when possible) and excludes the chain
  --     from default timing analysis.
  --   * Intel Quartus: SYNCHRONIZER_IDENTIFICATION = "FORCED" marks the
  --     chain as a vendor-recognized synchronizer for MTBF reporting and
  --     fitter-side adjacency optimisation.
  --   * Lattice Diamond / Radiant: syn_preserve / syn_keep prevent the
  --     synthesizer from optimising the chain (e.g. retiming a stage into
  --     combinational logic, which would break the metastability
  --     resolution window).
  ----------------------------------------------------------------------------
  attribute async_reg : string;
  attribute async_reg of sync_chain : signal is "TRUE";

  attribute altera_attribute : string;
  attribute altera_attribute of sync_chain : signal is
    "-name SYNCHRONIZER_IDENTIFICATION FORCED";

  attribute syn_preserve : boolean;
  attribute syn_preserve of sync_chain : signal is true;

  attribute syn_keep : boolean;
  attribute syn_keep of sync_chain : signal is true;

begin

  ----------------------------------------------------------------------------
  -- Elaboration-time validation of STAGES (≥ 2 per §6.9).  STAGES = 1 is
  -- not a synchronizer — it is a single sampling flop with no MTBF
  -- improvement over a direct cross.  PCDN-A-006 requires the MTBF
  -- justification be computed against a STAGES ≥ 2 chain; STAGES = 1 fails
  -- elaboration to prevent silent under-spec.
  ----------------------------------------------------------------------------
  assert STAGES >= 2
    report "sos_synchronizer: SOS-08-A §6.9 requires STAGES >= 2; got "
           & integer'image(STAGES)
    severity failure;

  ----------------------------------------------------------------------------
  -- Sequential flop chain.  No combinational logic between stages; the
  -- synthesis-tool attributes above keep the chain physically adjacent for
  -- metastability resolution.
  ----------------------------------------------------------------------------
  process (clk_dst)
  begin
    if rising_edge(clk_dst) then
      if rst_dst = '1' then
        for i in 1 to STAGES loop
          sync_chain(i) <= (others => '0');
        end loop;
      else
        sync_chain(1) <= d_src;
        for i in 2 to STAGES loop
          sync_chain(i) <= sync_chain(i - 1);
        end loop;
      end if;
    end if;
  end process;

  d_dst <= sync_chain(STAGES);

end architecture rtl;
