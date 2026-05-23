--------------------------------------------------------------------------------
-- sos_credit_counter.vhd - L0 primitive: distributed semaphore (resource credits)
--
-- @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.6
-- @amendments  docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 entries):
--              - PCDN-A-002 resolution: control-only primitives use bare
--                `req`/`ack` naming (NOT AXI-Stream prefixed).
--              - PCDN-A-mutex-ack resolution: stateful primitives MAY use a
--                level-held ack variant. THIS primitive is counter-stateful but
--                **one-shot per acquire attempt** — it therefore uses the
--                **pulse** variant of the two §5.1 control-handshake variants
--                (one-shot per acquire). Per the same amendment, the pulse
--                variant is the canonical shape for non-ownership-tracking
--                stateful primitives (`sos_credit_counter`, `sos_strobe_latch`,
--                `sos_arbiter_rr`).
--              - PCDN-A-bind-form resolution: SVA bind is module-type across
--                all SOS-08-A primitives. The companion bind file in
--                `tb/sos_credit_counter/sos_credit_counter_bind.sv` follows
--                that form.
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- Invariants cited (not re-derived):
--   INV-SOS-A  chart-as-source                  (SOS-07 §6)
--   INV-SOS-B  vectors-as-deliverable           (SOS-07 §6)
--   INV-SOS-C  MCP as sole modification surface (SOS-07 §6)
--   INV-SOS-D  iState authoring, SCXML canon.   (SOS-07 §6)
--   INV-SOS-E  explicit AuthorityRelationship   (SOS-07 §6)
--   INV-SOS-F  bound composition                (SOS-07 §6)
--   INV-SOS-G  verified-codegen position        (SOS-07 §6)
--   INV-SOS-H  vector-to-chart traceability     (SOS-07 §6)
--
--   INV-S-HDL-1  handshake-compatible ports     (SOS-08 §7)
--   INV-S-HDL-2  static-allocation discipline   (SOS-08 §7)
--   INV-S-HDL-3  cross-domain isolation         (SOS-08 §7) — N/A: single domain
--   INV-S-HDL-4  cooperative-only at v1         (SOS-08 §7)
--   INV-S-HDL-5  vector-to-chart traceability   (SOS-08 §7)
--
--   INV-S-HDL-A-1 uniform reset semantics       (SOS-08-A §7) — sync active-high
--   INV-S-HDL-A-2 handshake associativity       (SOS-08-A §7)
--   INV-S-HDL-A-3 vendor-shim byte-identical    (SOS-08-A §7) — portable-only here
--   INV-S-HDL-A-4 one-hot internal FSM default  (SOS-08-A §7) — N/A: pure counter
--   INV-S-HDL-A-5 mandatory params no defaults  (SOS-08-A §7)
--                  — both INIT_CREDITS and MAX_CREDITS have NO defaults.
--
-- Behaviour:
--   * Credit pool initialised to INIT_CREDITS at reset (NOT zero) — the pool
--     is owned by an external scheduler, not the requesters. Reset returns
--     the pool to its initial-availability snapshot.
--   * `acquire_req` is a 1-cycle pulse input. On any cycle where
--     `acquire_req='1'` AND `credits > 0`, `acquire_ack` is a 1-cycle pulse
--     and `credits` decrements by one on the next cycle. The handshake is
--     one-shot: if `credits = 0` when `acquire_req` fires, `acquire_ack`
--     stays low and the requester MUST retry next cycle.
--   * `release_req` is a 1-cycle pulse input that increments `credits` by
--     one on the next cycle. If `credits = MAX_CREDITS` when `release_req`
--     fires, the release is silently dropped (no overflow). The chart
--     compiler is expected to enforce correctness via bounded reachability
--     analysis (INV-SOS-G); no error signal is emitted.
--   * Simultaneous `acquire_req && acquire_ack` AND `release_req` in the
--     same cycle: net-neutral — the new `credits` is `credits_prev - 1 + 1`
--     = `credits_prev`. This is the documented behaviour; see §15
--     PCDN-A-mutex-ack note "two control-handshake variants" — the credit
--     pool uses pulse acquire-ack semantics, so same-cycle acquire+release
--     is a legal, commutative interleaving.
--   * `credits` is an observability output of width
--     ceil(log2(MAX_CREDITS+1)). Width is NOT exposed as a user generic
--     (derived from MAX_CREDITS per §6.6 interface signature).
--   * Synchronous active-high `rst` returns `credits` to INIT_CREDITS and
--     deasserts `acquire_ack`.
--
-- Static elaboration-time check:
--   INIT_CREDITS <= MAX_CREDITS (silent saturation would invite trade-off
--   confusion at synth time per INV-S-HDL-A-5 reasoning).
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_credit_counter is
    generic (
        -- Initial credit pool at reset. Mandatory; no default per INV-S-HDL-A-5.
        INIT_CREDITS : natural;
        -- Maximum credit pool (upper bound on the counter). Mandatory; no
        -- default per INV-S-HDL-A-5.
        MAX_CREDITS  : positive
    );
    port (
        clk         : in  std_logic;
        rst         : in  std_logic;                                                              -- sync active-high
        acquire_req : in  std_logic;                                                              -- 1-cycle pulse
        acquire_ack : out std_logic;                                                              -- 1-cycle pulse on success
        release_req : in  std_logic;                                                              -- 1-cycle pulse
        credits     : out std_logic_vector(integer(ceil(log2(real(MAX_CREDITS+1))))-1 downto 0)   -- observability
    );
