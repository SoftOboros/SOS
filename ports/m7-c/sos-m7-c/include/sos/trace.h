/* sos/trace.h — on-device JSONL trace writer (SOS-05 §6.2 / INV-S-PORT-9).
 *
 * Hand-rolled to match SOS-02 §7.1 field order byte-for-byte
 * (PCDN-SOS-05-008 parallels PCDN-SOS-04-008). Skeleton commit:
 * prototype only.
 */

#ifndef SOS_TRACE_H
#define SOS_TRACE_H

#include "sos/types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Forward declaration; the full Datamodel struct lives in src/kernel.c
 * (file-static) at v1. A future amendment MAY promote it to a public
 * type if cross-module access becomes necessary. */
struct sos_datamodel;

/* Serialise one TraceRecord (boot baseline or post-macrostep) into
 * `buf` and return the number of bytes written. The bytes are exactly
 * the SOS-02 §7.1 JSONL record (terminating `\n` included).
 *
 * `after_input_idx == -1` is the boot baseline; otherwise the index of
 * the just-consumed event from the wrapped vector input. */
size_t sos_trace_write_record(uint8_t *buf, size_t cap,
                              const struct sos_datamodel *dm,
                              int64_t after_input_idx);

#ifdef __cplusplus
}
#endif

#endif /* SOS_TRACE_H */
