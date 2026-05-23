/* sos/stm32h747_minimal.h — hand-coded minimal CMSIS-Device + CMSIS-Core
 * surface for the STM32H747I-DISCO CM7.
 *
 * Per SOS-05-CONCEPTS.md PCDN-SOS-05-009 (no STM32CubeH7 HAL) and §4.1
 * (CMSIS-Core is `mirror`-dependency, vendored device header is
 * acceptable). The phase-1 skeleton expected an externally-vendored
 * `stm32h747xx.h`; phase 2 chooses option (b) — a hand-coded minimal
 * header — because the conformance port only touches a handful of
 * peripherals (RCC, GPIOA, USART1, SCB, SysTick, NVIC) and a full
 * CMSIS-Device drop is ~10K lines of mostly-irrelevant content.
 *
 * The choice is *hermetic*: the build does not require an external
 * CMSIS-Device package to be installed. The trade-off is that adding a
 * new peripheral (e.g. USART3 if PCDN-SOS-05-008 changes its fallback)
 * means extending this header. At v1 surface size that is a one-line
 * struct entry.
 *
 * Register offsets and reset values were transcribed from RM0399 §8
 * (RCC), §57 (GPIO), §54 (USART), and the ARMv7-M ARM B3 (SCB / SysTick
 * / NVIC). The two ports — Rust via `stm32h7` PAC, C via this header —
 * MUST agree on the register layout; sibling-parallel review at PR time
 * is the gate. INV-S-PORT-9 applies once the kernel state is observable;
 * INV-S-PORT-2 applies at boot.
 */

#ifndef SOS_STM32H747_MINIMAL_H
#define SOS_STM32H747_MINIMAL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================ */
/* CMSIS-Core intrinsics (subset)                               */
/* ============================================================ */

/* Data Synchronisation Barrier. */
__attribute__((always_inline)) static inline void __DSB(void)
{
    __asm volatile ("dsb 0xF" ::: "memory");
}

/* Instruction Synchronisation Barrier. */
__attribute__((always_inline)) static inline void __ISB(void)
{
    __asm volatile ("isb 0xF" ::: "memory");
}

/* Wait For Interrupt. */
__attribute__((always_inline)) static inline void __WFI(void)
{
    __asm volatile ("wfi");
}

/* Write BASEPRI. */
__attribute__((always_inline)) static inline void __set_BASEPRI(uint32_t value)
{
    __asm volatile ("msr basepri, %0" : : "r" (value) : "memory");
}

/* Read BASEPRI. */
__attribute__((always_inline)) static inline uint32_t __get_BASEPRI(void)
{
    uint32_t result;
    __asm volatile ("mrs %0, basepri" : "=r" (result));
    return result;
}

/* ============================================================ */
/* SCB — System Control Block (0xE000_ED00)                     */
/* ============================================================ */

typedef struct {
    volatile uint32_t CPUID;       /* 0x000 */
    volatile uint32_t ICSR;        /* 0x004 */
    volatile uint32_t VTOR;        /* 0x008 */
    volatile uint32_t AIRCR;       /* 0x00C */
    volatile uint32_t SCR;         /* 0x010 */
    volatile uint32_t CCR;         /* 0x014 */
    volatile uint8_t  SHPR[12];    /* 0x018: SHPR1..SHPR3, byte-indexed */
    volatile uint32_t SHCSR;       /* 0x024 */
    volatile uint32_t CFSR;        /* 0x028 */
    volatile uint32_t HFSR;        /* 0x02C */
    volatile uint32_t DFSR;        /* 0x030 */
    volatile uint32_t MMFAR;       /* 0x034 */
    volatile uint32_t BFAR;        /* 0x038 */
    volatile uint32_t AFSR;        /* 0x03C */
    volatile uint32_t reserved0[18];
    volatile uint32_t CPACR;       /* 0x088 */
} SCB_Type;

#define SCB_BASE              0xE000ED00UL
#define SCB                   ((SCB_Type *)SCB_BASE)

#define SCB_AIRCR_VECTKEY_Pos 16U
#define SCB_AIRCR_VECTKEY     (0x05FAUL << SCB_AIRCR_VECTKEY_Pos)
#define SCB_AIRCR_PRIGROUP_Pos 8U

#define SCB_ICSR_PENDSVSET_Pos 28U
#define SCB_ICSR_PENDSVSET_Msk (1UL << SCB_ICSR_PENDSVSET_Pos)

