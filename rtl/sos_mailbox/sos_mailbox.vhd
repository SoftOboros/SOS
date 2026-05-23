-- =============================================================================
-- sos_mailbox.vhd  --  L1 service: priority-tiered message mailbox
--                     (portable VHDL-2008)
--
-- @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.1 (sos_mailbox contract)
--       docs/concepts/SOS-08-B-CONCEPTS.md §5  (frozen decisions inherited)
--       docs/concepts/SOS-08-B-CONCEPTS.md §7  (cross-service invariants
--                                              INV-S-HDL-B-1..5)
--       docs/concepts/SOS-08-B-CONCEPTS.md §15 2026-05-23 ratification entry
--                                              (PCDN-SOS-08-B-001 resolved
--                                              NUM_PRIO default 8;
--                                              PCDN-SOS-08-B-006 resolved
--                                              level-sensitive irq_non_empty)
--       docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (sos_fifo_sync L0 contract;
--                                                composed by instantiation)
--       docs/concepts/SOS-08-A-CONCEPTS.md §6.4 (sos_arbiter_priority L0
--                                                contract; composed by
--                                                instantiation)
--       docs/concepts/SOS-08-A-CONCEPTS.md §15  2026-05-23 wave-1 entry
--                                              (READ_LATENCY / RESET_MEM /
--                                              GRANT_LATENCY_CYCLES generics)
--       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants
--                                              INV-SOS-A..H)
--       docs/concepts/SOS-08-CONCEPTS.md   §7  (cross-sub-phase invariants
--                                              INV-S-HDL-1..5)
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
--   INV-S-HDL-3  cross-domain isolation (N/A -- single-clock variant)
--   INV-S-HDL-4  cooperative-only at v1
--   INV-S-HDL-5  vector-to-chart traceability for HDL
--
-- L1 cross-service invariants (SOS-08-B §7, cited):
--   INV-S-HDL-B-1  vocabulary mirror discipline
--   INV-S-HDL-B-2  L0 non-modification (composes sos_fifo_sync +
--                  sos_arbiter_priority by instantiation)
--   INV-S-HDL-B-3  service-level SVA on every L1 instance
--   INV-S-HDL-B-4  vendor-IP pass-through
--   INV-S-HDL-B-5  chart-vocabulary failure rendering
--
-- L0 primitive contracts consumed (by instantiation, per INV-S-HDL-B-2):
--   sos_fifo_sync       (SOS-08-A §6.2)
--   sos_arbiter_priority (SOS-08-A §6.4)
--
-- Behavioural summary (per SOS-08-B §6.1):
--   * Producer Slave AXI-Stream + s_axis_tprio lane selector.
--   * Consumer Master AXI-Stream + m_axis_tprio lane reporter.
--   * NUM_PRIO parallel sos_fifo_sync instances, one per lane.
--   * sos_arbiter_priority arbitrates across lane ~empty signals (lane index
--     == priority value; higher index wins per §6.4 convention).
--   * irq_non_empty level-sensitive (PCDN-SOS-08-B-006).
--
-- Design notes (NOT spec re-derivation; flagged for the agent report):
--   * Lane priority convention: higher s_axis_tprio value selects a
--     higher-priority lane.
--   * Spec §6.1 prints the sideband width as [$clog2(NUM_PRIO):0] (one bit
--     wider than the canonical -1:0 form).  The task brief explicitly fixes
--     [$clog2(NUM_PRIO)-1:0]; this file follows the task brief.  AMBIGUITY
--     flagged for the agent report.
--   * NUM_PRIO = 1 collapses the priority sideband to 0 bits; we clamp the
--     port width to >= 1 via PRIO_W_EFF.
--   * Cross-clock variant (CROSS_CLK = 1, sos_fifo_async swap) is out of
--     scope for this implementation per the task brief.
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;
  use ieee.math_real.all;

package sos_mailbox_pkg is
  -- ceil(log2(n)) clamped to >= 1 so the NUM_PRIO=1 degenerate case still
  -- produces a 1-bit-wide sideband port.
  function clog2_at_least_one (n : positive) return positive;
end package sos_mailbox_pkg;

package body sos_mailbox_pkg is
  function clog2_at_least_one (n : positive) return positive is
    variable v : natural  := n - 1;
    variable r : positive := 1;
  begin
    if n <= 1 then
      return 1;
    end if;
    r := 0;
    while v > 0 loop
      v := v / 2;
      r := r + 1;
    end loop;
    if r < 1 then
      r := 1;
    end if;
    return r;
  end function;
end package body sos_mailbox_pkg;

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;
  use ieee.math_real.all;

library work;
  use work.sos_mailbox_pkg.all;

