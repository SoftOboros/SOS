//------------------------------------------------------------------------------
// instantiate.sv - sos_resource_pool instantiation example
//                  (POOL_SIZE=64, ID_WIDTH=16, META_WIDTH=128 — the chart's
//                   task pool with TCB-shaped metadata)
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.3 (instantiation example)
//              docs/concepts/SOS-08-B-CONCEPTS.md §15 (PCDN-SOS-08-B-003 → ID_WIDTH
//                                                       default 16, matching chart
//                                                       task_id; per-pool width
//                                                       selected at chart-emission
//                                                       from MAX_TASKS / MAX_SEMS /
//                                                       MAX_QUEUES)
//              docs/concepts/SOS-08-A-CONCEPTS.md §6.6 (composed sos_credit_counter)
//              docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (composed sos_dpram_arb)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-B-1..5.
//
// Minimal chart-emitted top-level showing how the task pool is wired:
// POOL_SIZE=64 slots (matches a chart MAX_TASKS=64 configuration),
// ID_WIDTH=16 (chart task_id width per PCDN-SOS-08-B-003), META_WIDTH=128
// (a TCB-shaped packed struct: task fn ptr + arg ptr + stack base + priority
// + state bits, packed into 128 bits at chart-emission time).
//
// The alloc / free vocabulary maps to chart events:
//   alloc_req  -> task.create
//   alloc_id   -> task_id assigned to the newly-created task
//   free_req   -> task.delete  (future SOS-01 §15 amendment)
//   write_meta -> TCB initialisation by the task-create syscall body
//   read_meta  -> TCB lookup by the scheduler
//------------------------------------------------------------------------------

`default_nettype none

module sos_resource_pool_example (
    input  wire         clk,
    input  wire         rst,

    // alloc side.
    input  wire         alloc_req,
    output wire         alloc_ack,
    output wire [15:0]  alloc_id,         // ID_WIDTH = 16

    // free side.
    input  wire         free_req,
    input  wire [15:0]  free_id,

    // read side.
    input  wire [15:0]  read_id,
    output wire [127:0] read_meta,        // META_WIDTH = 128

    // write side.
    input  wire         write_req,
    input  wire [15:0]  write_id,
    input  wire [127:0] write_meta,

    // observability — clog2(64+1) = 7 bits.
    output wire [6:0]   free_count
);

    sos_resource_pool #(
        .POOL_SIZE  (64),         // chart MAX_TASKS = 64 (worked example)
        .ID_WIDTH   (16),         // PCDN-SOS-08-B-003 default
        .META_WIDTH (128)         // TCB packed-struct width
    ) u_task_pool (
        .clk        (clk),
        .rst        (rst),

        .alloc_req  (alloc_req),
        .alloc_ack  (alloc_ack),
        .alloc_id   (alloc_id),

        .free_req   (free_req),
        .free_id    (free_id),

        .read_id    (read_id),
        .read_meta  (read_meta),

        .write_req  (write_req),
        .write_id   (write_id),
        .write_meta (write_meta),

        .free_count (free_count)
    );

endmodule

`default_nettype wire
