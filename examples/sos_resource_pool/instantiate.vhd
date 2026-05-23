--------------------------------------------------------------------------------
-- instantiate.vhd - sos_resource_pool instantiation example
--                   (POOL_SIZE=64, ID_WIDTH=16, META_WIDTH=128 — the chart's
--                    task pool with TCB-shaped metadata)
--
-- @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.3 (instantiation example)
--              docs/concepts/SOS-08-B-CONCEPTS.md §15 (PCDN-SOS-08-B-003 →
--                                                       ID_WIDTH default 16,
--                                                       matching chart task_id;
--                                                       per-pool width selected
--                                                       at chart-emission from
--                                                       MAX_TASKS / MAX_SEMS /
--                                                       MAX_QUEUES)
--              docs/concepts/SOS-08-A-CONCEPTS.md §6.6 (composed
--                                                       sos_credit_counter)
--              docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (composed sos_dpram_arb)
-- @parent      docs/concepts/SOS-08-CONCEPTS.md §6
-- @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
--
-- Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-B-1..5.
--
-- Minimal chart-emitted top-level showing how the task pool is wired:
-- POOL_SIZE=64 slots (matches a chart MAX_TASKS=64 configuration),
-- ID_WIDTH=16 (chart task_id width per PCDN-SOS-08-B-003), META_WIDTH=128
-- (a TCB-shaped packed struct).
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;

entity sos_resource_pool_example is
    port (
        clk        : in  std_logic;
        rst        : in  std_logic;

        -- alloc side.
        alloc_req  : in  std_logic;
        alloc_ack  : out std_logic;
        alloc_id   : out std_logic_vector(15 downto 0);    -- ID_WIDTH = 16

        -- free side.
        free_req   : in  std_logic;
        free_id    : in  std_logic_vector(15 downto 0);

        -- read side.
        read_id    : in  std_logic_vector(15 downto 0);
        read_meta  : out std_logic_vector(127 downto 0);   -- META_WIDTH = 128

        -- write side.
        write_req  : in  std_logic;
        write_id   : in  std_logic_vector(15 downto 0);
        write_meta : in  std_logic_vector(127 downto 0);

        -- observability — ceil(log2(64+1)) = 7 bits.
        free_count : out std_logic_vector(6 downto 0)
    );
end entity sos_resource_pool_example;

architecture rtl of sos_resource_pool_example is

    component sos_resource_pool is
        generic (
            POOL_SIZE  : positive;
            ID_WIDTH   : positive := 16;
            META_WIDTH : positive
        );
        port (
            clk        : in  std_logic;
            rst        : in  std_logic;

            alloc_req  : in  std_logic;
            alloc_ack  : out std_logic;
            alloc_id   : out std_logic_vector;

            free_req   : in  std_logic;
            free_id    : in  std_logic_vector;

            read_id    : in  std_logic_vector;
            read_meta  : out std_logic_vector;

            write_req  : in  std_logic;
            write_id   : in  std_logic_vector;
            write_meta : in  std_logic_vector;

            free_count : out std_logic_vector
        );
    end component;

begin

    u_task_pool : sos_resource_pool
        generic map (
            POOL_SIZE  => 64,     -- chart MAX_TASKS = 64 (worked example)
            ID_WIDTH   => 16,     -- PCDN-SOS-08-B-003 default
            META_WIDTH => 128     -- TCB packed-struct width
        )
        port map (
            clk        => clk,
            rst        => rst,

            alloc_req  => alloc_req,
            alloc_ack  => alloc_ack,
            alloc_id   => alloc_id,

            free_req   => free_req,
            free_id    => free_id,

            read_id    => read_id,
            read_meta  => read_meta,

            write_req  => write_req,
            write_id   => write_id,
            write_meta => write_meta,

            free_count => free_count
        );

end architecture rtl;