entity sos_mailbox is
  generic (
    -- Per PCDN-SOS-08-B-001 (resolved 2026-05-23): default 8 priority lanes.
    -- The ONLY default on this module surface -- mirrors the INV-S-HDL-A-5
    -- named-exception convention from SOS-08-A.
    NUM_PRIO              : positive := 8;

    -- Mandatory: no default (INV-S-HDL-A-5, inherited from sos_fifo_sync).
    DEPTH                 : positive;
    WIDTH                 : positive;
    READ_LATENCY          : natural;
    RESET_MEM             : boolean;

    -- Mandatory: no default (INV-S-HDL-A-5, inherited from
    -- sos_arbiter_priority).
    AGING_ENABLE          : integer;
    AGING_THRESHOLD       : positive;

    -- PCDN-A-arbiter-GRANT_LATENCY_CYCLES named-exception default.
    GRANT_LATENCY_CYCLES  : integer := 1
  );
  port (
    -- Clock + sync active-high reset (INV-S-HDL-A-1 / PCDN-A-003).
    clk            : in  std_logic;
    rst            : in  std_logic;

    -- Slave AXI-Stream ingress.
    s_axis_tdata   : in  std_logic_vector(WIDTH - 1 downto 0);
    s_axis_tprio   : in  std_logic_vector(clog2_at_least_one(NUM_PRIO) - 1 downto 0);
    s_axis_tvalid  : in  std_logic;
    s_axis_tready  : out std_logic;

    -- Master AXI-Stream egress.
    m_axis_tdata   : out std_logic_vector(WIDTH - 1 downto 0);
    m_axis_tprio   : out std_logic_vector(clog2_at_least_one(NUM_PRIO) - 1 downto 0);
    m_axis_tvalid  : out std_logic;
    m_axis_tready  : in  std_logic;

    -- Level-sensitive IRQ (PCDN-SOS-08-B-006).
    irq_non_empty  : out std_logic
  );
end entity sos_mailbox;

architecture rtl of sos_mailbox is

  constant PRIO_W_EFF : positive := clog2_at_least_one(NUM_PRIO);
  -- PRIORITY_BITS for the arbiter.  Same form -- clamped to >= 1 so the
  -- NUM_PRIO=1 case has a valid (if unused) bus shape.
  constant PBITS      : positive := clog2_at_least_one(NUM_PRIO);
  constant CNT_W      : positive := positive(integer(ceil(log2(real(DEPTH + 1)))));

  -- Per-lane FIFO surfaces.
  signal lane_s_tvalid : std_logic_vector(NUM_PRIO - 1 downto 0);
  signal lane_s_tready : std_logic_vector(NUM_PRIO - 1 downto 0);
  signal lane_full     : std_logic_vector(NUM_PRIO - 1 downto 0);
  signal lane_empty    : std_logic_vector(NUM_PRIO - 1 downto 0);
  signal lane_m_tvalid : std_logic_vector(NUM_PRIO - 1 downto 0);
  signal lane_m_tready : std_logic_vector(NUM_PRIO - 1 downto 0);

  type   data_array_t  is array (0 to NUM_PRIO - 1)
                          of std_logic_vector(WIDTH - 1 downto 0);
  type   count_array_t is array (0 to NUM_PRIO - 1)
                          of std_logic_vector(CNT_W - 1 downto 0);
  signal lane_m_tdata  : data_array_t;
  signal lane_count    : count_array_t;

  -- Arbiter surfaces.
  signal arb_req            : std_logic_vector(NUM_PRIO - 1 downto 0);
  signal arb_priority_in    : std_logic_vector(NUM_PRIO * PBITS - 1 downto 0);
  signal arb_grant          : std_logic_vector(NUM_PRIO - 1 downto 0);
  signal arb_last_winner_id : std_logic_vector(
      positive(integer(ceil(log2(real(NUM_PRIO + 1))))) - 1 downto 0);

  -- Ingress lane-select one-hot.
  signal s_tprio_one_hot : std_logic_vector(NUM_PRIO - 1 downto 0);

  function any_set (v : std_logic_vector) return std_logic is
    variable r : std_logic := '0';
  begin
    for i in v'range loop
      r := r or v(i);
    end loop;
    return r;
  end function;

  function none_set (v : std_logic_vector) return std_logic is
  begin
    return not any_set(v);
  end function;

