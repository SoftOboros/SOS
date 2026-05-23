--------------------------------------------------------------------------------
-- sos_resource_pool.vhd - L1 service: chart-tracked resource pool
--
-- @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.3 (sos_resource_pool
--                                                       interface + behavioural
--                                                       contract + service-level
--                                                       SVA)
--              docs/concepts/SOS-08-B-CONCEPTS.md §15 (2026-05-23 ratification:
--                                                       PCDN-SOS-08-B-003 →
--                                                       ID_WIDTH parameterised
--                                                       with default 16,
--                                                       matching chart's
--                                                       task_id; per-pool width
--                                                       selected at chart-
--                                                       emission time from
--                                                       MAX_TASKS / MAX_SEMS /
--                                                       MAX_QUEUES.)
--              docs/concepts/SOS-08-A-CONCEPTS.md §6.6 (sos_credit_counter L0
--                                                       primitive composed here)
--              docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb L0
--                                                       primitive composed here)
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 service set), §7
--                                                  (INV-S-HDL-1..5)
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- Cross-phase invariants (cited, not redefined):
--   INV-SOS-A  chart-as-source                  (SOS-07 §6)
--   INV-SOS-B  vectors-as-deliverable           (SOS-07 §6)
--   INV-SOS-C  MCP as sole modification surface (SOS-07 §6)
--   INV-SOS-D  iState authoring, SCXML canon.   (SOS-07 §6)
--   INV-SOS-E  explicit AuthorityRelationship   (SOS-07 §6)
--   INV-SOS-F  bound composition                (SOS-07 §6)
--   INV-SOS-G  verified-codegen position        (SOS-07 §6)
--   INV-SOS-H  vector-to-chart traceability     (SOS-07 §6)
--
-- Cross-sub-phase invariants (SOS-08 §7, cited):
--   INV-S-HDL-1  handshake-compatible ports     — alloc/free pulse handshakes
--                                                  match the L0 surface (see
--                                                  §5.1 of SOS-08-A).
--   INV-S-HDL-2  static-allocation discipline   — POOL_SIZE bounded at synth.
--   INV-S-HDL-3  cross-domain isolation         — N/A: SINGLE_CLOCK service.
--   INV-S-HDL-4  cooperative-only at v1
--   INV-S-HDL-5  vector-to-chart traceability for HDL
--
-- Cross-service invariants (SOS-08-B §7, cited):
--   INV-S-HDL-B-1  vocabulary mirror discipline (alloc / free / read_meta /
--                                                 write_meta vocabulary maps
--                                                 onto SOS-04/05 TCB_POOL /
--                                                 SEM_POOL / QUEUE_POOL).
--   INV-S-HDL-B-2  L0 non-modification          — composes credit_counter +
--                                                  dpram_arb without modifying
--                                                  their behaviour.
--   INV-S-HDL-B-3  service-level SVA on every instance — companion bind file
--                                                  `tb/sos_resource_pool/
--                                                  sos_resource_pool_bind.sv`.
--   INV-S-HDL-B-4  vendor-IP pass-through       — dpram_arb's vendor shim
--                                                  inherits transparently.
--   INV-S-HDL-B-5  chart-vocabulary failure rendering
--                                                — cocotb assertions name the
--                                                  chart verb (`task.create` /
--                                                  `task.delete`).
--
-- Behaviour:
--   * Composes ONE `sos_credit_counter` (INIT_CREDITS = POOL_SIZE,
--     MAX_CREDITS = POOL_SIZE) + ONE `sos_dpram_arb` (SINGLE_CLOCK,
--     DEPTH=POOL_SIZE, WIDTH=META_WIDTH, READ_LATENCY=0 (FWFT), RESET_MEM=0)
--     + a `free_vec` bit-vector tracker of POOL_SIZE bits (one per slot) +
--     a lowest-id-first priority encoder that converts the free-vec into the
--     next `alloc_id`.
--
--   * Free-vector initialisation: at reset, every bit in `free_vec` is set
--     (all slots free); after reset the credit_counter's `credits` output
--     equals POOL_SIZE on the cycle after reset deasserts, matching
--     popcount(free_vec) by construction (SVA-POOL-4 conservation, restated
--     in companion sva file).
--
--   * alloc_req / alloc_ack / alloc_id (pulse handshake; mirrors
--     sos_credit_counter §6.6):
--       - alloc_ack is the combinational AND of alloc_req and (credits > 0).
--         (credits is read directly off the inner credit_counter.)
--       - alloc_id is the lowest-set-bit index of free_vec at the time
--         alloc_req fires. The chosen-bit direction is **lowest-id-first**
--         (priority encoder scans bit 0 → POOL_SIZE-1); rationale: matches
--         the chart-side static-pool indexing convention (SOS-04 / SOS-05
--         allocate from id=0 upward into TCB_POOL[MAX_TASKS]).
--       - On the cycle alloc_ack fires, the credit_counter's acquire_req is
--         driven high (decrementing credits next cycle) AND the free_vec
--         bit at alloc_id is cleared next cycle.
--       - alloc_id is undefined when alloc_ack is low.
--
--   * free_req / free_id (pulse; one-shot):
--       - When free_req fires AND free_vec[free_id] == '0' (the slot is
--         currently busy), the credit_counter's release_req is driven high
--         (incrementing credits next cycle) AND free_vec[free_id] is set
--         next cycle.
--       - When free_req fires AND free_vec[free_id] == '1' (the slot is
--         already free, i.e. a double-free), the request is silently
--         dropped — no credit_counter release, no free_vec change. The
--         chart compiler enforces correctness per INV-SOS-G; SVA-POOL-2 in
--         the companion sva file asserts the no-op behaviour.
--
--   * read_meta is FWFT (combinational read off the DPRAM's port-A read
--     path); read_id drives port_a_addr directly. The chart-side syscall
--     ABI gets a same-cycle metadata read with `read_id` presented.
--
--   * write_req / write_id / write_meta uses the DPRAM's port-A write
--     channel; write_req drives port_a_we as a 1-cycle pulse. The write
--     lands at the next rising edge of clk; same-cycle read of the same
--     slot observes the OLD (pre-write) value per §6.7 "read-old"
--     semantics.
--
--   * Port-B of the inner DPRAM is reserved for future use (e.g. a parallel
--     observer or refill controller); v1 ties it off (we=0, re=0).
--
--   * free_count is driven directly from the inner credit_counter's
--     `credits` output, which is `popcount(free_vec)` by SVA-POOL-4
--     conservation.
--
-- Static elaboration-time check (matches L0 primitives):
--   POOL_SIZE >= 1 and META_WIDTH >= 1 and ID_WIDTH >= clog2(POOL_SIZE).
--
-- Same-cycle alloc + free behaviour:
--   alloc_req and free_req are independent pulse ports — both MAY pulse in
--   the same cycle. The free-vector update applies BOTH the alloc-bit-clear
--   AND the free-bit-set computed off the pre-update free_vec. If
--   free_id == alloc_id on the same cycle (the caller is freeing the very
--   slot the priority encoder picked for alloc), the resulting bit value
--   for that index is the alloc-side clear (next-cycle free_vec[id] = '0')
--   — the simultaneous free is silently absorbed because the encoder
--   already chose that bit. The inner credit_counter sees both
--   acquire_req=1 and release_req=1 simultaneously and nets to zero per
--   sos_credit_counter §6.6 ("same-cycle acquire+release is net-neutral").
--   This is documented behaviour, not a defect.
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_resource_pool is
    generic (
        -- Mandatory; no default per INV-S-HDL-A-5. Bounded by the chart
        -- compiler from MAX_TASKS / MAX_SEMS / MAX_QUEUES (SOS-08-B §6.3).
        POOL_SIZE   : positive;
        -- Default 16 per PCDN-SOS-08-B-003 resolution (matches chart's
        -- task_id width). Per-pool override at chart-emission time.
        ID_WIDTH    : positive := 16;
        -- Mandatory; no default. Bounded by the chart's TCB / sem-handle /
        -- queue-handle struct width.
        META_WIDTH  : positive
    );
    port (
        clk        : in  std_logic;
        rst        : in  std_logic;                                                              -- sync active-high

        -- alloc side: pulse req in, pulse ack + id out.
        alloc_req  : in  std_logic;                                                              -- 1-cycle pulse
        alloc_ack  : out std_logic;                                                              -- 1-cycle pulse on success
        alloc_id   : out std_logic_vector(ID_WIDTH - 1 downto 0);                                -- valid only when alloc_ack='1'

        -- free side: pulse req in, id in.
        free_req   : in  std_logic;                                                              -- 1-cycle pulse
        free_id    : in  std_logic_vector(ID_WIDTH - 1 downto 0);

        -- read side: FWFT (combinational) read by id.
        read_id    : in  std_logic_vector(ID_WIDTH - 1 downto 0);
        read_meta  : out std_logic_vector(META_WIDTH - 1 downto 0);

        -- write side: pulse req in, id + meta in.
        write_req  : in  std_logic;                                                              -- 1-cycle pulse
        write_id   : in  std_logic_vector(ID_WIDTH - 1 downto 0);
        write_meta : in  std_logic_vector(META_WIDTH - 1 downto 0);

        -- observability: count of currently-free slots.
        free_count : out std_logic_vector(integer(ceil(log2(real(POOL_SIZE + 1)))) - 1 downto 0)
    );
