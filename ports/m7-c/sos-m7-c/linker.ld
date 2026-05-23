/* linker.ld — SOS-05 M7 C port linker script.
 *
 * Per SOS-05-CONCEPTS.md §6.9 (memory regions per RM0399 §D1.2.3) and
 * §6.8 (boot path / stack symbols). Sibling-parallel with
 * ports/m7-rust/sos-m7-rust/memory.x — the two ports share the v1
 * region layout (FLASH 1024K, DTCM 128K, AXI-SRAM 384K).
 *
 * Skeleton commit: declares the regions, the sections, and the
 * `_stack_start` / `_sidata` / `_sdata` / `_edata` / `_sbss` / `_ebss`
 * symbols startup.S references.
 */

ENTRY(Reset_Handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 1024K   /* CM7 Bank 1 */
    DTCM  (rwx) : ORIGIN = 0x20000000, LENGTH =  128K   /* CM7 DTCM */
    SRAM  (rwx) : ORIGIN = 0x24000000, LENGTH =  384K   /* D1 AXI-SRAM */
}

/* Per SOS-04 PCDN-006 (mirrored to SOS-05): 4 KiB MSP backing store at
 * the top of DTCM. The actual reservation happens via _stack_start
 * pointing at ORIGIN(DTCM)+LENGTH(DTCM); the .kernel_stack section
 * carves the region by reserving size at the end of DTCM's .bss. */
_kernel_stack_size = 4K;

SECTIONS
{
    /* Vector table first in FLASH. */
    .isr_vector :
    {
        . = ALIGN(4);
        KEEP(*(.isr_vector))
        . = ALIGN(4);
    } > FLASH

    /* Code + read-only data. */
    .text :
    {
        . = ALIGN(4);
        *(.text)
        *(.text*)
        *(.glue_7)
        *(.glue_7t)
        *(.eh_frame)
        . = ALIGN(4);
        _etext = .;
    } > FLASH

    .rodata :
    {
        . = ALIGN(4);
        *(.rodata)
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH

    .ARM.extab :
    {
        *(.ARM.extab* .gnu.linkonce.armextab.*)
    } > FLASH

    .ARM :
    {
        __exidx_start = .;
        *(.ARM.exidx*)
        __exidx_end = .;
    } > FLASH

    /* .data: load from FLASH, run from DTCM. Startup copies. */
    _sidata = LOADADDR(.data);
    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > DTCM AT > FLASH

    /* .bss in DTCM. */
    .bss :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss)
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > DTCM

    /* Reserve the kernel (MSP) stack at the top of DTCM. */
    .kernel_stack (NOLOAD) :
    {
        . = ALIGN(8);
        . = . + _kernel_stack_size;
        . = ALIGN(8);
    } > DTCM

    /* Per-task PSP regions in AXI-SRAM. The task_stacks[] array in
     * src/kernel.c carries `__attribute__((section(".task_stacks")))`
     * which collects here. */
    .task_stacks (NOLOAD) :
    {
        . = ALIGN(8);
        *(.task_stacks)
        . = ALIGN(8);
    } > SRAM

    /* Initial MSP value the vector table emits at offset 0. */
    _stack_start = ORIGIN(DTCM) + LENGTH(DTCM);

    /DISCARD/ :
    {
        *(.ARM.attributes)
    }
}
