/* SOS-09-G MPU region table — auto-generated. Do not edit by hand. */
#include "sos_mpu.h"

const sos_mpu_region_t sis08d_c2_membrane_mpu_regions[] = {
    {
        .name = "membrane_command",
        .base_address = 0x40010000u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8d000000-0000-4000-8000-000000000001",
    },
    {
        .name = "membrane_status",
        .base_address = 0x40010020u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8d000000-0000-4000-8000-000000000002",
    },
    {
        .name = "transfer_mailbox_data",
        .base_address = 0x40010040u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8d000000-0000-4000-8000-000000000003",
    },
    {
        .name = "transfer_mailbox_notify",
        .base_address = 0x40010060u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8d000000-0000-4000-8000-000000000004",
    },
    {
        .name = "sram_window",
        .base_address = 0x40010080u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_NORMAL_WB_WA,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8d000000-0000-4000-8000-000000000005",
    },
};

const size_t sis08d_c2_membrane_mpu_regions_count = sizeof(sis08d_c2_membrane_mpu_regions) / sizeof(sis08d_c2_membrane_mpu_regions[0]);
