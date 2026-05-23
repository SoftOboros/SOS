/* json_parser.c — hand-rolled JSON parser for SOS-05 M7 C reference.
 *
 * Mirrors `ports/m7-rust/sos-m7-rust/src/json_parser.rs` 1:1 on grammar
 * acceptance, error class, and incremental API. Per PCDN-SOS-04-008
 * (hand-rolled writer) the input-side parser is symmetrically hand-
 * rolled: no third-party JSON library, no allocator, no `<stdio.h>`
 * sscanf, no Unicode escape support.
 *
 * The parser is a state-machine over the wrapped-vector grammar:
 *
 *   wrapper := '{' ( name_field ',' )? config_field ',' input_field '}' '\n'
 *
 * where the three top-level wrapper keys (`name`, `config`, `input`)
 * are order-tolerant. `name` is tolerated and its value discarded
 * (per Wave 7 agent D); `config` and `input` are required. Per
 * SOS-04 Amendment 009, within each event object the `event` field
 * MUST appear before `data` (this parser does not buffer the data
 * object's bytes; if `data` arrives first, it errors with
 * `BAD_EVENT_SHAPE`).
 *
 * All `static` helpers below the public-API split mirror the structure
 * of the Rust file; names are translated from snake-case Rust to the
 * same snake-case in C (the Rust file already uses snake_case for
 * functions). Inline `cursor_*` helpers are the C analogue of the
 * Rust `Cursor<'a>` struct + methods.
 */

#include "sos/json_parser.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* ----- Cursor: peek-and-advance over a contiguous byte buffer ----- */

typedef struct {
    const uint8_t *buf;
    size_t         len;
    size_t         pos;
} cursor_t;

static inline void cursor_init(cursor_t *c, const uint8_t *buf, size_t len)
{
    c->buf = buf;
    c->len = len;
    c->pos = 0;
}

/* Returns `true` and writes the next byte to `*out` without advancing.
 * Returns `false` if at end-of-buffer. */
static inline bool cursor_peek(const cursor_t *c, uint8_t *out)
{
    if (c->pos >= c->len) {
        return false;
    }
    *out = c->buf[c->pos];
    return true;
}

/* Advance one byte. Caller MUST have peeked successfully first. */
static inline void cursor_bump(cursor_t *c)
{
    c->pos += 1;
}

/* Skip ASCII whitespace (space, tab, LF, CR) per RFC 8259 §2. */
static void cursor_skip_ws(cursor_t *c)
{
    uint8_t b;
    while (cursor_peek(c, &b)) {
        if (b == ' ' || b == '\t' || b == '\n' || b == '\r') {
            cursor_bump(c);
        } else {
            break;
        }
    }
}

/* Try to consume a specific byte. Returns:
 *   1  — matched + advanced;
 *   0  — peeked but mismatched (no advance);
 *  -1  — buffer exhausted. */
static int cursor_expect(cursor_t *c, uint8_t want)
{
    uint8_t b;
    if (!cursor_peek(c, &b)) {
        return -1;
    }
    if (b == want) {
        cursor_bump(c);
        return 1;
    }
    return 0;
}

/* ----- Wrapper-key seen-bitfield ----- */

#define SEEN_NAME   ((uint8_t)0x01)
#define SEEN_CONFIG ((uint8_t)0x02)
#define SEEN_INPUT  ((uint8_t)0x04)

/* ----- Step builders (small helpers to keep call sites terse) ----- */

static sos_parse_step_t step_need_more_input(void)
{
    sos_parse_step_t s = {0};
    s.kind = SOS_PARSE_STEP_NEED_MORE_INPUT;
    s.consumed = 0;
    return s;
}

static sos_parse_step_t step_error(sos_parse_error_t kind, size_t offset)
{
    sos_parse_step_t s = {0};
    s.kind = SOS_PARSE_STEP_ERROR;
    s.consumed = 0;
    s.error_kind = kind;
    s.error_offset = offset;
    return s;
}

static sos_parse_step_t step_vector_header(const sos_vector_header_t *hdr,
                                           size_t consumed)
{
    sos_parse_step_t s = {0};
    s.kind = SOS_PARSE_STEP_VECTOR_HEADER;
    s.consumed = consumed;
    s.header = *hdr;
    return s;
}

static sos_parse_step_t step_event(const sos_event_t *ev, size_t consumed)
{
    sos_parse_step_t s = {0};
    s.kind = SOS_PARSE_STEP_EVENT;
    s.consumed = consumed;
    s.event = *ev;
    return s;
}

static sos_parse_step_t step_end_of_input(size_t consumed)
{
    sos_parse_step_t s = {0};
    s.kind = SOS_PARSE_STEP_END_OF_INPUT;
    s.consumed = consumed;
    return s;
}

/* ----- Number parsing ----- */

/* Internal three-state result for sub-parsers that may exhaust their
 * input mid-token. Mirrors Rust's `Result<Option<T>, ParseError>`. */
typedef enum {
    PR_OK    = 0,
    PR_NEED  = 1,
    PR_ERROR = 2
} parse_rc_t;

/* Parse a signed integer literal from the cursor. Returns:
 *   PR_OK    — `*out` holds the parsed value; cursor advanced past it;
 *   PR_NEED  — buffer exhausted mid-number (cursor position is
 *              unspecified — the caller MUST treat the call as a
 *              "no consumption" path: the outer state machine returns
 *              NEED_MORE_INPUT with consumed=0);
 *   PR_ERROR — `*err` holds the error class.
 *
 * Accepts:    `0`, `42`, `-7`.
 * Rejects:    leading zeros (`-0123`), lone `-`, plus signs,
 *             floating-point dots/exponents.
 */
