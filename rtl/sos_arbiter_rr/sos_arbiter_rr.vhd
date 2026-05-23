-- =============================================================================
-- sos_arbiter_rr.vhd  --  L0 round-robin arbiter (portable VHDL-2008)
--
-- @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.3
--   Per 2026-05-23 ratification (§15): control primitive, bare req/grant
--   naming (PCDN-A-002 ratified resolution applied to arbiters per task scope;
--   the per-§6.3 contract uses `req` / `grant` as a 1-cycle request +
--   1-cycle grant pulse pair).  Parameters UPPER_CASE (PCDN-A-001).
--   Synchronous active-high reset (PCDN-A-003, INV-S-HDL-A-1).
--   Mandatory N_REQS, no default (PCDN-A-004, INV-S-HDL-A-5).
--   One-hot internal pointer (INV-S-HDL-A-4, SOS-08 PCDN-002 ratified
--   one-hot at v1).
--
--   Per PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23: the
--   primitive exposes a `GRANT_LATENCY_CYCLES` generic (0 or 1) controlling
--   the request->grant timing. =1 (the canonical v1 shape) registers the
--   grant; =0 forwards the combinational priority-mask result on the same
--   cycle.  This is the SINGLE generic in the L0 set that ships with a
--   default — the canonical registered form (=1) is the safe shape and the
--   v0-style combinational form is opt-in.  Any other value is unsupported
--   at v1.
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
--   INV-S-HDL-A-5 mandatory parameters, no default (SOS-08-A §7)
--
-- Behavioural contract:
--   The pointer is a one-hot vector naming the *next* round-robin priority
--   anchor.  On any given cycle, the arbiter scans requesters starting at
--   the pointer position, wrapping modulo N_REQS, and grants the first
--   asserted requester it finds.  At most one bit of `grant` is asserted
--   per cycle.  On a grant, the pointer advances one slot past the winner,
--   ensuring a starvation bound of N_REQS cycles per continuously-asserted
--   requester.
--
-- Fairness bound:  any requester continuously asserted is granted within
-- N_REQS cycles of contention.
--
-- Resource cost:  N_REQS one-hot pointer FFs, N_REQS grant FFs,
-- ceil(log2(N_REQS+1)) observability FFs, combinational priority-mask
-- + lowest-set-bit reduction.
-- =============================================================================

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

package sos_arbiter_rr_pkg is
  -- ceil(log2(n+1)).  Sized so `n` itself ("no winner yet") fits.
  function clog2_p1 (n : positive) return positive;
end package sos_arbiter_rr_pkg;

package body sos_arbiter_rr_pkg is
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
    -- r = ceil(log2(n+1)) for n >= 1.
    return r;
  end function;
end package body sos_arbiter_rr_pkg;

library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

library work;
  use work.sos_arbiter_rr_pkg.all;

entity sos_arbiter_rr is
  generic (
    -- Mandatory: no default (INV-S-HDL-A-5).
    N_REQS               : positive;
    -- Grant timing: 0 = combinational forward of the priority-mask result on
    -- the same cycle req is asserted; 1 = registered grant (canonical v1
    -- shape; 1-cycle latency).  This is the one L0 generic that carries a
    -- default (PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23): the
    -- registered shape (=1) is the safe canonical primitive form and the
    -- combinational v0 form is opt-in.  Values other than {0, 1} are
    -- unsupported at v1.
    GRANT_LATENCY_CYCLES : integer := 1
  );
  port (
    clk            : in  std_logic;
    rst            : in  std_logic;  -- synchronous active-high (INV-S-HDL-A-1)
    req            : in  std_logic_vector(N_REQS - 1 downto 0);
    grant          : out std_logic_vector(N_REQS - 1 downto 0);
    -- Observability: id of the most recent winner.
    -- Width = ceil(log2(N_REQS + 1)).  Value N_REQS encodes "no winner yet".
    last_winner_id : out std_logic_vector(clog2_p1(N_REQS) - 1 downto 0)
  );
end entity sos_arbiter_rr;

