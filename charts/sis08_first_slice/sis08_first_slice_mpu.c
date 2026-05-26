/* SOS-09-G MPU region table — auto-generated. Do not edit by hand. */
#include "sos_mpu.h"

const sos_mpu_region_t sis08_first_slice_mpu_regions[] = {
    {
        .name = "fifo_data",
        .base_address = 0x40000000u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8b000000-0000-4000-8000-000000000001",
    },
    {
        .name = "fifo_status",
        .base_address = 0x40000020u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8b000000-0000-4000-8000-000000000002",
    },
    {
        .name = "fifo_control",
        .base_address = 0x40000040u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8b000000-0000-4000-8000-000000000003",
    },
    {
        .name = "mailbox_notify",
        .base_address = 0x40000060u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_DEVICE_NGNRNE,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8b000000-0000-4000-8000-000000000004",
    },
    {
        .name = "credit_budget",
        .base_address = 0x40000080u,
        .size_log2 = 5u,
        .attr = SOS_MPU_ATTR_NORMAL_WB_WA,
        .access = SOS_MPU_AP_PRIV_RW_UNPRIV_NONE,
        .xn = 1,
        .enable = 1,
        .srd = 0x00u,
        .channel_id = "8b000000-0000-4000-8000-000000000005",
    },
};

const size_t sis08_first_slice_mpu_regions_count = sizeof(sis08_first_slice_mpu_regions) / sizeof(sis08_first_slice_mpu_regions[0]);