static parse_rc_t parse_i64(cursor_t *c, int64_t *out, sos_parse_error_t *err)
{
    bool neg = false;
    uint8_t b;
    if (!cursor_peek(c, &b)) {
        return PR_NEED;
    }
    if (b == '-') {
        neg = true;
        cursor_bump(c);
        if (!cursor_peek(c, &b)) {
            return PR_NEED;
        }
    }

    if (b < '0' || b > '9') {
        *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
        return PR_ERROR;
    }

    /* RFC 8259 §6: a leading `0` MUST be the entire integer part. */
    if (b == '0') {
        cursor_bump(c);
        uint8_t next;
        if (cursor_peek(c, &next)) {
            if (next >= '0' && next <= '9') {
                *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
                return PR_ERROR;
            }
        }
        *out = 0;
        return PR_OK;
    }

    int64_t acc = 0;
    while (cursor_peek(c, &b)) {
        if (b < '0' || b > '9') {
            break;
        }
        int64_t digit = (int64_t)(b - (uint8_t)'0');
        /* Build positive then negate at the end so i64::MIN is
         * reachable (its absolute value overflows i64::MAX). */
        if (neg) {
            /* acc = acc * 10 - digit, checked. */
            if (acc < (INT64_MIN / 10)) {
                *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
                return PR_ERROR;
            }
            int64_t mul = acc * 10;
            if (mul < INT64_MIN + digit) {
                *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
                return PR_ERROR;
            }
            acc = mul - digit;
        } else {
            if (acc > (INT64_MAX / 10)) {
                *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
                return PR_ERROR;
            }
            int64_t mul = acc * 10;
            if (mul > INT64_MAX - digit) {
                *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
                return PR_ERROR;
            }
            acc = mul + digit;
        }
        cursor_bump(c);
    }

    *out = acc;
    return PR_OK;
}

/* Match a literal byte sequence (`true`, `false`, `null`). Returns
 *   PR_OK    — full match, cursor advanced;
 *   PR_NEED  — buffer exhausted mid-literal;
 *   PR_ERROR — mismatch encountered (caller decides error class). */
static parse_rc_t match_literal(cursor_t *c, const char *lit)
{
    for (const char *p = lit; *p != '\0'; ++p) {
        uint8_t b;
        if (!cursor_peek(c, &b)) {
            return PR_NEED;
        }
        if (b != (uint8_t)*p) {
            return PR_ERROR;
        }
        cursor_bump(c);
    }
    return PR_OK;
}

/* Parse either an integer or the literal `null`. On `null`, sets
 * `*is_null = true` and leaves `*out` untouched. Used for `from_tid`
 * and the `data` field of an event.
 */
static parse_rc_t parse_i64_or_null(cursor_t *c,
                                    int64_t *out,
                                    bool *is_null,
                                    sos_parse_error_t *err)
{
    cursor_skip_ws(c);
    uint8_t b;
    if (!cursor_peek(c, &b)) {
        return PR_NEED;
    }
    *is_null = false;
    if (b == 'n') {
        parse_rc_t rc = match_literal(c, "null");
        if (rc == PR_NEED) return PR_NEED;
        if (rc == PR_ERROR) {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }
        *is_null = true;
        return PR_OK;
    }
    return parse_i64(c, out, err);
}

/* ----- String parsing ----- */

/* Parse a JSON string starting at the next byte (which MUST be `"`).
 * Writes the decoded bytes into `out[0..]` up to `out_cap` bytes; sets
 * `*out_len` on success. Unicode escapes (`\u####`) are rejected as
 * unexpected bytes (SOS grammar disallows them).
 *
 * Returns PR_OK / PR_NEED / PR_ERROR. PR_ERROR with `*err =
 * NUMBER_OUT_OF_RANGE` means the decoded string overflowed `out_cap`. */
static parse_rc_t parse_string_into(cursor_t *c,
                                    uint8_t *out,
                                    size_t out_cap,
                                    size_t *out_len,
                                    sos_parse_error_t *err)
{
    uint8_t b;
    if (!cursor_peek(c, &b)) {
        return PR_NEED;
    }
    if (b != '"') {
        *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
        return PR_ERROR;
    }
    cursor_bump(c);

    size_t n = 0;
    for (;;) {
        if (!cursor_peek(c, &b)) {
            return PR_NEED;
        }
        cursor_bump(c);
        if (b == '"') {
            *out_len = n;
            return PR_OK;
        }
        if (b == '\\') {
            uint8_t esc;
            if (!cursor_peek(c, &esc)) {
                return PR_NEED;
            }
            cursor_bump(c);
            uint8_t decoded;
            switch (esc) {
                case '"':  decoded = '"';  break;
                case '\\': decoded = '\\'; break;
                case '/':  decoded = '/';  break;
                case 'n':  decoded = '\n'; break;
                case 't':  decoded = '\t'; break;
                case 'r':  decoded = '\r'; break;
                case 'b':  decoded = 0x08; break;
                case 'f':  decoded = 0x0C; break;
                case 'u':  /* unsupported per SOS grammar */
                default:
                    *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
                    return PR_ERROR;
            }
            if (n >= out_cap) {
                *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
                return PR_ERROR;
            }
            out[n++] = decoded;
        } else {
            if (n >= out_cap) {
                *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
                return PR_ERROR;
            }
            out[n++] = b;
        }
    }
}

/* Skip a JSON string value (consume opening `"`, body, closing `"`)
 * without decoding. Returns PR_OK / PR_NEED / PR_ERROR. */
static parse_rc_t skip_string_value(cursor_t *c, sos_parse_error_t *err)
{
    uint8_t b;
    if (!cursor_peek(c, &b)) {
        return PR_NEED;
    }
    if (b != '"') {
        *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
        return PR_ERROR;
    }
    cursor_bump(c);
    for (;;) {
        if (!cursor_peek(c, &b)) {
            return PR_NEED;
        }
        cursor_bump(c);
        if (b == '"') {
            return PR_OK;
        }
        if (b == '\\') {
            uint8_t esc;
            if (!cursor_peek(c, &esc)) {
                return PR_NEED;
            }
            if (esc == 'u') {
                *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
                return PR_ERROR;
            }
            cursor_bump(c);
        }
    }
}

