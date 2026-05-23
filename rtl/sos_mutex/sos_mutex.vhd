--------------------------------------------------------------------------------
-- sos_mutex.vhd - L0 primitive: 1-bit lock register + round-robin arbiter
--
-- @spec       docs/concepts/SOS-08-A-CONCEPTS.md §6.5
-- @parent     docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- Invariants cited (not re-derived):
--   INV-SOS-A  chart-as-source                 (SOS-07 §6)
--   INV-SOS-B  vectors-as-deliverable          (SOS-07 §6)
--   INV-SOS-C  MCP as sole modification surface(SOS-07 §6)
--   INV-SOS-D  iState authoring, SCXML canon.  (SOS-07 §6)
--   INV-SOS-E  explicit AuthorityRelationship  (SOS-07 §6)
--   INV-SOS-F  bound composition               (SOS-07 §6)
--   INV-SOS-G  verified-codegen position       (SOS-07 §6)
--   INV-SOS-H  vector-to-chart traceability    (SOS-07 §6)
--
--   INV-S-HDL-1  handshake-compatible ports    (SOS-08 §7)
--   INV-S-HDL-2  static-allocation discipline  (SOS-08 §7)
--   INV-S-HDL-3  cross-domain isolation        (SOS-08 §7) — N/A: single domain
--   INV-S-HDL-4  cooperative-only at v1        (SOS-08 §7)
--   INV-S-HDL-5  vector-to-chart traceability  (SOS-08 §7)
--
--   INV-S-HDL-A-1 uniform reset semantics      (SOS-08-A §7) — sync active-high
--   INV-S-HDL-A-2 handshake associativity      (SOS-08-A §7)
--   INV-S-HDL-A-3 vendor-shim byte-identical   (SOS-08-A §7) — portable-only here
--   INV-S-HDL-A-4 one-hot internal FSM default (SOS-08-A §7)
--   INV-S-HDL-A-5 mandatory params no defaults (SOS-08-A §7) — N_CLIENTS no default
--
-- Per PCDN-A-002 resolution (§15 2026-05-23): control-only primitives use bare
-- `req`/`ack` (not AXI-Stream prefixed). This is a control primitive.
--
-- Behaviour:
--   * `req(i)` asserted by client i to acquire (and hold) the lock.
--   * `ack(i)` asserted high on every cycle client i holds the lock (one-hot).
--   * Release is signalled by the client deasserting `req(i)` while holding.
--   * On simultaneous contention while Free, a round-robin pointer selects the
--     next-highest index (mod N_CLIENTS) starting from the slot after the last
--     holder, providing the fairness bound of N_CLIENTS cycles for any
--     continuously-asserted requester.
--   * `holder_id = N_CLIENTS` when no client holds the lock (sentinel).
--   * Synchronous active-high `rst` returns FSM to Free, clears `holder_id`,
--     clears `ack`, and resets the round-robin pointer to 0.
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;

entity sos_mutex is
    generic (
        -- Number of requesting clients. Mandatory; no default per INV-S-HDL-A-5.
        N_CLIENTS : positive
    );
    port (
        clk       : in  std_logic;
        rst       : in  std_logic;                                  -- sync active-high
        req       : in  std_logic_vector(N_CLIENTS-1 downto 0);
        ack       : out std_logic_vector(N_CLIENTS-1 downto 0);     -- one-hot grant
        locked    : out std_logic;
        holder_id : out std_logic_vector(integer(ceil(log2(real(N_CLIENTS+1))))-1 downto 0)
    );
end entity sos_mutex;

architecture rtl of sos_mutex is

    -- Width of holder_id: enough bits to encode {0 .. N_CLIENTS} where the value
    -- N_CLIENTS encodes "unheld".
    constant HID_W : natural := integer(ceil(log2(real(N_CLIENTS+1))));

    -- Sentinel value for "no holder".
    constant NO_HOLDER : unsigned(HID_W-1 downto 0) :=
        to_unsigned(N_CLIENTS, HID_W);

    --------------------------------------------------------------------------
    -- Internal FSM (one-hot per INV-S-HDL-A-4).
    --   state(0) = FREE
    --   state(1) = HELD
    --------------------------------------------------------------------------
    signal state      : std_logic_vector(1 downto 0);
    constant ST_FREE  : std_logic_vector(1 downto 0) := "01";
    constant ST_HELD  : std_logic_vector(1 downto 0) := "10";

    signal holder_r   : unsigned(HID_W-1 downto 0);  -- current holder index
    signal rr_ptr_r   : unsigned(HID_W-1 downto 0);  -- next-scan start, in [0, N_CLIENTS)

    --------------------------------------------------------------------------
    -- Round-robin pick: choose the lowest-numbered index i in
    --   ( (rr_ptr_r + 0), (rr_ptr_r + 1), ..., (rr_ptr_r + N_CLIENTS - 1) ) mod N
    -- whose req(i) is asserted. Returns N_CLIENTS if none.
    --------------------------------------------------------------------------
    function rr_pick(
        req_vec : std_logic_vector;
        start   : unsigned;
        n       : positive
    ) return natural is
        variable idx : natural;
    begin
        for k in 0 to n-1 loop
            idx := (to_integer(start) + k) mod n;
            if req_vec(idx) = '1' then
                return idx;
            end if;
        end loop;
        return n;  -- no requester
    end function rr_pick;

begin

    ----------------------------------------------------------------------------
    -- Sequential: FSM + holder + round-robin pointer
    ----------------------------------------------------------------------------
    process(clk)
        variable picked : natural;
    begin
        if rising_edge(clk) then
            if rst = '1' then
                state    <= ST_FREE;
                holder_r <= NO_HOLDER;
                rr_ptr_r <= (others => '0');
            else
                case state is

                    when ST_FREE =>
                        picked := rr_pick(req, rr_ptr_r, N_CLIENTS);
                        if picked < N_CLIENTS then
                            state    <= ST_HELD;
                            holder_r <= to_unsigned(picked, HID_W);
                            -- Advance rr pointer past the winner for next contention.
                            rr_ptr_r <= to_unsigned((picked + 1) mod N_CLIENTS, HID_W);
                        end if;

                    when ST_HELD =>
                        -- Holder relinquishes when its req drops.
                        if req(to_integer(holder_r)) = '0' then
                            state    <= ST_FREE;
                            holder_r <= NO_HOLDER;
                            -- rr_ptr_r already advanced at grant; next contention
                            -- starts from there, giving the holder's neighbour
                            -- priority on the next cycle. This caps continuous
                            -- starvation at N_CLIENTS cycles.
                        end if;

                    when others =>
                        -- Illegal one-hot state; recover.
                        state    <= ST_FREE;
                        holder_r <= NO_HOLDER;

                end case;
            end if;
        end if;
    end process;

    ----------------------------------------------------------------------------
    -- Combinational outputs
    ----------------------------------------------------------------------------
    locked    <= '1' when state = ST_HELD else '0';
    holder_id <= std_logic_vector(holder_r);

    -- One-hot ack: high for the holder while HELD, else all zero.
    ack_gen : process(state, holder_r)
    begin
        ack <= (others => '0');
        if state = ST_HELD then
            if to_integer(holder_r) < N_CLIENTS then
                ack(to_integer(holder_r)) <= '1';
            end if;
        end if;
    end process ack_gen;

end architecture rtl;