/* SHPR byte index for the system exceptions used by SOS:
 *   SHPR[7]  = PendSV  (exception 14)  — SHPR3[15:8]
 *   SHPR[8]  = SysTick (exception 15)  — SHPR3[23:16]
 * Indices follow the ARMv7-M ARM B3.2.10 mapping: SHPR[N] is the
 * priority of exception (N + 4), i.e. SHPR[0] = MemManage (4),
 * SHPR[7] = PendSV (14), SHPR[8] = SysTick (15). */
#define SCB_SHPR_PENDSV_IDX  7U
#define SCB_SHPR_SYSTICK_IDX 8U

/* ============================================================ */
/* SysTick (0xE000_E010)                                        */
/* ============================================================ */

typedef struct {
    volatile uint32_t CTRL;        /* 0x000 */
    volatile uint32_t LOAD;        /* 0x004 */
    volatile uint32_t VAL;         /* 0x008 */
    volatile uint32_t CALIB;       /* 0x00C */
} SysTick_Type;

#define SysTick_BASE          0xE000E010UL
#define SysTick               ((SysTick_Type *)SysTick_BASE)

#define SysTick_CTRL_ENABLE_Pos      0U
#define SysTick_CTRL_ENABLE_Msk      (1UL << SysTick_CTRL_ENABLE_Pos)
#define SysTick_CTRL_TICKINT_Pos     1U
#define SysTick_CTRL_TICKINT_Msk     (1UL << SysTick_CTRL_TICKINT_Pos)
#define SysTick_CTRL_CLKSOURCE_Pos   2U
#define SysTick_CTRL_CLKSOURCE_Msk   (1UL << SysTick_CTRL_CLKSOURCE_Pos)

/* ============================================================ */
/* NVIC (0xE000_E100)                                           */
/* ============================================================ */

typedef struct {
    volatile uint32_t ISER[8];     /* 0x000 enable */
    uint32_t reserved0[24];
    volatile uint32_t ICER[8];     /* 0x080 clear-enable */
    uint32_t reserved1[24];
    volatile uint32_t ISPR[8];     /* 0x100 set-pending */
    uint32_t reserved2[24];
    volatile uint32_t ICPR[8];     /* 0x180 clear-pending */
    uint32_t reserved3[24];
    volatile uint32_t IABR[8];     /* 0x200 active-bit */
    uint32_t reserved4[56];
    volatile uint8_t  IPR[240];    /* 0x300 byte-indexed priorities */
} NVIC_Type;

#define NVIC_BASE             0xE000E100UL
#define NVIC                  ((NVIC_Type *)NVIC_BASE)

/* External IRQ numbers used by SOS. The full STM32H747xx vector table
 * carries dozens; SOS only enables USART1 (INV-S-PORT-4). */
#define USART1_IRQn           37

/* ============================================================ */
/* RCC (0x5802_4400) — Reset and Clock Control                   */
/* ============================================================ */

/* The H7 RCC register block is large; SOS only touches CR, CFGR,
 * PLLCKSELR, PLLCFGR, PLL1DIVR, D1CFGR, D2CFGR, D3CFGR, AHB4ENR,
 * APB2ENR. Layout is per RM0399 Table 56 with byte offsets. We define a
 * sparse struct that places only the fields we use; intermediate
 * reserved space is sized as required. */

