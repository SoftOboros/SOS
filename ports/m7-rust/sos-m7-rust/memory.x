/* sos-m7-rust linker memory regions.
 *
 * Per SOS-04-CONCEPTS.md §6.9 (bench substrate) and §8 (artifact map),
 * cross-referenced with RM0399 §D1.2.3 (CM7 memory layout). Sizes are
 * the v1 ratified values (PCDN-SOS-04-006, PCDN-SOS-04-012, PCDN-SOS-04-013).
 *
 * Skeleton commit: declares the three regions cortex-m-rt needs and a
 * canonical stack-top. Per-section placement of `.kernel_stack` /
 * `.task_stacks` / `TRACE_*_BUF` lands in the implementation phase when
 * the corresponding static symbols exist.
 */

MEMORY
{
  FLASH  : ORIGIN = 0x08000000, LENGTH = 1024K  /* CM7 Bank 1 (PCDN-SOS-04-012). */
  /* cortex-m-rt 0.7's bundled `link.x` (see cargo build OUT_DIR after
   * the cortex-m-rt build script runs) references a region named `RAM`
   * for `_ram_start` / `_ram_end` / `_stack_start` and for placing
   * `.bss` + `.data`. Per SOS-04-CONCEPTS.md §6.9, the CM7 DTCM at
   * 0x20000000 holds `.bss` + `.data` + the kernel stack; we surface it
   * to the linker under the canonical name `RAM`. The semantic-friendly
   * `DTCM` alias below preserves the §6.9 vocabulary for any future
   * crate-local placement directives. */
  RAM    : ORIGIN = 0x20000000, LENGTH = 128K   /* CM7 DTCM — .bss + .data + kernel stack. */
  SRAM   : ORIGIN = 0x24000000, LENGTH = 384K   /* CM7 D1 AXI-SRAM — TRACE_*_BUF + .task_stacks. */
}

/* `DTCM` alias preserves the SOS-04-CONCEPTS.md §6.9 vocabulary for any
 * crate-local placement directives that target the DTCM bank by name. */
REGION_ALIAS("DTCM", RAM);

/* cortex-m-rt 0.7 reads `_stack_start` for the initial MSP value.
 * PCDN-SOS-04-006: KERNEL_STACK_BYTES = 4 KiB at the top of DTCM. The
 * task-stack pool (TASK_STACK_BYTES x MAX_TASKS = 16 KiB) lives in D1
 * AXI-SRAM and is declared as a static array in src/kernel.rs at the
 * implementation phase — no custom SECTIONS block needed at v1. */
_stack_start = ORIGIN(RAM) + LENGTH(RAM);