end entity sos_resource_pool;

architecture rtl of sos_resource_pool is

    -- Derived widths.
    constant CW       : natural := integer(ceil(log2(real(POOL_SIZE + 1))));
    constant ADDR_W   : natural := integer(ceil(log2(real(POOL_SIZE))));

    -- Inner credit counter handshake signals.
    signal cc_acquire_req : std_logic := '0';
    signal cc_acquire_ack : std_logic;
    signal cc_release_req : std_logic := '0';
    signal cc_credits     : std_logic_vector(CW - 1 downto 0);

    -- Free-vector tracker. '1' = slot is free; '0' = slot is currently busy
    -- (allocated). Reset value = all-ones (all slots free) — matches the
    -- credit_counter's INIT_CREDITS=POOL_SIZE reset value. SVA-POOL-4
    -- conservation: popcount(free_vec) == credits at every cycle after reset.
    signal free_vec      : std_logic_vector(POOL_SIZE - 1 downto 0)
                                            := (others => '1');

    -- Priority-encoded lowest-set-bit index of free_vec. Combinational.
    -- Output width is ADDR_W (sufficient for POOL_SIZE entries); zero-extended
    -- into the ID_WIDTH-wide alloc_id port.
    signal alloc_idx     : unsigned(ADDR_W - 1 downto 0);
    signal have_free     : std_logic;

    -- Inner DPRAM port-A signals (write + FWFT read).
    signal dpa_addr      : std_logic_vector(ADDR_W - 1 downto 0);
    signal dpa_wdata     : std_logic_vector(META_WIDTH - 1 downto 0);
    signal dpa_we        : std_logic;
    signal dpa_re        : std_logic := '1';   -- FWFT: always sample
    signal dpa_rdata     : std_logic_vector(META_WIDTH - 1 downto 0);
    signal dpa_full      : std_logic;
    signal dpa_ready     : std_logic;

    -- Inner DPRAM port-B signals (tied off in v1).
    signal dpb_addr      : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal dpb_wdata     : std_logic_vector(META_WIDTH - 1 downto 0) := (others => '0');
    signal dpb_rdata     : std_logic_vector(META_WIDTH - 1 downto 0);
    signal dpb_full      : std_logic;
    signal dpb_ready     : std_logic;

    -- The free-id derived from the input port (resized into ADDR_W).
    signal free_idx      : unsigned(ADDR_W - 1 downto 0);
    -- The write-id resized into ADDR_W.
    signal write_idx     : unsigned(ADDR_W - 1 downto 0);
    -- The read-id resized into ADDR_W.
    signal read_idx      : unsigned(ADDR_W - 1 downto 0);