architecture rtl of sos_arbiter_rr is

  constant ID_W : positive := clog2_p1(N_REQS);

  -- One-hot pointer (INV-S-HDL-A-4): pointer(i) = '1' means requester i
  -- holds the highest priority *this cycle*.  Reset value = pointer(0)='1'.
  signal pointer    : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_q    : std_logic_vector(N_REQS - 1 downto 0);
  signal last_id_q  : unsigned(ID_W - 1 downto 0);

  -- Sentinel for "no winner yet" written into last_id_q at reset.
  constant NO_WINNER : unsigned(ID_W - 1 downto 0)
    := to_unsigned(N_REQS, ID_W);

  -- Combinational signals.
  signal mask_high  : std_logic_vector(N_REQS - 1 downto 0);
  signal req_high   : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_high : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_low  : std_logic_vector(N_REQS - 1 downto 0);
  signal grant_next : std_logic_vector(N_REQS - 1 downto 0);
  signal any_high   : std_logic;

  ----------------------------------------------------------------------------
  -- Local helpers.  Kept in the architecture declaration region so they
  -- are visible to the concurrent statements that follow.
  ----------------------------------------------------------------------------

  -- Local OR-reduce; IEEE.std_logic_misc may not be available everywhere.
  function or_reduce_loc (v : std_logic_vector) return std_logic is
    variable r : std_logic := '0';
  begin
    for i in v'range loop
      r := r or v(i);
    end loop;
    return r;
  end function;

  -- Lowest-set-bit extractor: returns a one-hot vector with only the
  -- least-significant '1' of `v` preserved; all-zero if v is all-zero.
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

  -- Build the priority mask: from the asserted bit of one-hot pointer `p`
  -- upward (toward MSB) is '1'; bits below are '0'.
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

  -- Encode a one-hot vector to its index (low-order bit wins if multiple).
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
  -- Elaboration-time validation of GRANT_LATENCY_CYCLES (must be 0 or 1).
  -- Per PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23.
  ----------------------------------------------------------------------------
  assert GRANT_LATENCY_CYCLES = 0 or GRANT_LATENCY_CYCLES = 1
    report "sos_arbiter_rr: SOS-08-A §6.3 supports GRANT_LATENCY_CYCLES in "
           & "{0, 1} at v1; got value=" & integer'image(GRANT_LATENCY_CYCLES)
    severity failure;

  ----------------------------------------------------------------------------
  -- Combinational arbitration logic.
  ----------------------------------------------------------------------------

  mask_high  <= priority_mask(pointer);
  req_high   <= req and mask_high;
  any_high   <= or_reduce_loc(req_high);

  -- First-bit-set within the masked half; if none, first-bit-set globally
  -- (wrap-around to lower indices).
  grant_high <= lsb_one_hot(req_high);
  grant_low  <= lsb_one_hot(req);

  grant_next <= grant_high when any_high = '1' else grant_low;

  ----------------------------------------------------------------------------
  -- Sequential update of pointer + observability registers.
  ----------------------------------------------------------------------------

  process (clk)
    variable winner_idx_v : natural;
    variable new_ptr_v    : std_logic_vector(N_REQS - 1 downto 0);
  begin
    if rising_edge(clk) then
      if rst = '1' then
        pointer    <= (0 => '1', others => '0');
        grant_q    <= (others => '0');
        last_id_q  <= NO_WINNER;
      else
        grant_q <= grant_next;

        if or_reduce_loc(grant_next) = '1' then
          winner_idx_v := onehot_to_index(grant_next);
          last_id_q    <= to_unsigned(winner_idx_v, ID_W);
          -- Pointer advances to one slot past the winner (modulo N_REQS).
          new_ptr_v                                 := (others => '0');
          new_ptr_v((winner_idx_v + 1) mod N_REQS)  := '1';
          pointer                                   <= new_ptr_v;
        end if;
        -- If no grant this cycle, pointer is held (INV-S-HDL-A-4: pointer
        -- advances exactly once per grant, never spuriously).
      end if;
    end if;
  end process;

  ----------------------------------------------------------------------------
  -- Grant output selector (PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved
  -- 2026-05-23):
  --   GRANT_LATENCY_CYCLES = 1 -> registered grant (grant_q); canonical.
  --   GRANT_LATENCY_CYCLES = 0 -> combinational forward of grant_next; the
  --   pointer still updates on the registered next-cycle path, so the
  --   round-robin advance is unchanged.  Only the externally-visible
  --   request->grant timing collapses by one cycle.
  ----------------------------------------------------------------------------
  g_grant_reg : if GRANT_LATENCY_CYCLES = 1 generate
    grant <= grant_q;
  end generate g_grant_reg;

  g_grant_comb : if GRANT_LATENCY_CYCLES = 0 generate
    grant <= grant_next;
  end generate g_grant_comb;

  last_winner_id <= std_logic_vector(last_id_q);

end architecture rtl;
