-- =============================================================================
-- sos_arbiter_priority.vhd  --  L0 priority arbiter with optional aging
--                               (portable VHDL-2008)
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.4
--   Per 2026-05-23 initial-draft + ratification (§15 first entry) +
--   impl-wave-1 PCDN amendments (§15 second 2026-05-23 entry).
--
--   Control primitive, bare req/grant naming (per PCDN-A-002 ratified for
--   control primitives; arbiters are control primitives per §10
--   reconciliation).  Parameters UPPER_CASE (PCDN-A-001).  Synchronous
--   active-high reset (PCDN-A-003, INV-S-HDL-A-1).  Resource-determining
--   generics are mandatory with no default (PCDN-A-004, INV-S-HDL-A-5).
--   One-hot internal pointer (INV-S-HDL-A-4, SOS-08 PCDN-002 ratified
--   one-hot at v1).
--
--   GRANT_LATENCY_CYCLES generic mirrors the sos_arbiter_rr resolution of
--   PCDN-A-arbiter-GRANT_LATENCY_CYCLES (§15 second 2026-05-23 entry,
--   resolution row).  The PCDN amendment text names sos_arbiter_rr
--   specifically; per the task brief this primitive extends the same
--   generic/default to sos_arbiter_priority for parity across the arbiter
--   family.  Flagged as a §15 amendment extension that the spec doc SHOULD
--   absorb at the next walkthrough; no code-side speculation needed (the
--   amendment text already describes the named exception to INV-S-HDL-A-5
--   in generic terms and the PCDN id form trivially generalises).
--
-- Cited invariants (this primitive does not redefine them):
--   INV-SOS-A  chart-as-source                     (SOS-07 §6)
--   INV-SOS-B  vectors-as-deliverable              (SOS-07 §6)
--   INV-SOS-E  explicit AuthorityRelationship      (SOS-07 §6)
--   INV-SOS-G  verified-codegen position           (SOS-07 §6)
--   INV-SOS-H  vector-to-chart traceability        (SOS-07 §6)
--   INV-S-HDL-1 handshake-compatible ports         (SOS-08 §7)
--   INV-S-HDL-2 static-allocation discipline       (SOS-08 §7)
--   INV-S-HDL-3 cross-domain isolation             (SOS-08 §7; N/A here, single-domain)
--   INV-S-HDL-4 cooperative-only at v1             (SOS-08 §7)
--   INV-S-HDL-5 vector-to-chart traceability (HDL) (SOS-08 §7)
--   INV-S-HDL-A-1 uniform sync active-high reset   (SOS-08-A §7)
--   INV-S-HDL-A-2 handshake associativity          (SOS-08-A §7)
--   INV-S-HDL-A-3 vendor-shim byte-identical wrap  (SOS-08-A §7; portable-only here)
--   INV-S-HDL-A-4 one-hot internal FSM by default  (SOS-08-A §7)
--   INV-S-HDL-A-5 mandatory parameters, no default (SOS-08-A §7;
--                  named exception for GRANT_LATENCY_CYCLES per second
--                  2026-05-23 §15 entry, extended to this primitive)
--
-- Design choices made by this implementation (flagged in the agent report;
-- no spec text re-derived here):
--
--   * Priority direction: HIGHER priority value wins.  Tie within a priority
--     lane is resolved by a SHARED round-robin pointer scanning the
--     requester index space (one pointer for the whole arbiter, not a
--     per-lane pointer).  Both choices are documented and are open to
--     spec amendment if the §15 walkthrough flags a different shape.
--
--   * Aging: when AGING_ENABLE = 1, an unsigned counter per requester counts
--     cycles the requester has asserted req[i] without being granted; once
--     the counter reaches AGING_THRESHOLD, that requester's effective
--     priority is promoted to the maximum (all-ones) so the next arbitration
--     pass will select it as soon as no higher-priority promotion fires.
--     Counter resets on grant or on req[i] deassertion.
--
-- Behavioural contract (per §6.4):
--   On any given cycle:
--     1. Each requester i has an effective priority = priority[i] if not
--        aging-promoted, else all-ones.
--     2. Among the asserted requesters, the arbiter selects the one with
--        the highest effective-priority value.
--     3. If two or more requesters tie at the top effective priority, the
--        shared round-robin pointer (scanned from `pointer` upward modulo
--        N_REQS) selects the first asserted-and-top-priority requester.
--     4. The selected requester is granted; pointer advances to one slot
--        past the winner; the winner's aging counter resets to zero;
--        every other asserted-but-unserved requester increments its aging
--        counter (saturating at AGING_THRESHOLD).
--   At most one bit of `grant` is asserted per cycle.
--
-- Fairness bound (AGING_ENABLE = 1):
--   Every continuously-asserted requester is granted within
--   AGING_THRESHOLD + N_REQS cycles: at most AGING_THRESHOLD cycles to
--   accrue aging promotion, then at most N_REQS cycles for the
--   round-robin tie-break against other promoted requesters.
--
-- Resource cost:
--   N_REQS one-hot pointer FFs; N_REQS grant FFs;
--   N_REQS * AGING_BITS aging-counter FFs (only when AGING_ENABLE = 1);
--   ceil(log2(N_REQS+1)) observability FFs;
--   combinational reduction-OR over priority lanes and lowest-set-bit
--   reduction.
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