/* ----- Key-name compare ----- */

/* Compares a parsed key (bytes in `key[0..key_len]`) to a known C
 * string. Returns true on match. */
static bool key_eq(const uint8_t *key, size_t key_len, const char *known)
{
    size_t i;
    for (i = 0; i < key_len; i++) {
        if (known[i] == '\0') return false;
        if (key[i] != (uint8_t)known[i]) return false;
    }
    return known[i] == '\0';
}

/* ----- Range-narrowing helpers (i64 → narrower type) ----- */

static parse_rc_t usize_from_i64(int64_t v, size_t *out, sos_parse_error_t *err)
{
    if (v < 0) {
        *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
        return PR_ERROR;
    }
#if SIZE_MAX < INT64_MAX
    if ((uint64_t)v > (uint64_t)SIZE_MAX) {
        *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
        return PR_ERROR;
    }
#endif
    *out = (size_t)v;
    return PR_OK;
}

static parse_rc_t u32_from_i64(int64_t v, uint32_t *out, sos_parse_error_t *err)
{
    if (v < 0 || v > (int64_t)UINT32_MAX) {
        *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
        return PR_ERROR;
    }
    *out = (uint32_t)v;
    return PR_OK;
}

static parse_rc_t i16_from_i64(int64_t v, int16_t *out, sos_parse_error_t *err)
{
    if (v < (int64_t)INT16_MIN || v > (int64_t)INT16_MAX) {
        *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
        return PR_ERROR;
    }
    *out = (int16_t)v;
    return PR_OK;
}

static parse_rc_t u8_from_i64(int64_t v, uint8_t *out, sos_parse_error_t *err)
{
    if (v < 0 || v > (int64_t)UINT8_MAX) {
        *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
        return PR_ERROR;
    }
    *out = (uint8_t)v;
    return PR_OK;
}

/* ----- Config object parsing ----- */

/* Parse the `config` value object starting at the next byte (which
 * MUST be `{`). Populates `*hdr` on success.
 *
 * Returns PR_OK / PR_NEED / PR_ERROR. PR_NEED preserves cursor
 * position-isn't-meaningful semantics — the outer state machine emits
 * NEED_MORE_INPUT with consumed=0. */
static parse_rc_t parse_config_object(cursor_t *c,
                                      sos_vector_header_t *hdr,
                                      sos_parse_error_t *err)
{
    cursor_skip_ws(c);
    uint8_t b;
    if (!cursor_peek(c, &b)) return PR_NEED;
    if (b != '{') {
        *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
        return PR_ERROR;
    }
    cursor_bump(c);

    /* Six required scalar keys; track which we've seen. */
    enum {
        K_MAX_TASKS  = 1u << 0,
        K_MAX_PRIO   = 1u << 1,
        K_MAX_SEMS   = 1u << 2,
        K_MAX_QUEUES = 1u << 3,
        K_Q_DEPTH    = 1u << 4,
        K_TICK_HZ    = 1u << 5
    };
    const uint8_t ALL =
        K_MAX_TASKS | K_MAX_PRIO | K_MAX_SEMS |
        K_MAX_QUEUES | K_Q_DEPTH | K_TICK_HZ;

    uint8_t seen = 0;
    int64_t max_tasks_v  = 0;
    int64_t max_prio_v   = 0;
    int64_t max_sems_v   = 0;
    int64_t max_queues_v = 0;
    int64_t q_depth_v    = 0;
    int64_t tick_hz_v    = 0;

    for (;;) {
        cursor_skip_ws(c);
        if (!cursor_peek(c, &b)) return PR_NEED;
        if (b == '}') { cursor_bump(c); break; }
        if (b == ',') { cursor_bump(c); continue; }
        if (b != '"') {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }

        uint8_t key_buf[16];
        size_t  key_len;
        parse_rc_t rc = parse_string_into(c, key_buf, sizeof key_buf,
                                          &key_len, err);
        if (rc != PR_OK) return rc;

        cursor_skip_ws(c);
        int e = cursor_expect(c, ':');
        if (e < 0) return PR_NEED;
        if (e == 0) {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }
        cursor_skip_ws(c);

        int64_t v;
        rc = parse_i64(c, &v, err);
        if (rc != PR_OK) return rc;

        uint8_t bit;
        if      (key_eq(key_buf, key_len, "max_tasks"))  { max_tasks_v  = v; bit = K_MAX_TASKS; }
        else if (key_eq(key_buf, key_len, "max_prio"))   { max_prio_v   = v; bit = K_MAX_PRIO; }
        else if (key_eq(key_buf, key_len, "max_sems"))   { max_sems_v   = v; bit = K_MAX_SEMS; }
        else if (key_eq(key_buf, key_len, "max_queues")) { max_queues_v = v; bit = K_MAX_QUEUES; }
        else if (key_eq(key_buf, key_len, "q_depth"))    { q_depth_v    = v; bit = K_Q_DEPTH; }
        else if (key_eq(key_buf, key_len, "tick_hz"))    { tick_hz_v    = v; bit = K_TICK_HZ; }
        else {
            *err = SOS_PARSE_ERR_UNKNOWN_FIELD;
            return PR_ERROR;
        }
        if (seen & bit) {
            *err = SOS_PARSE_ERR_DUPLICATE_FIELD;
            return PR_ERROR;
        }
        seen |= bit;
    }

    if (seen != ALL) {
        *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
        return PR_ERROR;
    }

    /* Range-check and pack. */
    parse_rc_t rc;
    rc = usize_from_i64(max_tasks_v,  &hdr->max_tasks,  err); if (rc != PR_OK) return rc;
    rc = usize_from_i64(max_prio_v,   &hdr->max_prio,   err); if (rc != PR_OK) return rc;
    rc = usize_from_i64(max_sems_v,   &hdr->max_sems,   err); if (rc != PR_OK) return rc;
    rc = usize_from_i64(max_queues_v, &hdr->max_queues, err); if (rc != PR_OK) return rc;
    rc = usize_from_i64(q_depth_v,    &hdr->q_depth,    err); if (rc != PR_OK) return rc;
    rc = u32_from_i64  (tick_hz_v,    &hdr->tick_hz,    err); if (rc != PR_OK) return rc;
    return PR_OK;
}

