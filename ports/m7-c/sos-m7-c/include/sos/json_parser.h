/* sos/json_parser.h — hand-rolled `no_std`-style JSON parser for the
 * SOS-05 M7 C reference port. Mirrors the canonical Rust parser at
 * `ports/m7-rust/sos-m7-rust/src/json_parser.rs`.
 *
 * Per SOS-04 §6.2.1 (firmware JSON parser narrative) and Amendment 009
 * (event-before-data field-order ratification). The parser is
 * incremental: the caller drains UART bytes into a ring buffer and
 * passes a contiguous window to `sos_vector_stream_try_step()`; the
 * function consumes a prefix and returns one parse step.
 *
 * Grammar accepted (per SOS-04 §6.2.1 + SOS-03 §6.2):
 *
 *   wrapper := '{' ( name_field ',' )? config_field ',' input_field '}' '\n'
 *            | '{' input_field ',' config_field '}' '\n'    -- order tolerant
 *            | '{' name_field ',' input_field ',' config_field '}' '\n'
 *
 * The parser is allocator-free, uses fixed-size stack scratch
 * (16 bytes for object keys, 32 bytes for event-name strings), and
 * surfaces malformed input via the typed `sos_parse_error_t` enum
 * rather than panicking.
 */

#ifndef SOS_JSON_PARSER_H
#define SOS_JSON_PARSER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "sos/event.h"
#include "sos/types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Maximum nested-brace depth the parser tolerates. Vector files have
 * real depth ~4 (wrapper → input array → event object → data object);
 * 16 is generous headroom. Exceeding it surfaces as
 * `SOS_PARSE_ERR_DEPTH_EXCEEDED`. */
#define SOS_PARSER_MAX_DEPTH 16

/* Vector-level configuration mirroring SOS-00 §7.1 `config` block.
 * Mirrors `VectorHeader` in the Rust port. The firmware uses these
 * to (informationally) validate against compile-time constants —
 * `SOS_MAX_TASKS` / `SOS_MAX_PRIO` / etc. — and halts if a vector
 * specifies bounds the at-HEAD invariants forbid. The parser itself
 * does not enforce the bound. */
typedef struct {
    size_t   max_tasks;   /* `MAX_TASKS` */
    size_t   max_prio;    /* `MAX_PRIO`  */
    size_t   max_sems;    /* `MAX_SEMS`  */
    size_t   max_queues;  /* `MAX_QUEUES`*/
    size_t   q_depth;     /* `Q_DEPTH`   */
    uint32_t tick_hz;     /* `SOS_TICK_HZ` */
} sos_vector_header_t;

/* Parser error class — mirrors `ParseError` in the Rust port. */
typedef enum {
    SOS_PARSE_ERR_NONE                = 0,
    SOS_PARSE_ERR_UNEXPECTED_BYTE     = 1,
    SOS_PARSE_ERR_UNEXPECTED_END      = 2,
    SOS_PARSE_ERR_DEPTH_EXCEEDED      = 3,
    SOS_PARSE_ERR_UNKNOWN_EVENT_NAME  = 4,
    SOS_PARSE_ERR_UNKNOWN_FIELD       = 5,
    SOS_PARSE_ERR_DUPLICATE_FIELD     = 6,
    SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE = 7,
    SOS_PARSE_ERR_BAD_EVENT_SHAPE     = 8,
    SOS_PARSE_ERR_BAD_WRAPPER_SHAPE   = 9
} sos_parse_error_t;

/* Parse-step discriminant — mirrors `ParseStep` in the Rust port. */
typedef enum {
    SOS_PARSE_STEP_NEED_MORE_INPUT = 0,
    SOS_PARSE_STEP_VECTOR_HEADER   = 1,
    SOS_PARSE_STEP_EVENT           = 2,
    SOS_PARSE_STEP_END_OF_INPUT    = 3,
    SOS_PARSE_STEP_ERROR           = 4
} sos_parse_step_kind_t;

/* One parse step result. `consumed` is the byte-count the caller should
 * advance its read cursor by; on `NEED_MORE_INPUT` it is zero.
 *
 * `header` is valid only when `kind == SOS_PARSE_STEP_VECTOR_HEADER`;
 * `event` only when `kind == SOS_PARSE_STEP_EVENT`; `error_kind` +
 * `error_offset` only when `kind == SOS_PARSE_STEP_ERROR`. Other union-
 * arm fields are uninitialised on those paths and MUST NOT be read. */
typedef struct {
    sos_parse_step_kind_t kind;
    size_t                consumed;
    sos_vector_header_t   header;
    sos_event_t           event;
    sos_parse_error_t     error_kind;
    size_t                error_offset;
} sos_parse_step_t;

/* Top-level parser state — internal. Declared in the header so the
 * caller can allocate `sos_vector_stream_t` by value; consumers MUST
 * NOT inspect or mutate these fields directly. */
typedef enum {
    SOS_VS_EXPECT_WRAPPER_OPEN          = 0,
    SOS_VS_IN_WRAPPER_EXPECT_KEY        = 1,
    SOS_VS_IN_INPUT_ARRAY_EXPECT_ELEMENT = 2,
    SOS_VS_IN_INPUT_ARRAY_BETWEEN_ELEMENTS = 3,
    SOS_VS_AWAITING_WRAPPER_CLOSE       = 4,
    SOS_VS_DONE                         = 5
} sos_vector_stream_state_t;

/* Incremental wrapped-vector parser. One per vector ingress cycle.
 *
 * Caller pattern (mirrors `VectorStream::try_step` in the Rust port):
 *
 *   sos_vector_stream_t vs;
 *   sos_vector_stream_init(&vs);
 *   while (more_bytes) {
 *       sos_parse_step_t step =
 *           sos_vector_stream_try_step(&vs, ringbuf_head, ringbuf_len);
 *       switch (step.kind) {
 *           case SOS_PARSE_STEP_NEED_MORE_INPUT: ...
 *           case SOS_PARSE_STEP_VECTOR_HEADER:   ringbuf_head += step.consumed; ...
 *           case SOS_PARSE_STEP_EVENT:           ringbuf_head += step.consumed; ...
 *           case SOS_PARSE_STEP_END_OF_INPUT:    break;
 *           case SOS_PARSE_STEP_ERROR:           halt + done sentinel;
 *       }
 *   }
 */
typedef struct {
    /* Top-level state-machine cursor. */
    sos_vector_stream_state_t state;
    /* Nested-brace depth tracker; reaches 1 inside the wrapper. */
    uint8_t depth;
    /* Bitfield of wrapper-level keys already consumed.
     * Bit 0 = `name`, bit 1 = `config`, bit 2 = `input`. */
    uint8_t seen_wrapper_keys;
} sos_vector_stream_t;

/* Initialise a fresh parser at the start of a new vector. The returned
 * parser expects the next byte to be (after optional whitespace) the
 * wrapper's opening `{`. */
void sos_vector_stream_init(sos_vector_stream_t *vs);

/* Consume bytes from the start of `buf` (length `len`) and return the
 * next parse step. On `SOS_PARSE_STEP_NEED_MORE_INPUT`,
 * `step.consumed == 0`. The parser allocates nothing, never panics on
 * malformed input, and treats `buf == NULL || len == 0` as the
 * "need more input" case. */
sos_parse_step_t sos_vector_stream_try_step(sos_vector_stream_t *vs,
                                            const uint8_t *buf,
                                            size_t len);

#ifdef __cplusplus
}
#endif

#endif /* SOS_JSON_PARSER_H */