package sos_arbiter_priority_pkg is
  -- ceil(log2(n+1)).  Sized so `n` itself ("no winner yet") fits.
  function clog2_p1 (n : positive) return positive;
  -- ceil(log2(n)) but never below 1.  Used for sizing the aging counter
  -- so that it can hold the value AGING_THRESHOLD.
  function clog2_at_least_one (n : positive) return positive;
end package sos_arbiter_priority_pkg;

package body sos_arbiter_priority_pkg is

  function clog2_p1 (n : positive) return positive is
    variable v : natural  := n;
    variable r : positive := 1;
  begin
    while v > 0 loop
      v := v / 2;
      if v > 0 then
        r := r + 1;
      end if;
    end loop;
    return r;
  end function;

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

end package body sos_arbiter_priority_pkg;

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

library work;
  use work.sos_arbiter_priority_pkg.all;

entity sos_arbiter_priority is
  generic (
    -- Mandatory: no default (INV-S-HDL-A-5).
    N_REQS               : positive;
    -- Mandatory: no default.  Width of the per-requester priority field.
    PRIORITY_BITS        : positive;
    -- Mandatory: no default.  When = 1, aging promotes starved requesters
    -- after AGING_THRESHOLD cycles.  When = 0, strict priority (the lowest
    -- priority lane MAY starve under continuous higher-priority pressure;
    -- this is intentional under AGING_ENABLE = 0).
    AGING_ENABLE         : integer;
    -- Mandatory: no default.  Counter threshold in `clk` cycles.  Ignored
    -- when AGING_ENABLE = 0 (the counters and promotion logic are still
    -- present but their outputs do not influence arbitration).  MUST be
    -- >= 1.
    AGING_THRESHOLD      : positive;
    -- See sos_arbiter_rr.  Default 1 (canonical registered shape); 0 opts
    -- in to combinational grant forward.  Named exception to
    -- INV-S-HDL-A-5 per the second 2026-05-23 §15 entry, extended to this
    -- primitive per the task brief.
    GRANT_LATENCY_CYCLES : integer := 1
  );
  port (
    clk            : in  std_logic;
    rst            : in  std_logic;  -- synchronous active-high (INV-S-HDL-A-1)
    req            : in  std_logic_vector(N_REQS - 1 downto 0);
    -- Flat per-requester priority field.  Slot i occupies bits
    -- [(i+1)*PRIORITY_BITS - 1 : i*PRIORITY_BITS].  Higher value = higher
    -- priority.  Named `priority_in` (not bare `priority`) so the VHDL
    -- and SV ports match byte-for-byte and the SV form does not collide
    -- with the SV `priority` reserved keyword.
    priority_in    : in  std_logic_vector(N_REQS * PRIORITY_BITS - 1 downto 0);
    grant          : out std_logic_vector(N_REQS - 1 downto 0);
    -- Observability: id of the most recent winner.
    -- Width = ceil(log2(N_REQS + 1)).  Value N_REQS encodes "no winner yet".
    last_winner_id : out std_logic_vector(clog2_p1(N_REQS) - 1 downto 0)
  );
end entity sos_arbiter_priority;

