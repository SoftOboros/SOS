--------------------------------------------------------------------------------
-- instantiate.vhd - sos_credit_counter instantiation example
--                   (INIT_CREDITS=4, MAX_CREDITS=8)
--
-- @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.6 ("Instantiation example")
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
--
-- Minimal chart-emitted top-level showing how a credit pool initialised to 4
-- with a ceiling of 8 is wired: one acquire-pulse in, one ack-pulse out, one
-- release-pulse in, and a `credits` observability port (width
-- ceil(log2(8+1)) = 4).
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_credit_counter_example is
    port (
        clk         : in  std_logic;
        rst         : in  std_logic;
        acquire_req : in  std_logic;
        acquire_ack : out std_logic;
        release_req : in  std_logic;
        credits     : out std_logic_vector(3 downto 0)  -- ceil(log2(8+1)) = 4
    );
end entity sos_credit_counter_example;

architecture rtl of sos_credit_counter_example is
begin

    u_credit : entity work.sos_credit_counter
        generic map (
            INIT_CREDITS => 4,
            MAX_CREDITS  => 8
        )
        port map (
            clk         => clk,
            rst         => rst,
            acquire_req => acquire_req,
            acquire_ack => acquire_ack,
            release_req => release_req,
            credits     => credits
        );

end architecture rtl;
