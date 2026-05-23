--------------------------------------------------------------------------------
-- instantiate.vhd - sos_mutex instantiation example (N_CLIENTS = 4)
--
-- @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.5 ("Instantiation example")
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
--
-- Minimal chart-emitted top-level showing how a 4-client mutex is wired:
--   four request bits in, four grant bits out, plus the lock-status outputs
--   for observability.
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_mutex_example is
    port (
        clk       : in  std_logic;
        rst       : in  std_logic;
        req       : in  std_logic_vector(3 downto 0);
        ack       : out std_logic_vector(3 downto 0);
        locked    : out std_logic;
        holder_id : out std_logic_vector(2 downto 0)  -- $clog2(4+1) = 3
    );
end entity sos_mutex_example;

architecture rtl of sos_mutex_example is
begin

    u_mutex : entity work.sos_mutex
        generic map (
            N_CLIENTS => 4
        )
        port map (
            clk       => clk,
            rst       => rst,
            req       => req,
            ack       => ack,
            locked    => locked,
            holder_id => holder_id
        );

end architecture rtl;