end entity sos_credit_counter;

architecture rtl of sos_credit_counter is

    -- Derived width: enough bits to encode {0..MAX_CREDITS}. Not user-exposed.
    constant CW : natural := integer(ceil(log2(real(MAX_CREDITS+1))));

    signal credits_r    : unsigned(CW-1 downto 0);
    signal acquire_ok   : std_logic;  -- combinational: acquire fires this cycle

begin

    ----------------------------------------------------------------------------
    -- Elaboration-time static assertion: INIT_CREDITS <= MAX_CREDITS.
    -- A larger initial pool than the bound is structurally meaningless and
    -- would invite a silent saturation; reject explicitly.
    ----------------------------------------------------------------------------
    assert INIT_CREDITS <= MAX_CREDITS
        report "sos_credit_counter: INIT_CREDITS (" & integer'image(INIT_CREDITS)
               & ") must be <= MAX_CREDITS (" & integer'image(MAX_CREDITS) & ")"
        severity failure;

    ----------------------------------------------------------------------------
    -- Combinational ack: pulse high when acquire requested and credits > 0.
    ----------------------------------------------------------------------------
    acquire_ok <= '1' when (acquire_req = '1') and (credits_r > 0) else '0';

    ----------------------------------------------------------------------------
    -- Sequential counter update.
    --
    --   d_acquire = -1 if acquire_ok else 0
    --   d_release = +1 if (release_req && credits_r < MAX_CREDITS) else 0
    --              (release at MAX is silently dropped per spec)
    --   credits_r_next = credits_r + d_release + d_acquire
    --
    -- The full ordering uses the **pre-update** credits_r to gate both the
    -- acquire and release decisions, which makes same-cycle acquire+release
    -- net-neutral as documented above.
    ----------------------------------------------------------------------------
    process(clk)
        variable next_credits : unsigned(CW-1 downto 0);
        variable do_release   : boolean;
        variable do_acquire   : boolean;
    begin
        if rising_edge(clk) then
            if rst = '1' then
                credits_r <= to_unsigned(INIT_CREDITS, CW);
            else
                next_credits := credits_r;
                do_acquire := (acquire_ok = '1');
                do_release := (release_req = '1')
                              and (credits_r < to_unsigned(MAX_CREDITS, CW));

                if do_release then
                    next_credits := next_credits + 1;
                end if;
                if do_acquire then
                    next_credits := next_credits - 1;
                end if;

                credits_r <= next_credits;
            end if;
        end if;
    end process;

    ----------------------------------------------------------------------------
    -- Outputs
    ----------------------------------------------------------------------------
    acquire_ack <= acquire_ok;
    credits     <= std_logic_vector(credits_r);

end architecture rtl;
