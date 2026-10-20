/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd.
 * @file h102_profile_control.h
 * @brief Define the fixed little-endian ABI between the software IIO device and root service.
 * @details Exchange preset requests and verified status without direct register operations.
 * @author LogicRF Technologies
 * @architect LogicRF
 * @email info@logicrf.com
 * @website https://www.logicrf.com
 * @version 1.0.0
 * @date 2026-10-08
 * @note Strings are NUL-terminated; structure size is independent of native ARM alignment.
 */
#ifndef H102_PROFILE_CONTROL_H
#define H102_PROFILE_CONTROL_H
#include <linux/types.h>
#define H102_CONTROL_ABI 1
#define H102_CONTROL_ID 64
#define H102_CONTROL_TEXT 2048
/* Phase values are ABI; queued is an internal kernel state only. */
enum h102_phase {
 H102_UNAVAILABLE, H102_READY, H102_APPLYING, H102_APPLIED,
 H102_ROLLED_BACK, H102_REJECTED, H102_QUEUED,
};
/* Request sequence increases monotonically within this module instance. */
struct h102_request {
 __le32 version, reserved;
 __le64 ticket;
 char id[H102_CONTROL_ID];
} __packed;
/* Active configuration is independently read back; reserved fields must be zero. */
struct h102_update {
 __le32 version, phase;
 __le64 ticket;
 __le32 configuration_id, reserved;
 char active[H102_CONTROL_ID], previous[H102_CONTROL_ID];
 char error[256], info[H102_CONTROL_TEXT], available[H102_CONTROL_TEXT];
} __packed;
#endif