/* ----- Event-name dispatch ----- */

/* SOS-01 §5.3 — the closed 18-variant set. Flat dispatch table:
 * 18 string compares max is a few hundred cycles on M7, well under
 * the parser's per-event budget. */
struct name_entry {
    const char       *str;
    sos_event_name_t  name;
};

static const struct name_entry NAME_TABLE[] = {
    { "task.create",         SOS_EVN_TASK_CREATE         },
    { "task.delay",          SOS_EVN_TASK_DELAY          },
    { "task.yield",          SOS_EVN_TASK_YIELD          },
    { "task.suspend",        SOS_EVN_TASK_SUSPEND        },
    { "task.resume",         SOS_EVN_TASK_RESUME         },
    { "sem.create",          SOS_EVN_SEM_CREATE          },
    { "sem.take",            SOS_EVN_SEM_TAKE            },
    { "sem.give",            SOS_EVN_SEM_GIVE            },
    { "sem.give_from_isr",   SOS_EVN_SEM_GIVE_FROM_ISR   },
    { "queue.create",        SOS_EVN_QUEUE_CREATE        },
    { "queue.send",          SOS_EVN_QUEUE_SEND          },
    { "queue.receive",       SOS_EVN_QUEUE_RECEIVE       },
    { "queue.send_from_isr", SOS_EVN_QUEUE_SEND_FROM_ISR },
    { "sys.tick",            SOS_EVN_SYS_TICK            },
    { "crit.enter",          SOS_EVN_CRIT_ENTER          },
    { "crit.exit",           SOS_EVN_CRIT_EXIT           },
    { "sched.suspend",       SOS_EVN_SCHED_SUSPEND       },
    { "sched.resume",        SOS_EVN_SCHED_RESUME        }
};

#define NAME_TABLE_LEN (sizeof NAME_TABLE / sizeof NAME_TABLE[0])

static bool resolve_event_name(const uint8_t *s, size_t len,
                               sos_event_name_t *out)
{
    for (size_t i = 0; i < NAME_TABLE_LEN; i++) {
        if (key_eq(s, len, NAME_TABLE[i].str)) {
            *out = NAME_TABLE[i].name;
            return true;
        }
    }
    return false;
}

/* ----- Event-data parsing (typed payload per EventName) ----- */

/* Per-field "seen" bits for the inner data object. Mirrors the option-
 * pattern in the Rust file (`id_v: Option<i64>` etc.) but rolled into
 * one bitfield + parallel value array for terseness. */
enum {
    DK_ID      = 1u << 0,
    DK_PRIO    = 1u << 1,
    DK_TICKS   = 1u << 2,
    DK_SID     = 1u << 3,
    DK_QID     = 1u << 4,
    DK_MSG     = 1u << 5,
    DK_TIMEOUT = 1u << 6,
    DK_CAP     = 1u << 7,
    DK_INITIAL = 1u << 8,
    DK_MAX     = 1u << 9
};

struct data_fields {
    uint16_t present;
    int64_t  id;
    int64_t  prio;
    int64_t  ticks;
    int64_t  sid;
    int64_t  qid;
    int64_t  msg;
    int64_t  timeout;
    int64_t  cap;
    int64_t  initial;
    int64_t  max;
};

/* Returns true iff `f->present` includes every bit in `required` and
 * none of the bits in `forbidden`. */
static bool data_fields_only(const struct data_fields *f,
                             uint16_t required,
                             uint16_t forbidden)
{
    if ((f->present & required) != required) return false;
    if ((f->present & forbidden) != 0)       return false;
    return true;
}