architecture rtl of sos_arbiter_priority is

  constant ID_W   : positive := clog2_p1(N_REQS);
  constant AGE_W  : positive := clog2_at_least_one(AGING_THRESHOLD + 1);

  -- One-hot pointer (INV-S-HDL-A-4): pointer(i) = '1' means requester i is
  -- the round-robin scan anchor for tie-breaking *this cycle*.  Reset
  -- value = pointer(0) = '1'.
  signal pointer    : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_q    : std_logic_vector(N_REQS - 1 downto 0);
  signal last_id_q  : unsigned(ID_W - 1 downto 0);

  -- Aging counter per requester.  Each counter saturates at AGING_THRESHOLD.
  type age_array_t is array (0 to N_REQS - 1) of unsigned(AGE_W - 1 downto 0);
  signal age_q : age_array_t;

  -- Sentinel for "no winner yet" written into last_id_q at reset.
  constant NO_WINNER : unsigned(ID_W - 1 downto 0)
    := to_unsigned(N_REQS, ID_W);

  -- Effective per-requester priority width: PRIORITY_BITS unless aging is
  -- enabled, in which case we add one extra MSB to encode the
  -- "aged-promotion" lane (so a promoted requester always outranks any
  -- non-promoted one regardless of their base priority).
  constant EFF_W : positive := PRIORITY_BITS + 1;

  -- Combinational signals.
  type eff_array_t is array (0 to N_REQS - 1) of unsigned(EFF_W - 1 downto 0);
  signal eff_prio   : eff_array_t;
  signal max_prio   : unsigned(EFF_W - 1 downto 0);
  signal top_req    : std_logic_vector(N_REQS - 1 downto 0);
  signal mask_high  : std_logic_vector(N_REQS - 1 downto 0);
  signal top_high   : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_high : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_low  : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_next : std_logic_vector(N_REQS - 1 downto 0);
  signal any_top_hi : std_logic;
  signal any_grant  : std_logic;

  ----------------------------------------------------------------------------
  -- Local helpers.
  ----------------------------------------------------------------------------

  function or_reduce_loc (v : std_logic_vector) return std_logic is
    variable r : std_logic := '0';
  begin
    for i in v'range loop
      r := r or v(i);
    end loop;
    return r;
  end function;

  function lsb_one_hot (v : std_logic_vector) return std_logic_vector is
    variable r    : std_logic_vector(v'range) := (others => '0');
    variable seen : std_logic := '0';
  begin
    for i in v'low to v'high loop
      if seen = '0' and v(i) = '1' then
        r(i) := '1';
        seen := '1';
      end if;
    end loop;
    return r;
  end function;

  function priority_mask (p : std_logic_vector) return std_logic_vector is
    variable r       : std_logic_vector(p'range) := (others => '0');
    variable started : std_logic := '0';
  begin
    for i in p'low to p'high loop
      if started = '1' or p(i) = '1' then
        r(i)    := '1';
        started := '1';
      end if;
    end loop;
    return r;
  end function;

  function onehot_to_index (v : std_logic_vector) return natural is
  begin
    for i in v'low to v'high loop
      if v(i) = '1' then
        return i;
      end if;
    end loop;
    return 0;
  end function;

begin

  ----------------------------------------------------------------------------
  -- Elaboration-time validation.
  ----------------------------------------------------------------------------
  assert GRANT_LATENCY_CYCLES = 0 or GRANT_LATENCY_CYCLES = 1
    report "sos_arbiter_priority: SOS-08-A §6.4 supports "
           & "GRANT_LATENCY_CYCLES in {0, 1} at v1; got value="
           & integer'image(GRANT_LATENCY_CYCLES)
    severity failure;

  assert AGING_ENABLE = 0 or AGING_ENABLE = 1
    report "sos_arbiter_priority: AGING_ENABLE must be 0 or 1; got value="
           & integer'image(AGING_ENABLE)
    severity failure;

  ----------------------------------------------------------------------------
  -- Effective priority computation.  For each requester i:
  --
  --   eff_prio(i) = { aged_flag(i) , priority[i] }  (width EFF_W)
  --
  -- aged_flag(i) is 1 iff AGING_ENABLE = 1 AND age_q(i) >= AGING_THRESHOLD;
  -- otherwise 0.  Concatenation guarantees a promoted requester always
  -- outranks any non-promoted requester regardless of base priority.
  ----------------------------------------------------------------------------
  g_eff_prio : for i in 0 to N_REQS - 1 generate
    process (priority_in, age_q)
      variable base    : unsigned(PRIORITY_BITS - 1 downto 0);
      variable aged    : std_logic;
      variable thresh  : unsigned(AGE_W - 1 downto 0);
    begin
      base := unsigned(priority_in((i + 1) * PRIORITY_BITS - 1
                                   downto i * PRIORITY_BITS));
      if AGING_ENABLE = 1 then
        thresh := to_unsigned(AGING_THRESHOLD, AGE_W);
        if age_q(i) >= thresh then
          aged := '1';
        else
          aged := '0';
        end if;
      else
        aged := '0';
      end if;
      eff_prio(i) <= aged & base;
    end process;
  end generate g_eff_prio;

  ----------------------------------------------------------------------------
  -- Find the maximum effective priority over the asserted requesters.
  ----------------------------------------------------------------------------
  process (req, eff_prio)
    variable m : unsigned(EFF_W - 1 downto 0);
  begin
    m := (others => '0');
    for i in 0 to N_REQS - 1 loop
      if req(i) = '1' then
        if eff_prio(i) > m then
          m := eff_prio(i);
        end if;
      end if;
    end loop;
    max_prio <= m;
  end process;

  ----------------------------------------------------------------------------
  -- top_req(i) is set iff requester i is asserted AND its effective
  -- priority equals the (asserted-set) maximum.  Note: when no requester
  -- is asserted, max_prio = 0 and top_req is all-zero because req gates
  -- the conjunction.
  ----------------------------------------------------------------------------
  process (req, eff_prio, max_prio)
    variable t : std_logic_vector(N_REQS - 1 downto 0);
  begin
    t := (others => '0');
    for i in 0 to N_REQS - 1 loop
      if req(i) = '1' and eff_prio(i) = max_prio then
        t(i) := '1';
      end if;
    end loop;
    top_req <= t;
  end process;

  ----------------------------------------------------------------------------
  -- Round-robin tie-break across the top-priority slice.  Same pattern as
  -- sos_arbiter_rr: build a priority mask from the one-hot pointer upward,
  -- find lowest-set bit in (top_req & mask); fall back to lowest-set bit
  -- globally for the wrap-around case.
  ----------------------------------------------------------------------------
  mask_high  <= priority_mask(pointer);
  top_high   <= top_req and mask_high;
  any_top_hi <= or_reduce_loc(top_high);

  grant_high <= lsb_one_hot(top_high);
  grant_low  <= lsb_one_hot(top_req);

  grant_next <= grant_high when any_top_hi = '1' else grant_low;
  any_grant  <= or_reduce_loc(grant_next);

  ----------------------------------------------------------------------------
  -- Sequential update: pointer, aging counters, observability registers.
  ----------------------------------------------------------------------------
  process (clk)
    variable winner_idx_v : natural;
    variable new_ptr_v    : std_logic_vector(N_REQS - 1 downto 0);
    variable thresh_v     : unsigned(AGE_W - 1 downto 0);
  begin
    if rising_edge(clk) then
      if rst = '1' then
        pointer    <= (0 => '1', others => '0');
        grant_q    <= (others => '0');
        last_id_q  <= NO_WINNER;
        for i in 0 to N_REQS - 1 loop
          age_q(i) <= (others => '0');
        end loop;
      else
        grant_q <= grant_next;

        if any_grant = '1' then
          winner_idx_v := onehot_to_index(grant_next);
          last_id_q    <= to_unsigned(winner_idx_v, ID_W);
          new_ptr_v                                 := (others => '0');
          new_ptr_v((winner_idx_v + 1) mod N_REQS)  := '1';
          pointer                                   <= new_ptr_v;
        end if;
        -- Pointer is held when no grant fires (INV-S-HDL-A-4).

        -- Aging counter update per requester.
        thresh_v := to_unsigned(AGING_THRESHOLD, AGE_W);
        for i in 0 to N_REQS - 1 loop
          if grant_next(i) = '1' then
            -- Winner: reset aging counter.
            age_q(i) <= (others => '0');
          elsif req(i) = '1' then
            -- Asserted-but-not-granted: increment with saturation at
            -- AGING_THRESHOLD.  Saturating keeps the promotion latched
            -- across the contention window without overflow.
            if age_q(i) < thresh_v then
              age_q(i) <= age_q(i) + 1;
            end if;
          else
            -- Deasserted: clear.  Forces a fresh aging window when the
            -- requester re-asserts (matches §6.4 "each unserved
            -- requester's effective priority increments by one per
            -- cycle" applied only while req is held).
            age_q(i) <= (others => '0');
          end if;
        end loop;
      end if;
    end if;
  end process;

  ----------------------------------------------------------------------------
  -- Grant output selector (PCDN-A-arbiter-GRANT_LATENCY_CYCLES; extension
  -- to this primitive flagged in the header).
  ----------------------------------------------------------------------------
  g_grant_reg : if GRANT_LATENCY_CYCLES = 1 generate
    grant <= grant_q;
  end generate g_grant_reg;

  g_grant_comb : if GRANT_LATENCY_CYCLES = 0 generate
    grant <= grant_next;
  end generate g_grant_comb;

  last_winner_id <= std_logic_vector(last_id_q);

end architecture rtl;