typedef struct {
    volatile uint32_t CR;          /* 0x000 */
    volatile uint32_t HSICFGR;     /* 0x004 */
    volatile uint32_t CRRCR;       /* 0x008 */
    volatile uint32_t CSICFGR;     /* 0x00C */
    volatile uint32_t CFGR;        /* 0x010 */
    uint32_t reserved0[1];         /* 0x014 */
    volatile uint32_t D1CFGR;      /* 0x018 */
    volatile uint32_t D2CFGR;      /* 0x01C */
    volatile uint32_t D3CFGR;      /* 0x020 */
    uint32_t reserved1[1];         /* 0x024 */
    volatile uint32_t PLLCKSELR;   /* 0x028 */
    volatile uint32_t PLLCFGR;     /* 0x02C */
    volatile uint32_t PLL1DIVR;    /* 0x030 */
    volatile uint32_t PLL1FRACR;   /* 0x034 */
    volatile uint32_t PLL2DIVR;    /* 0x038 */
    volatile uint32_t PLL2FRACR;   /* 0x03C */
    volatile uint32_t PLL3DIVR;    /* 0x040 */
    volatile uint32_t PLL3FRACR;   /* 0x044 */
    uint32_t reserved2[1];         /* 0x048 */
    volatile uint32_t D1CCIPR;     /* 0x04C */
    volatile uint32_t D2CCIP1R;    /* 0x050 */
    volatile uint32_t D2CCIP2R;    /* 0x054 */
    volatile uint32_t D3CCIPR;     /* 0x058 */
    uint32_t reserved3[1];         /* 0x05C */
    volatile uint32_t CIER;        /* 0x060 */
    volatile uint32_t CIFR;        /* 0x064 */
    volatile uint32_t CICR;        /* 0x068 */
    uint32_t reserved4[1];         /* 0x06C */
    volatile uint32_t BDCR;        /* 0x070 */
    volatile uint32_t CSR;         /* 0x074 */
    uint32_t reserved5[1];         /* 0x078 */
    volatile uint32_t AHB3RSTR;    /* 0x07C */
    volatile uint32_t AHB1RSTR;    /* 0x080 */
    volatile uint32_t AHB2RSTR;    /* 0x084 */
    volatile uint32_t AHB4RSTR;    /* 0x088 */
    volatile uint32_t APB3RSTR;    /* 0x08C */
    volatile uint32_t APB1LRSTR;   /* 0x090 */
    volatile uint32_t APB1HRSTR;   /* 0x094 */
    volatile uint32_t APB2RSTR;    /* 0x098 */
    volatile uint32_t APB4RSTR;    /* 0x09C */
    volatile uint32_t GCR;         /* 0x0A0 */
    uint32_t reserved6[1];         /* 0x0A4 */
    volatile uint32_t D3AMR;       /* 0x0A8 */
    uint32_t reserved7[9];         /* 0x0AC..0x0CC */
    volatile uint32_t RSR;         /* 0x0D0 */
    volatile uint32_t AHB3ENR;     /* 0x0D4 */
    volatile uint32_t AHB1ENR;     /* 0x0D8 */
    volatile uint32_t AHB2ENR;     /* 0x0DC */
    volatile uint32_t AHB4ENR;     /* 0x0E0 */
    volatile uint32_t APB3ENR;     /* 0x0E4 */
    volatile uint32_t APB1LENR;    /* 0x0E8 */
    volatile uint32_t APB1HENR;    /* 0x0EC */
    volatile uint32_t APB2ENR;     /* 0x0F0 */
    volatile uint32_t APB4ENR;     /* 0x0F4 */
} RCC_Type;

#define RCC_BASE              0x58024400UL
#define RCC                   ((RCC_Type *)RCC_BASE)

/* RCC->CR bits */
#define RCC_CR_HSION          (1UL <<  0)
#define RCC_CR_HSIRDY         (1UL <<  2)
#define RCC_CR_HSEON          (1UL << 16)
#define RCC_CR_HSERDY         (1UL << 17)
#define RCC_CR_HSEBYP         (1UL << 18)
#define RCC_CR_PLL1ON         (1UL << 24)
#define RCC_CR_PLL1RDY        (1UL << 25)

/* RCC->CFGR bits */
#define RCC_CFGR_SW_HSI       (0UL << 0)
#define RCC_CFGR_SW_CSI       (1UL << 0)
#define RCC_CFGR_SW_HSE       (2UL << 0)
#define RCC_CFGR_SW_PLL1      (3UL << 0)
#define RCC_CFGR_SW_Msk       (7UL << 0)
#define RCC_CFGR_SWS_Pos      3
#define RCC_CFGR_SWS_Msk      (7UL << RCC_CFGR_SWS_Pos)
#define RCC_CFGR_SWS_PLL1     (3UL << RCC_CFGR_SWS_Pos)

/* RCC->D1CFGR: D1CPRE [11:8], HPRE [3:0], D1PPRE [6:4] */
#define RCC_D1CFGR_HPRE_DIV2      (8UL << 0)   /* HCLK = SYSCLK / 2 */
#define RCC_D1CFGR_D1CPRE_DIV1    (0UL << 8)   /* CM7 = SYSCLK / 1 */
#define RCC_D1CFGR_D1PPRE_DIV2    (4UL << 4)   /* APB3 = HCLK / 2 */

/* RCC->D2CFGR: D2PPRE1 [6:4], D2PPRE2 [10:8] */
#define RCC_D2CFGR_D2PPRE1_DIV2   (4UL << 4)
#define RCC_D2CFGR_D2PPRE2_DIV2   (4UL << 8)

/* RCC->D3CFGR: D3PPRE [6:4] */
#define RCC_D3CFGR_D3PPRE_DIV2    (4UL << 4)