static parse_rc_t parse_event_data(cursor_t *c,
                                   sos_event_name_t name,
                                   sos_event_data_t *out,
                                   sos_parse_error_t *err)
{
    cursor_skip_ws(c);
    uint8_t b;
    if (!cursor_peek(c, &b)) return PR_NEED;

    /* `null` data → SOS_EVD_NONE (valid only for no-payload events). */
    if (b == 'n') {
        parse_rc_t rc = match_literal(c, "null");
        if (rc == PR_NEED) return PR_NEED;
        if (rc == PR_ERROR) {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }
        out->tag = SOS_EVD_NONE;
        return PR_OK;
    }

    if (b != '{') {
        *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
        return PR_ERROR;
    }
    cursor_bump(c);

    struct data_fields f = {0};

    for (;;) {
        cursor_skip_ws(c);
        if (!cursor_peek(c, &b)) return PR_NEED;
        if (b == '}') { cursor_bump(c); break; }
        if (b == ',') { cursor_bump(c); continue; }
        if (b != '"') {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }

        uint8_t key_buf[16];
        size_t  key_len;
        parse_rc_t rc = parse_string_into(c, key_buf, sizeof key_buf,
                                          &key_len, err);
        if (rc != PR_OK) return rc;

        cursor_skip_ws(c);
        int e = cursor_expect(c, ':');
        if (e < 0) return PR_NEED;
        if (e == 0) {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }
        cursor_skip_ws(c);

        int64_t v;
        rc = parse_i64(c, &v, err);
        if (rc != PR_OK) return rc;

        uint16_t bit;
        int64_t *slot;
        if      (key_eq(key_buf, key_len, "id"))      { bit = DK_ID;      slot = &f.id; }
        else if (key_eq(key_buf, key_len, "prio"))    { bit = DK_PRIO;    slot = &f.prio; }
        else if (key_eq(key_buf, key_len, "ticks"))   { bit = DK_TICKS;   slot = &f.ticks; }
        else if (key_eq(key_buf, key_len, "sid"))     { bit = DK_SID;     slot = &f.sid; }
        else if (key_eq(key_buf, key_len, "qid"))     { bit = DK_QID;     slot = &f.qid; }
        else if (key_eq(key_buf, key_len, "msg"))     { bit = DK_MSG;     slot = &f.msg; }
        else if (key_eq(key_buf, key_len, "timeout")) { bit = DK_TIMEOUT; slot = &f.timeout; }
        else if (key_eq(key_buf, key_len, "cap"))     { bit = DK_CAP;     slot = &f.cap; }
        else if (key_eq(key_buf, key_len, "initial")) { bit = DK_INITIAL; slot = &f.initial; }
        else if (key_eq(key_buf, key_len, "max"))     { bit = DK_MAX;     slot = &f.max; }
        else {
            *err = SOS_PARSE_ERR_UNKNOWN_FIELD;
            return PR_ERROR;
        }
        if (f.present & bit) {
            *err = SOS_PARSE_ERR_DUPLICATE_FIELD;
            return PR_ERROR;
        }
        f.present |= bit;
        *slot = v;
    }

    /* Dispatch on event name and populate the typed variant. */
    parse_rc_t rc;
    switch (name) {
        case SOS_EVN_TASK_CREATE: {
            if (!data_fields_only(&f, DK_ID | DK_PRIO,
                  DK_TICKS | DK_SID | DK_QID | DK_MSG | DK_TIMEOUT |
                  DK_CAP | DK_INITIAL | DK_MAX)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_TASK_CREATE;
            rc = i16_from_i64(f.id, &out->u.task_create.id, err);
            if (rc != PR_OK) return rc;
            rc = u8_from_i64(f.prio, &out->u.task_create.prio, err);
            if (rc != PR_OK) return rc;
            return PR_OK;
        }
        case SOS_EVN_TASK_DELAY: {
            if (!data_fields_only(&f, DK_TICKS,
                  DK_ID | DK_PRIO | DK_SID | DK_QID | DK_MSG |
                  DK_TIMEOUT | DK_CAP | DK_INITIAL | DK_MAX)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_TASK_DELAY;
            out->u.task_delay.ticks = f.ticks;
            return PR_OK;
        }
        case SOS_EVN_TASK_SUSPEND:
        case SOS_EVN_TASK_RESUME: {
            if (!data_fields_only(&f, DK_ID,
                  DK_PRIO | DK_TICKS | DK_SID | DK_QID | DK_MSG |
                  DK_TIMEOUT | DK_CAP | DK_INITIAL | DK_MAX)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_TASK_ID;
            rc = i16_from_i64(f.id, &out->u.task_id.id, err);
            if (rc != PR_OK) return rc;
            return PR_OK;
        }
        case SOS_EVN_SEM_CREATE: {
            if (!data_fields_only(&f, DK_ID | DK_INITIAL | DK_MAX,
                  DK_PRIO | DK_TICKS | DK_SID | DK_QID | DK_MSG |
                  DK_TIMEOUT | DK_CAP)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_SEM_CREATE;
            rc = i16_from_i64(f.id, &out->u.sem_create.id, err);
            if (rc != PR_OK) return rc;
            rc = u32_from_i64(f.initial, &out->u.sem_create.initial, err);
            if (rc != PR_OK) return rc;
            rc = u32_from_i64(f.max, &out->u.sem_create.max, err);
            if (rc != PR_OK) return rc;
            return PR_OK;
        }
        case SOS_EVN_SEM_TAKE:
        case SOS_EVN_SEM_GIVE:
        case SOS_EVN_SEM_GIVE_FROM_ISR: {
            bool timeout_required = (name == SOS_EVN_SEM_TAKE);
            if (!(f.present & DK_SID)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            if (timeout_required && !(f.present & DK_TIMEOUT)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            uint16_t forbid = DK_ID | DK_PRIO | DK_TICKS | DK_QID |
                              DK_MSG | DK_CAP | DK_INITIAL | DK_MAX;
            if (f.present & forbid) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_SEM_OP;
            rc = i16_from_i64(f.sid, &out->u.sem_op.sid, err);
            if (rc != PR_OK) return rc;
            out->u.sem_op.timeout = (f.present & DK_TIMEOUT) ? f.timeout : 0;
            return PR_OK;
        }
        case SOS_EVN_QUEUE_CREATE: {
            if (!data_fields_only(&f, DK_ID | DK_CAP,
                  DK_PRIO | DK_TICKS | DK_SID | DK_QID | DK_MSG |
                  DK_TIMEOUT | DK_INITIAL | DK_MAX)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_QUEUE_CREATE;
            rc = i16_from_i64(f.id, &out->u.queue_create.id, err);
            if (rc != PR_OK) return rc;
            rc = u32_from_i64(f.cap, &out->u.queue_create.cap, err);
            if (rc != PR_OK) return rc;
            return PR_OK;
        }
        case SOS_EVN_QUEUE_SEND:
        case SOS_EVN_QUEUE_SEND_FROM_ISR: {
            bool timeout_required = (name == SOS_EVN_QUEUE_SEND);
            if (!(f.present & DK_QID) || !(f.present & DK_MSG)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            if (timeout_required && !(f.present & DK_TIMEOUT)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            uint16_t forbid = DK_ID | DK_PRIO | DK_TICKS | DK_SID |
                              DK_CAP | DK_INITIAL | DK_MAX;
            if (f.present & forbid) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_QUEUE_SEND;
            rc = i16_from_i64(f.qid, &out->u.queue_send.qid, err);
            if (rc != PR_OK) return rc;
            out->u.queue_send.msg = f.msg;
            out->u.queue_send.timeout =
                (f.present & DK_TIMEOUT) ? f.timeout : 0;
            return PR_OK;
        }
        case SOS_EVN_QUEUE_RECEIVE: {
            if (!data_fields_only(&f, DK_QID | DK_TIMEOUT,
                  DK_ID | DK_PRIO | DK_TICKS | DK_SID | DK_MSG |
                  DK_CAP | DK_INITIAL | DK_MAX)) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_QUEUE_RECEIVE;
            rc = i16_from_i64(f.qid, &out->u.queue_receive.qid, err);
            if (rc != PR_OK) return rc;
            out->u.queue_receive.timeout = f.timeout;
            return PR_OK;
        }
        case SOS_EVN_TASK_YIELD:
        case SOS_EVN_SYS_TICK:
        case SOS_EVN_CRIT_ENTER:
        case SOS_EVN_CRIT_EXIT:
        case SOS_EVN_SCHED_SUSPEND:
        case SOS_EVN_SCHED_RESUME: {
            if (f.present != 0) {
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            out->tag = SOS_EVD_NONE;
            return PR_OK;
        }
    }
    /* Defensive — every variant is handled above. */
    *err = SOS_PARSE_ERR_UNKNOWN_EVENT_NAME;
    return PR_ERROR;
}

/* ----- name→data shape cross-check (mirrors validate_data_for_name) ----- */

static bool validate_data_for_name(sos_event_name_t name,
                                   const sos_event_data_t *data)
{
    switch (name) {
        case SOS_EVN_TASK_YIELD:
        case SOS_EVN_SYS_TICK:
        case SOS_EVN_CRIT_ENTER:
        case SOS_EVN_CRIT_EXIT:
        case SOS_EVN_SCHED_SUSPEND:
        case SOS_EVN_SCHED_RESUME:
            return data->tag == SOS_EVD_NONE;
        case SOS_EVN_TASK_CREATE:  return data->tag == SOS_EVD_TASK_CREATE;
        case SOS_EVN_TASK_DELAY:   return data->tag == SOS_EVD_TASK_DELAY;
        case SOS_EVN_TASK_SUSPEND:
        case SOS_EVN_TASK_RESUME:  return data->tag == SOS_EVD_TASK_ID;
        case SOS_EVN_SEM_CREATE:   return data->tag == SOS_EVD_SEM_CREATE;
        case SOS_EVN_SEM_TAKE:
        case SOS_EVN_SEM_GIVE:
        case SOS_EVN_SEM_GIVE_FROM_ISR: return data->tag == SOS_EVD_SEM_OP;
        case SOS_EVN_QUEUE_CREATE: return data->tag == SOS_EVD_QUEUE_CREATE;
        case SOS_EVN_QUEUE_SEND:
        case SOS_EVN_QUEUE_SEND_FROM_ISR: return data->tag == SOS_EVD_QUEUE_SEND;
        case SOS_EVN_QUEUE_RECEIVE: return data->tag == SOS_EVD_QUEUE_RECEIVE;
    }
    return false;
}

/* ----- Event object parsing ----- */

/* Parse one event object starting at the next byte (which MUST be
 * `{`). Populates `*ev` on success. */
static parse_rc_t parse_event_object(cursor_t *c,
                                     sos_event_t *ev,
                                     sos_parse_error_t *err)
{
    cursor_skip_ws(c);
    uint8_t b;
    if (!cursor_peek(c, &b)) return PR_NEED;
    if (b != '{') {
        *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
        return PR_ERROR;
    }
    cursor_bump(c);

    bool seen_event = false;
    bool seen_data  = false;
    bool seen_from_tid = false;

    bool             have_name = false;
    sos_event_name_t name = SOS_EVN_TASK_YIELD;  /* placeholder */
    sos_event_data_t data;
    data.tag = SOS_EVD_NONE;
    bool from_tid_present_from_field = false;  /* explicit null still
                                                * counts as "no tid" */
    int64_t from_tid_v = 0;

    for (;;) {
        cursor_skip_ws(c);
        if (!cursor_peek(c, &b)) return PR_NEED;
        if (b == '}') { cursor_bump(c); break; }
        if (b == ',') { cursor_bump(c); continue; }
        if (b != '"') {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }

        uint8_t key_buf[16];
        size_t  key_len;
        parse_rc_t rc = parse_string_into(c, key_buf, sizeof key_buf,
                                          &key_len, err);
        if (rc != PR_OK) return rc;

        cursor_skip_ws(c);
        int e = cursor_expect(c, ':');
        if (e < 0) return PR_NEED;
        if (e == 0) {
            *err = SOS_PARSE_ERR_UNEXPECTED_BYTE;
            return PR_ERROR;
        }
        cursor_skip_ws(c);

        if (key_eq(key_buf, key_len, "event")) {
            if (seen_event) {
                *err = SOS_PARSE_ERR_DUPLICATE_FIELD;
                return PR_ERROR;
            }
            seen_event = true;
            uint8_t name_buf[32];
            size_t  name_len;
            rc = parse_string_into(c, name_buf, sizeof name_buf,
                                   &name_len, err);
            if (rc != PR_OK) return rc;
            if (!resolve_event_name(name_buf, name_len, &name)) {
                *err = SOS_PARSE_ERR_UNKNOWN_EVENT_NAME;
                return PR_ERROR;
            }
            have_name = true;
        } else if (key_eq(key_buf, key_len, "data")) {
            if (seen_data) {
                *err = SOS_PARSE_ERR_DUPLICATE_FIELD;
                return PR_ERROR;
            }
            seen_data = true;
            if (!have_name) {
                /* SOS-04 Amendment 009: event MUST precede data. The
                 * parser does not buffer the data window. */
                *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
                return PR_ERROR;
            }
            rc = parse_event_data(c, name, &data, err);
            if (rc != PR_OK) return rc;
        } else if (key_eq(key_buf, key_len, "from_tid")) {
            if (seen_from_tid) {
                *err = SOS_PARSE_ERR_DUPLICATE_FIELD;
                return PR_ERROR;
            }
            seen_from_tid = true;
            bool is_null = false;
            rc = parse_i64_or_null(c, &from_tid_v, &is_null, err);
            if (rc != PR_OK) return rc;
            if (is_null) {
                from_tid_present_from_field = false;
            } else {
                from_tid_present_from_field = true;
            }
        } else {
            *err = SOS_PARSE_ERR_UNKNOWN_FIELD;
            return PR_ERROR;
        }
    }

    if (!have_name) {
        *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
        return PR_ERROR;
    }
    if (!validate_data_for_name(name, &data)) {
        *err = SOS_PARSE_ERR_BAD_EVENT_SHAPE;
        return PR_ERROR;
    }

    /* Range-check `from_tid` if present. SOS-04 §6.2.1: TaskId must be
     * in [-1, MAX_TASKS); `-1` is the idle sentinel. */
    sos_task_id_t from_tid_narrow = -1;
    if (from_tid_present_from_field) {
        parse_rc_t rc = i16_from_i64(from_tid_v, &from_tid_narrow, err);
        if (rc != PR_OK) return rc;
        if (from_tid_narrow < -1 ||
            (int64_t)from_tid_narrow >= (int64_t)SOS_MAX_TASKS) {
            *err = SOS_PARSE_ERR_NUMBER_OUT_OF_RANGE;
            return PR_ERROR;
        }
    }

    /* Populate the typed parser-emit fields. Leave the skeleton-phase
     * `kind`/`task_id`/`arg_*`/`msg` fields zeroed — phase 3
     * dispatcher consumes `name`/`data`/`from_tid_present`/`from_tid`
     * only. */
    sos_event_t out = {0};
    out.kind = SOS_EVT_NONE;
    out.task_id = -1;
    out.msg.tag = SOS_MSG_NULL;
    out.name = name;
    out.data = data;
    out.from_tid_present = from_tid_present_from_field;
    out.from_tid = from_tid_present_from_field ? from_tid_narrow : (sos_task_id_t)-1;
    *ev = out;
    return PR_OK;
}

/* ----- Public API ----- */

void sos_vector_stream_init(sos_vector_stream_t *vs)
{
    vs->state = SOS_VS_EXPECT_WRAPPER_OPEN;
    vs->depth = 0;
    vs->seen_wrapper_keys = 0;
}

/* Forward declarations for state-handler bodies. */
static sos_parse_step_t step_expect_wrapper_open(sos_vector_stream_t *vs,
                                                 cursor_t *cur);
static sos_parse_step_t step_in_wrapper_expect_key(sos_vector_stream_t *vs,
                                                   cursor_t *cur);
static sos_parse_step_t step_in_input_array(sos_vector_stream_t *vs,
                                            cursor_t *cur);
static sos_parse_step_t step_awaiting_wrapper_close(sos_vector_stream_t *vs,
                                                    cursor_t *cur);

sos_parse_step_t sos_vector_stream_try_step(sos_vector_stream_t *vs,
                                            const uint8_t *buf,
                                            size_t len)
{
    if (buf == NULL || len == 0) {
        return step_need_more_input();
    }

    cursor_t cur;
    cursor_init(&cur, buf, len);

    switch (vs->state) {
        case SOS_VS_EXPECT_WRAPPER_OPEN:
            return step_expect_wrapper_open(vs, &cur);
        case SOS_VS_IN_WRAPPER_EXPECT_KEY:
            return step_in_wrapper_expect_key(vs, &cur);
        case SOS_VS_IN_INPUT_ARRAY_EXPECT_ELEMENT:
        case SOS_VS_IN_INPUT_ARRAY_BETWEEN_ELEMENTS:
            return step_in_input_array(vs, &cur);
        case SOS_VS_AWAITING_WRAPPER_CLOSE:
            return step_awaiting_wrapper_close(vs, &cur);
        case SOS_VS_DONE:
            return step_need_more_input();
    }
    return step_error(SOS_PARSE_ERR_UNEXPECTED_BYTE, 0);
}

/* ----- State handlers ----- */

static sos_parse_step_t step_expect_wrapper_open(sos_vector_stream_t *vs,
                                                 cursor_t *cur)
{
    cursor_skip_ws(cur);
    uint8_t b;
    if (!cursor_peek(cur, &b)) return step_need_more_input();
    if (b != '{') {
        return step_error(SOS_PARSE_ERR_UNEXPECTED_BYTE, cur->pos);
    }
    cursor_bump(cur);
    vs->depth = 1;
    vs->state = SOS_VS_IN_WRAPPER_EXPECT_KEY;
    return step_in_wrapper_expect_key(vs, cur);
}

static sos_parse_step_t step_in_wrapper_expect_key(sos_vector_stream_t *vs,
                                                   cursor_t *cur)
{
    cursor_skip_ws(cur);
    uint8_t b;

    /* If both `config` and `input` are done, expect closing `}`. */
    if ((vs->seen_wrapper_keys & SEEN_CONFIG) &&
        (vs->seen_wrapper_keys & SEEN_INPUT)) {
        if (!cursor_peek(cur, &b)) return step_need_more_input();
        if (b == '}') {
            cursor_bump(cur);
            if (vs->depth > 0) vs->depth -= 1;
            cursor_skip_ws(cur);
            vs->state = SOS_VS_DONE;
            return step_end_of_input(cur->pos);
        }
        if (b == ',') {
            cursor_bump(cur);
            return step_in_wrapper_expect_key(vs, cur);
        }
        return step_error(SOS_PARSE_ERR_BAD_WRAPPER_SHAPE, cur->pos);
    }

    if (!cursor_peek(cur, &b)) return step_need_more_input();
    if (b == ',') {
        cursor_bump(cur);
        return step_in_wrapper_expect_key(vs, cur);
    }
    if (b == '}') {
        /* Closing wrapper before both required keys arrived. */
        return step_error(SOS_PARSE_ERR_BAD_WRAPPER_SHAPE, cur->pos);
    }
    if (b != '"') {
        return step_error(SOS_PARSE_ERR_UNEXPECTED_BYTE, cur->pos);
    }

    uint8_t key_buf[16];
    size_t  key_len;
    sos_parse_error_t err = SOS_PARSE_ERR_NONE;
    parse_rc_t rc = parse_string_into(cur, key_buf, sizeof key_buf,
                                      &key_len, &err);
    if (rc == PR_NEED) return step_need_more_input();
    if (rc == PR_ERROR) return step_error(err, cur->pos);

    cursor_skip_ws(cur);
    int e = cursor_expect(cur, ':');
    if (e < 0) return step_need_more_input();
    if (e == 0) {
        return step_error(SOS_PARSE_ERR_UNEXPECTED_BYTE, cur->pos);
    }
    cursor_skip_ws(cur);

    if (key_eq(key_buf, key_len, "name")) {
        if (vs->seen_wrapper_keys & SEEN_NAME) {
            return step_error(SOS_PARSE_ERR_DUPLICATE_FIELD, cur->pos);
        }
        vs->seen_wrapper_keys |= SEEN_NAME;
        rc = skip_string_value(cur, &err);
        if (rc == PR_NEED) return step_need_more_input();
        if (rc == PR_ERROR) return step_error(err, cur->pos);
        return step_in_wrapper_expect_key(vs, cur);
    }

    if (key_eq(key_buf, key_len, "config")) {
        if (vs->seen_wrapper_keys & SEEN_CONFIG) {
            return step_error(SOS_PARSE_ERR_DUPLICATE_FIELD, cur->pos);
        }
        vs->seen_wrapper_keys |= SEEN_CONFIG;
        /* Zero-init: GCC 13 -Wmaybe-uninitialized can't always prove
         * parse_config_object populates every field before returning PR_OK
         * (the inner walker fills each field conditionally as keys are
         * encountered). The runtime contract is "PR_OK ⇒ all fields set"
         * but the data-flow analysis doesn't see the guard. */
        sos_vector_header_t hdr = {0};
        rc = parse_config_object(cur, &hdr, &err);
        if (rc == PR_NEED) return step_need_more_input();
        if (rc == PR_ERROR) return step_error(err, cur->pos);
        return step_vector_header(&hdr, cur->pos);
    }

    if (key_eq(key_buf, key_len, "input")) {
        if (vs->seen_wrapper_keys & SEEN_INPUT) {
            return step_error(SOS_PARSE_ERR_DUPLICATE_FIELD, cur->pos);
        }
        vs->seen_wrapper_keys |= SEEN_INPUT;
        cursor_skip_ws(cur);
        if (!cursor_peek(cur, &b)) return step_need_more_input();
        if (b != '[') {
            return step_error(SOS_PARSE_ERR_UNEXPECTED_BYTE, cur->pos);
        }
        cursor_bump(cur);
        vs->state = SOS_VS_IN_INPUT_ARRAY_EXPECT_ELEMENT;
        return step_in_input_array(vs, cur);
    }

    return step_error(SOS_PARSE_ERR_BAD_WRAPPER_SHAPE, cur->pos);
}

static sos_parse_step_t step_in_input_array(sos_vector_stream_t *vs,
                                            cursor_t *cur)
{
    cursor_skip_ws(cur);
    uint8_t b;

    if (vs->state == SOS_VS_IN_INPUT_ARRAY_BETWEEN_ELEMENTS) {
        if (!cursor_peek(cur, &b)) return step_need_more_input();
        if (b == ',') {
            cursor_bump(cur);
            cursor_skip_ws(cur);
            vs->state = SOS_VS_IN_INPUT_ARRAY_EXPECT_ELEMENT;
        } else if (b == ']') {
            cursor_bump(cur);
            vs->state = SOS_VS_IN_WRAPPER_EXPECT_KEY;
            return step_in_wrapper_expect_key(vs, cur);
        } else {
            return step_error(SOS_PARSE_ERR_UNEXPECTED_BYTE, cur->pos);
        }
    }

    if (!cursor_peek(cur, &b)) return step_need_more_input();
    if (b == ']') {
        cursor_bump(cur);
        vs->state = SOS_VS_IN_WRAPPER_EXPECT_KEY;
        return step_in_wrapper_expect_key(vs, cur);
    }
    if (b == '{') {
        sos_event_t ev;
        sos_parse_error_t err = SOS_PARSE_ERR_NONE;
        parse_rc_t rc = parse_event_object(cur, &ev, &err);
        if (rc == PR_NEED) return step_need_more_input();
        if (rc == PR_ERROR) return step_error(err, cur->pos);
        vs->state = SOS_VS_IN_INPUT_ARRAY_BETWEEN_ELEMENTS;
        return step_event(&ev, cur->pos);
    }
    return step_error(SOS_PARSE_ERR_UNEXPECTED_BYTE, cur->pos);
}

static sos_parse_step_t step_awaiting_wrapper_close(sos_vector_stream_t *vs,
                                                    cursor_t *cur)
{
    cursor_skip_ws(cur);
    uint8_t b;
    if (!cursor_peek(cur, &b)) return step_need_more_input();
    if (b == '}') {
        cursor_bump(cur);
        vs->state = SOS_VS_DONE;
        return step_end_of_input(cur->pos);
    }
    return step_error(SOS_PARSE_ERR_UNEXPECTED_END, cur->pos);
}