begin

  ----------------------------------------------------------------------------
  -- Elaboration-time validation.
  ----------------------------------------------------------------------------
  assert NUM_PRIO >= 1
    report "sos_mailbox: NUM_PRIO must be >= 1; got "
           & integer'image(NUM_PRIO)
    severity failure;
  assert DEPTH >= 1
    report "sos_mailbox: DEPTH must be >= 1; got "
           & integer'image(DEPTH)
    severity failure;
  assert WIDTH >= 1
    report "sos_mailbox: WIDTH must be >= 1; got "
           & integer'image(WIDTH)
    severity failure;

  ----------------------------------------------------------------------------
  -- Per-lane FIFO instances + ingress decode.
  ----------------------------------------------------------------------------
  g_lane : for i in 0 to NUM_PRIO - 1 generate

    -- Ingress decode: only lane == s_axis_tprio sees tvalid.
    lane_s_tvalid(i) <=
      s_axis_tvalid
      when unsigned(s_axis_tprio) = to_unsigned(i, PRIO_W_EFF)
      else '0';

    u_lane : entity work.sos_fifo_sync
      generic map (
        DEPTH        => DEPTH,
        WIDTH        => WIDTH,
        READ_LATENCY => READ_LATENCY,
        RESET_MEM    => RESET_MEM
      )
      port map (
        clk            => clk,
        rst            => rst,

        s_axis_tdata   => s_axis_tdata,
        s_axis_tvalid  => lane_s_tvalid(i),
        s_axis_tready  => lane_s_tready(i),

        m_axis_tdata   => lane_m_tdata(i),
        m_axis_tvalid  => lane_m_tvalid(i),
        m_axis_tready  => lane_m_tready(i),

        full           => lane_full(i),
        empty          => lane_empty(i),
        count          => lane_count(i)
      );

  end generate g_lane;

  ----------------------------------------------------------------------------
  -- Ingress lane-select one-hot decode + producer-side tready.
  ----------------------------------------------------------------------------
  process (s_axis_tprio)
    variable t : std_logic_vector(NUM_PRIO - 1 downto 0);
  begin
    t := (others => '0');
    for i in 0 to NUM_PRIO - 1 loop
      if to_unsigned(i, PRIO_W_EFF) = unsigned(s_axis_tprio) then
        t(i) := '1';
      end if;
    end loop;
    s_tprio_one_hot <= t;
  end process;

  -- s_axis_tready follows the targeted lane's tready.  When tprio is
  -- out of range (no bit set in the one-hot decode), tready is held low
  -- so the producer stalls until it corrects the sideband.
  process (s_tprio_one_hot, lane_s_tready)
    variable any  : std_logic := '0';
    variable val  : std_logic := '0';
  begin
    any := '0';
    val := '0';
    for i in 0 to NUM_PRIO - 1 loop
      if s_tprio_one_hot(i) = '1' then
        any := '1';
        val := val or lane_s_tready(i);
      end if;
    end loop;
    if any = '1' then
      s_axis_tready <= val;
    else
      s_axis_tready <= '0';
    end if;
  end process;

  ----------------------------------------------------------------------------
  -- Arbiter input assembly: req[i] = lane_m_tvalid[i]; priority[i] = i.
  ----------------------------------------------------------------------------
  g_arb_in : for i in 0 to NUM_PRIO - 1 generate
    arb_req(i) <= lane_m_tvalid(i);
    arb_priority_in((i + 1) * PBITS - 1 downto i * PBITS) <=
      std_logic_vector(to_unsigned(i, PBITS));
  end generate g_arb_in;

  ----------------------------------------------------------------------------
  -- Single-lane bypass vs multi-lane arbiter.  sos_arbiter_priority requires
  -- N_REQS >= 2 at elaboration; the NUM_PRIO=1 case bypasses the arbiter.
  ----------------------------------------------------------------------------
  g_single_lane : if NUM_PRIO = 1 generate
    arb_grant          <= lane_m_tvalid;
    arb_last_winner_id <= (others => '0');
  end generate g_single_lane;

  g_multi_lane : if NUM_PRIO > 1 generate
    u_arb : entity work.sos_arbiter_priority
      generic map (
        N_REQS               => NUM_PRIO,
        PRIORITY_BITS        => PBITS,
        AGING_ENABLE         => AGING_ENABLE,
        AGING_THRESHOLD      => AGING_THRESHOLD,
        GRANT_LATENCY_CYCLES => GRANT_LATENCY_CYCLES
      )
      port map (
        clk            => clk,
        rst            => rst,
        req            => arb_req,
        priority_in    => arb_priority_in,
        grant          => arb_grant,
        last_winner_id => arb_last_winner_id
      );
  end generate g_multi_lane;

  ----------------------------------------------------------------------------
  -- Egress mux + per-lane tready gating + irq_non_empty.
  ----------------------------------------------------------------------------
  process (arb_grant, lane_m_tdata, lane_m_tvalid)
    variable d : std_logic_vector(WIDTH - 1 downto 0);
    variable p : std_logic_vector(PRIO_W_EFF - 1 downto 0);
    variable v : std_logic;
  begin
    d := (others => '0');
    p := (others => '0');
    v := '0';
    for i in 0 to NUM_PRIO - 1 loop
      if arb_grant(i) = '1' then
        d := lane_m_tdata(i);
        p := std_logic_vector(to_unsigned(i, PRIO_W_EFF));
        v := lane_m_tvalid(i);
      end if;
    end loop;
    m_axis_tdata  <= d;
    m_axis_tprio  <= p;
    m_axis_tvalid <= v;
  end process;

  g_egress_ready : for i in 0 to NUM_PRIO - 1 generate
    lane_m_tready(i) <= arb_grant(i) and m_axis_tready;
  end generate g_egress_ready;

  irq_non_empty <= any_set(not lane_empty);

end architecture rtl;