/* RCC->PLLCKSELR: PLLSRC [1:0], DIVM1 [9:4] */
#define RCC_PLLCKSELR_PLLSRC_HSE  (2UL << 0)
#define RCC_PLLCKSELR_DIVM1_Pos   4

/* RCC->PLLCFGR */
#define RCC_PLLCFGR_PLL1FRACEN    (1UL <<  0)
#define RCC_PLLCFGR_PLL1VCOSEL    (1UL <<  1)   /* 0 = wide VCO (192..836 MHz) */
#define RCC_PLLCFGR_PLL1RGE_Pos   2
#define RCC_PLLCFGR_PLL1RGE_4_8   (3UL << RCC_PLLCFGR_PLL1RGE_Pos)
#define RCC_PLLCFGR_DIVP1EN       (1UL << 16)
#define RCC_PLLCFGR_DIVQ1EN       (1UL << 17)
#define RCC_PLLCFGR_DIVR1EN       (1UL << 18)

/* RCC->PLL1DIVR: DIVN1 [8:0], DIVP1 [15:9], DIVQ1 [22:16], DIVR1 [28:24] */
#define RCC_PLL1DIVR_DIVN1_Pos    0
#define RCC_PLL1DIVR_DIVP1_Pos    9
#define RCC_PLL1DIVR_DIVQ1_Pos    16
#define RCC_PLL1DIVR_DIVR1_Pos    24

/* RCC->AHB4ENR */
#define RCC_AHB4ENR_GPIOAEN       (1UL << 0)

/* RCC->APB2ENR */
#define RCC_APB2ENR_USART1EN      (1UL << 4)

/* ============================================================ */
/* GPIOA (0x5802_0000)                                          */
/* ============================================================ */

typedef struct {
    volatile uint32_t MODER;       /* 0x00 */
    volatile uint32_t OTYPER;      /* 0x04 */
    volatile uint32_t OSPEEDR;     /* 0x08 */
    volatile uint32_t PUPDR;       /* 0x0C */
    volatile uint32_t IDR;         /* 0x10 */
    volatile uint32_t ODR;         /* 0x14 */
    volatile uint32_t BSRR;        /* 0x18 */
    volatile uint32_t LCKR;        /* 0x1C */
    volatile uint32_t AFR[2];      /* 0x20: AFRL=AFR[0], AFRH=AFR[1] */
} GPIO_Type;

#define GPIOA_BASE            0x58020000UL
#define GPIOA                 ((GPIO_Type *)GPIOA_BASE)

/* ============================================================ */
/* USART1 (0x4001_1000)                                         */
/* ============================================================ */

typedef struct {
    volatile uint32_t CR1;         /* 0x00 */
    volatile uint32_t CR2;         /* 0x04 */
    volatile uint32_t CR3;         /* 0x08 */
    volatile uint32_t BRR;         /* 0x0C */
    volatile uint32_t GTPR;        /* 0x10 */
    volatile uint32_t RTOR;        /* 0x14 */
    volatile uint32_t RQR;         /* 0x18 */
    volatile uint32_t ISR;         /* 0x1C */
    volatile uint32_t ICR;         /* 0x20 */
    volatile uint32_t RDR;         /* 0x24 */
    volatile uint32_t TDR;         /* 0x28 */
    volatile uint32_t PRESC;       /* 0x2C */
} USART_Type;

#define USART1_BASE           0x40011000UL
#define USART1                ((USART_Type *)USART1_BASE)

/* USART CR1 bits */
#define USART_CR1_UE          (1UL <<  0)
#define USART_CR1_RE          (1UL <<  2)
#define USART_CR1_TE          (1UL <<  3)
#define USART_CR1_RXNEIE      (1UL <<  5)  /* RXFNEIE in FIFO mode per RM0399 §54.8.1 */
#define USART_CR1_FIFOEN      (1UL << 29)

/* USART ISR bits — in FIFO mode the names alias to TXE/RXNE per
 * RM0399 §54.8.10: TXE is TXFNF when FIFOEN=1, RXNE is RXFNE. */
#define USART_ISR_RXNE        (1UL <<  5)
#define USART_ISR_TXE         (1UL <<  7)
#define USART_ISR_ORE         (1UL <<  3)  /* Overrun error; cleared via ICR.ORECF */

/* USART ICR bits */
#define USART_ICR_ORECF       (1UL <<  3)

#ifdef __cplusplus
}
#endif

#endif /* SOS_STM32H747_MINIMAL_H */