begin

    ----------------------------------------------------------------------------
    -- Elaboration-time static assertions.
    --   * POOL_SIZE >= 1 enforced by `positive` domain.
    --   * META_WIDTH >= 1 enforced by `positive` domain.
    --   * ID_WIDTH >= ceil(log2(POOL_SIZE)) — the alloc_id output port must
    --     be wide enough to encode any pool index.
    ----------------------------------------------------------------------------
    assert ID_WIDTH >= ADDR_W
        report "sos_resource_pool: ID_WIDTH (" & integer'image(ID_WIDTH)
               & ") must be >= ceil(log2(POOL_SIZE)) = "
               & integer'image(ADDR_W)
        severity failure;

    ----------------------------------------------------------------------------
    -- Lowest-set-bit priority encoder over free_vec.
    --
    -- have_free = OR-reduction of free_vec
    -- alloc_idx = lowest index i such that free_vec(i) = '1'
    --             (defaults to 0 when have_free='0' — caller must check ack).
    ----------------------------------------------------------------------------
    have_free <= '1' when (free_vec /= (free_vec'range => '0')) else '0';

    p_priority_encode : process (free_vec)
        variable found : boolean;
        variable idx_v : unsigned(ADDR_W - 1 downto 0);
    begin
        found := false;
        idx_v := (others => '0');
        for i in 0 to POOL_SIZE - 1 loop
            if not found and free_vec(i) = '1' then
                idx_v := to_unsigned(i, ADDR_W);
                found := true;
            end if;
        end loop;
        alloc_idx <= idx_v;
    end process p_priority_encode;

    ----------------------------------------------------------------------------
    -- alloc/free index conversions. The input ports are ID_WIDTH-wide for
    -- chart-vocabulary parity; internally we use ADDR_W (the DPRAM/free-vec
    -- index width). The high (ID_WIDTH - ADDR_W) bits of free_id / write_id /
    -- read_id are ignored at the L1 boundary (a chart compiler bug if non-zero;
    -- not enforced at the RTL layer — INV-SOS-G covers it).
    ----------------------------------------------------------------------------
    free_idx  <= unsigned(free_id(ADDR_W - 1 downto 0));
    write_idx <= unsigned(write_id(ADDR_W - 1 downto 0));
    read_idx  <= unsigned(read_id(ADDR_W - 1 downto 0));

    ----------------------------------------------------------------------------
    -- Credit counter composition.
    --   INIT_CREDITS = POOL_SIZE, MAX_CREDITS = POOL_SIZE — every slot free
    --   at reset; never more credits than the pool size.
    --
    --   cc_acquire_req fires when alloc_req && have_free; cc_acquire_ack
    --   pulses on the same cycle (combinational ack from §6.6).
    --
    --   cc_release_req fires when free_req && (free_vec[free_idx] == '0')
    --   — i.e. when the freed slot is currently busy. Double-free
    --   (free_vec[free_idx] == '1') is silently dropped — no release,
    --   matching SVA-POOL-2 (no double-free).
    ----------------------------------------------------------------------------
    cc_acquire_req <= alloc_req and have_free;
    cc_release_req <= free_req and (not free_vec(to_integer(free_idx)));

    u_credit : entity work.sos_credit_counter
        generic map (
            INIT_CREDITS => POOL_SIZE,
            MAX_CREDITS  => POOL_SIZE
        )
        port map (
            clk         => clk,
            rst         => rst,
            acquire_req => cc_acquire_req,
            acquire_ack => cc_acquire_ack,
            release_req => cc_release_req,
            credits     => cc_credits
        );

    ----------------------------------------------------------------------------
    -- DPRAM composition. SINGLE_CLOCK, READ_LATENCY=0 (FWFT), RESET_MEM=0
    -- (retained — chart compiler initialises per-slot metadata via write_*
    -- in the boot path). SYNC_STAGES uses the default of 2 (unused in
    -- SINGLE_CLOCK; the parameter is part of the port surface in either
    -- mode per §6.7).
    --
    --   port_a: write + read driven by this service.
    --     - port_a_addr = write_idx on write cycles, read_idx otherwise.
    --     - port_a_we   = write_req (1-cycle pulse).
    --     - port_a_re   = '1' (FWFT — read always observes mem[port_a_addr]).
    --
    --   port_b: tied off in v1 (we=0, re=0, addr=0, wdata=0).
    --
    -- Same-cycle write + read on the same address observes the OLD value
    -- (§6.7 "read-old" semantics). Documented; chart compiler accounts for
    -- it.
    ----------------------------------------------------------------------------
    dpa_addr  <= write_id(ADDR_W - 1 downto 0) when write_req = '1'
                 else read_id(ADDR_W - 1 downto 0);
    dpa_wdata <= write_meta;
    dpa_we    <= write_req;

    u_dpram : entity work.sos_dpram_arb
        generic map (
            DEPTH        => POOL_SIZE,
            WIDTH        => META_WIDTH,
            MODE         => "SINGLE_CLOCK",
            READ_LATENCY => 0,                  -- FWFT
            RESET_MEM    => false,              -- retained — chart inits on boot
            SYNC_STAGES  => 2                   -- unused in SINGLE_CLOCK
        )
        port map (
            clk          => clk,
            rst          => rst,
            clk_a        => clk,                -- tied; unused in SINGLE_CLOCK
            rst_a        => rst,
            clk_b        => clk,
            rst_b        => rst,

            port_a_addr  => dpa_addr,
            port_a_wdata => dpa_wdata,
            port_a_we    => dpa_we,
            port_a_re    => dpa_re,
            port_a_rdata => dpa_rdata,
            port_a_full  => dpa_full,
            port_a_ready => dpa_ready,

            port_b_addr  => dpb_addr,
            port_b_wdata => dpb_wdata,
            port_b_we    => '0',                -- v1: port B reserved
            port_b_re    => '0',
            port_b_rdata => dpb_rdata,
            port_b_full  => dpb_full,
            port_b_ready => dpb_ready
        );

    ----------------------------------------------------------------------------
    -- free_vec update.
    --
    -- Pre-update free_vec gates both the alloc-bit-clear and the free-bit-set,
    -- mirroring sos_credit_counter's "use pre-update credits for both gates"
    -- shape. Same-cycle alloc + free on the same id resolves to bit=0 (busy)
    -- — see header "Same-cycle alloc + free behaviour" note.
    ----------------------------------------------------------------------------
    p_free_vec : process (clk)
        variable v : std_logic_vector(POOL_SIZE - 1 downto 0);
    begin
        if rising_edge(clk) then
            if rst = '1' then
                free_vec <= (others => '1');    -- all slots free at reset
            else
                v := free_vec;

                -- Free first (set the bit) — if it's a valid free (slot was
                -- busy). Double-free (slot already free) is silently dropped.
                if free_req = '1' and free_vec(to_integer(free_idx)) = '0' then
                    v(to_integer(free_idx)) := '1';
                end if;

                -- Alloc second (clear the bit) — overrides any same-cycle
                -- free-of-the-just-allocated-slot. Only when have_free='1'
                -- and alloc_req='1'.
                if alloc_req = '1' and have_free = '1' then
                    v(to_integer(alloc_idx)) := '0';
                end if;

                free_vec <= v;
            end if;
        end if;
    end process p_free_vec;

    ----------------------------------------------------------------------------
    -- Outputs.
    --   alloc_ack = cc_acquire_ack (pulse from the inner credit counter).
    --   alloc_id  = zero-extended ADDR_W-wide alloc_idx into ID_WIDTH bits.
    --   read_meta = combinational FWFT read off port_a_rdata.
    --   free_count = cc_credits (popcount(free_vec) by SVA-POOL-4).
    ----------------------------------------------------------------------------
    alloc_ack  <= cc_acquire_ack;

    g_alloc_id_width : if ID_WIDTH > ADDR_W generate
        alloc_id <= std_logic_vector(resize(alloc_idx, ID_WIDTH));
    else generate
        alloc_id <= std_logic_vector(alloc_idx);
    end generate g_alloc_id_width;

    read_meta  <= dpa_rdata;
    free_count <= cc_credits;

end architecture rtl;
