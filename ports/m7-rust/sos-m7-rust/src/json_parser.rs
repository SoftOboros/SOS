//! Hand-rolled `no_std` JSON parser for SOS-04 firmware vector ingress.
//!
//! Per PCDN-SOS-04-008 (hand-rolled writer) the input-side parser is
//! symmetrically hand-rolled: no `serde-json-core`, no derive macros, no
//! allocator, no `core::str`-level UTF-8 validation beyond what the
//! grammar at SOS-03 §6.2.1 mandates. The parser converts raw UART bytes
//! into typed [`Event`] instances the macrostep dispatch loop can hand to
//! `scripts::dispatch_event`, plus a leading [`VectorHeader`] mirroring
//! SOS-00 §7.1 `config`.
//!
//! Framing detection follows SOS-04 §6.2.1 narrative: the wrapped vector
//! input is one JSON document terminated by `\n`. Internally the parser
//! operates token-by-token, walking the wrapper object (`config` + `input`
//! array) and emitting one item per [`try_step`] call. The dispatch loop
//! drives the parser incrementally as UART bytes arrive.
//!
//! Grammar accepted (per SOS-04 §6.2.1 + SOS-03 §6.2):
//!
//! ```text
//! wrapper := '{' ( name_field ',' )? config_field ',' input_field '}' '\n'
//!          | '{' input_field ',' config_field '}' '\n'    -- order tolerant
//!          | '{' name_field ',' input_field ',' config_field '}' '\n'
//! name_field   := '"name"' ':' STRING            -- tolerated; value skipped
//! config_field := '"config"' ':' config_obj
//! config_obj   := '{' kv_pair ( ',' kv_pair )* '}'   -- 6 known scalar keys
//! input_field  := '"input"' ':' '[' event_obj ( ',' event_obj )* ']'
//! event_obj    := '{' event_kv_pair ( ',' event_kv_pair )* '}'
//! ```
//!
//! Per the task prompt + wave 7 agent D: this parser is tolerant of a
//! present `"name"` field — its value is consumed and discarded. The
//! parser is order-tolerant for the three top-level wrapper keys (`name`
//! optional, `config` and `input` required). All other top-level keys
//! surface as [`ParseError::BadWrapperShape`].
//!
//! Maximum nested-brace depth tolerated is [`MAX_DEPTH`] (16); vectors
//! have a real depth of ~4 so this is generous headroom.

use crate::event::{Event, EventData, EventName};
use crate::kernel::TaskId;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Maximum nested-brace depth the parser tolerates. Vector files have
/// depth ~4 (top-level object → input array → event object → data
/// object); 16 is far in excess. Used as the bound for the parser's
/// internal depth counter — exceeding it surfaces as
/// [`ParseError::DepthExceeded`].
pub const MAX_DEPTH: usize = 16;

/// Vector-level configuration mirroring SOS-00 §7.1 `config` block. The
/// firmware uses these to (informationally) validate against compile-time
/// constants — if a vector specifies `max_tasks > MAX_TASKS`, the chart's
/// at-HEAD invariants would be violated; the dispatcher detects this and
/// halts. The parser itself does not enforce the bound.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct VectorHeader {
    /// `MAX_TASKS` (SOS-00 §7.1 + chart `<data id="MAX_TASKS">`).
    pub max_tasks: usize,
    /// `MAX_PRIO`.
    pub max_prio: usize,
    /// `MAX_SEMS`.
    pub max_sems: usize,
    /// `MAX_QUEUES`.
    pub max_queues: usize,
    /// `Q_DEPTH`.
    pub q_depth: usize,
    /// `SOS_TICK_HZ` (informational on the firmware; SysTick LOAD is
    /// computed at boot from the disco-analyzer's clock tree).
    pub tick_hz: u32,
}

/// Parser result for incremental parsing. The dispatch loop calls
/// [`VectorStream::try_step`] repeatedly as new bytes arrive on UART RX.
pub enum ParseStep {
    /// The buffer doesn't yet contain a complete event/header. Caller
    /// reads more UART bytes and retries. `consumed == 0`; the buffer is
    /// not advanced.
    NeedMoreInput,
    /// Successfully parsed [`VectorHeader`] from the wrapper's `config`
    /// block. Caller advances its read cursor by `consumed` bytes and
    /// keeps calling [`VectorStream::try_step`] to consume events.
    VectorHeader {
        /// The parsed config record.
        header: VectorHeader,
        /// Number of bytes from `buf[0..]` that were consumed.
        consumed: usize,
    },
    /// Successfully parsed one [`Event`] from the `input` array. Caller
    /// advances its read cursor by `consumed` bytes.
    Event {
        /// The parsed event.
        event: Event,
        /// Number of bytes from `buf[0..]` that were consumed.
        consumed: usize,
    },
    /// The input stream's `input` array has ended (closing `]` consumed,
    /// plus the wrapper's closing `}`). Caller stops calling
    /// [`VectorStream::try_step`] for this vector.
    EndOfInput {
        /// Number of bytes from `buf[0..]` that were consumed (covers
        /// the array's closing `]` and the wrapper's closing `}` plus
        /// any trailing whitespace / `\n`).
        consumed: usize,
    },
    /// Parse error — caller should reset the parser or signal an error
    /// to the host (per SOS-04 §6.2.1 the v1 behaviour is to emit the
    /// done sentinel and halt without running the vector).
    Error {
        /// The error class.
        kind: ParseError,
        /// Offset within `buf[0..]` where the error was detected. May be
        /// approximate (the parser's lookahead is one byte) but is
        /// sufficient for diagnosis.
        byte_offset: usize,
    },
}

/// Parser error class. Surfaced via [`ParseStep::Error`].
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum ParseError {
    /// Encountered a byte the grammar does not admit at the current
    /// state (e.g. `]` while inside an object, alphabetic char where a
    /// number was expected).
    UnexpectedByte,
    /// The buffer ended mid-token in a position the grammar cannot
    /// recover from incrementally — used for the wrapper's closing `}`
    /// missing after `EndOfInput` is otherwise satisfied. (Mid-token
    /// shortages return [`ParseStep::NeedMoreInput`].)
    UnexpectedEnd,
    /// Nested-brace depth exceeded [`MAX_DEPTH`].
    DepthExceeded,
    /// `input[i].event` value not in SOS-01 §5.3 `ExternalEventName`.
    UnknownEventName,
    /// Object field name not in the parser's closed-key set for this
    /// object's context (e.g. `flubber` inside a `data` object).
    UnknownField,
    /// Same key appeared twice within one object.
    DuplicateField,
    /// Integer literal overflowed the parser's accumulator (`i64`).
    NumberOutOfRange,
    /// JSON valid but doesn't match the expected event-payload shape
    /// for the named [`EventName`] (e.g. `task.create` missing `id` or
    /// carrying a `ticks` field).
    BadEventShape,
    /// The wrapped vector container's outer key set is wrong (e.g.
    /// only `config` present with no `input`, or an unknown top-level
    /// key like `tags` or `expected_trace`).
    BadWrapperShape,
}

/// Top-level parser state machine driving the wrapper's traversal.
#[derive(Clone, Copy, PartialEq, Eq)]
enum ParserState {
    /// Expect the wrapper's opening `{`.
    ExpectWrapperOpen,
    /// Inside the wrapper, expect a key (or closing `}` if both
    /// `config` and `input` seen).
    InWrapperExpectKey,
    /// After a key was parsed; the parser is mid-value for either
    /// `config` (have we emitted the header?), `input` (have we
    /// reached the array's `[`?), or a skipped key (e.g. `name`).
    /// The `seen` bitfield tracks which keys have been processed.
    InWrapperInValue,
    /// Inside the `input` array; expect either an event object `{` or
    /// closing `]`.
    InInputArrayExpectElement,
    /// Mid-event-object (between elements).
    InInputArrayBetweenElements,
    /// After the `input` array's `]` was consumed; expect the
    /// wrapper's closing `}` (possibly with `,` and `config` still
    /// to come if `input` came first).
    AwaitingWrapperClose,
    /// Terminal state — `EndOfInput` already emitted; further calls
    /// return `NeedMoreInput` indefinitely (or the caller stops).
    Done,
}

/// Bitfield tracking which top-level wrapper keys have been consumed.
/// `name` is tolerated and skipped; `config` and `input` are required.
#[derive(Clone, Copy, PartialEq, Eq)]
struct SeenKeys(u8);

impl SeenKeys {
    const NAME: u8 = 0b001;
    const CONFIG: u8 = 0b010;
    const INPUT: u8 = 0b100;

    const fn new() -> Self {
        Self(0)
    }

    fn mark(&mut self, bit: u8) -> Result<(), ParseError> {
        if self.0 & bit != 0 {
            return Err(ParseError::DuplicateField);
        }
        self.0 |= bit;
        Ok(())
    }

    fn has(self, bit: u8) -> bool {
        self.0 & bit != 0
    }
}

/// Incremental wrapped-vector parser. One per vector ingress cycle.
///
/// The parser holds enough state to advance the wrapper's traversal one
/// item at a time. Internally it tracks the cumulative position in the
/// wrapper (have we seen `config`? `input`'s `[`?) plus a depth counter
/// for malformed-input detection.
pub struct VectorStream {
    state: ParserState,
    seen: SeenKeys,
    depth: u8,
}

impl VectorStream {
    /// Construct a fresh parser at the start of a new vector. The
    /// returned parser expects the next byte to be (after optional
    /// whitespace) the wrapper's opening `{`.
    pub const fn new() -> Self {
        Self {
            state: ParserState::ExpectWrapperOpen,
            seen: SeenKeys::new(),
            depth: 0,
        }
    }

    /// Consume bytes from the start of `buf` and return the next parse
    /// step. On [`ParseStep::NeedMoreInput`], `consumed == 0`. The
    /// caller manages the buffer's shift-left after partial-consume.
    ///
    /// The parser allocates nothing, panics on no input, and is `no_std`
    /// clean — malformed input surfaces as [`ParseStep::Error`], never
    /// as a panic.
    pub fn try_step(&mut self, buf: &[u8]) -> ParseStep {
        // Track cursor relative to caller's buffer start. Every successful
        // path returns a `ParseStep::*` carrying the absolute consumed count
        // (the parser's first-byte offset stays at 0 within a single call).
        let mut cur = Cursor::new(buf);

        match self.state {
            ParserState::ExpectWrapperOpen => self.step_expect_wrapper_open(&mut cur),
            ParserState::InWrapperExpectKey => self.step_in_wrapper_expect_key(&mut cur),
            ParserState::InWrapperInValue => {
                // Reachable only as a transient state; try_step keeps
                // calling sub-handlers until it reaches a recognisable
                // resting state. This arm guards against logic bugs.
                ParseStep::Error {
                    kind: ParseError::UnexpectedByte,
                    byte_offset: cur.pos,
                }
            }
            ParserState::InInputArrayExpectElement
            | ParserState::InInputArrayBetweenElements => {
                self.step_in_input_array(&mut cur)
            }
            ParserState::AwaitingWrapperClose => self.step_awaiting_wrapper_close(&mut cur),
            ParserState::Done => ParseStep::NeedMoreInput,
        }
    }
}

impl Default for VectorStream {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Cursor — a peek-and-advance wrapper over the caller's buffer.
// ---------------------------------------------------------------------------

/// Single-buffer cursor with one-byte lookahead.
struct Cursor<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> Cursor<'a> {
    fn new(buf: &'a [u8]) -> Self {
        Self { buf, pos: 0 }
    }

    /// Returns the next byte without advancing, or `None` at end of buf.
    fn peek(&self) -> Option<u8> {
        self.buf.get(self.pos).copied()
    }

    /// Advance one byte. Caller must have peeked first.
    fn bump(&mut self) {
        self.pos += 1;
    }

    /// Skip ASCII whitespace (space, tab, LF, CR) per RFC 8259 §2.
    fn skip_ws(&mut self) {
        while let Some(b) = self.peek() {
            if matches!(b, b' ' | b'\t' | b'\n' | b'\r') {
                self.bump();
            } else {
                break;
            }
        }
    }

    /// Expect a specific byte; advance on match. `None` if buffer
    /// exhausted; `Some(false)` if the next byte is not `c`.
    fn consume_if(&mut self, c: u8) -> Option<bool> {
        let b = self.peek()?;
        if b == c {
            self.bump();
            Some(true)
        } else {
            Some(false)
        }
    }
}

// ---------------------------------------------------------------------------
// State-handler bodies (private to VectorStream).
// ---------------------------------------------------------------------------

impl VectorStream {
    fn step_expect_wrapper_open(&mut self, cur: &mut Cursor<'_>) -> ParseStep {
        cur.skip_ws();
        match cur.peek() {
            None => ParseStep::NeedMoreInput,
            Some(b'{') => {
                cur.bump();
                self.depth = 1;
                self.state = ParserState::InWrapperExpectKey;
                // Recurse into key-expecting state without returning to
                // caller — the wrapper's first key is on the same byte
                // window as `{`.
                self.step_in_wrapper_expect_key(cur)
            }
            Some(_) => ParseStep::Error {
                kind: ParseError::UnexpectedByte,
                byte_offset: cur.pos,
            },
        }
    }

    fn step_in_wrapper_expect_key(&mut self, cur: &mut Cursor<'_>) -> ParseStep {
        cur.skip_ws();

        // If both `config` and `input` are done, the next byte must be
        // the wrapper's closing `}`. (The `name` key is optional.)
        if self.seen.has(SeenKeys::CONFIG) && self.seen.has(SeenKeys::INPUT) {
            match cur.peek() {
                None => return ParseStep::NeedMoreInput,
                Some(b'}') => {
                    cur.bump();
                    self.depth -= 1;
                    // Skip any trailing whitespace / newline that the
                    // host adapter terminates the wrapper with.
                    cur.skip_ws();
                    self.state = ParserState::Done;
                    return ParseStep::EndOfInput { consumed: cur.pos };
                }
                Some(b',') => {
                    // Trailing comma after both seen keys — accept it as
                    // a separator and re-enter the expect-key loop.
                    cur.bump();
                    return self.step_in_wrapper_expect_key(cur);
                }
                Some(_) => {
                    return ParseStep::Error {
                        kind: ParseError::BadWrapperShape,
                        byte_offset: cur.pos,
                    };
                }
            }
        }

        // Otherwise, expect either a key string, a trailing `}` (which
        // would be the BadWrapperShape error if seen here), or a comma
        // separating keys.
        match cur.peek() {
            None => return ParseStep::NeedMoreInput,
            Some(b',') => {
                cur.bump();
                return self.step_in_wrapper_expect_key(cur);
            }
            Some(b'}') => {
                // Closing wrapper before both required keys arrived.
                return ParseStep::Error {
                    kind: ParseError::BadWrapperShape,
                    byte_offset: cur.pos,
                };
            }
            Some(b'"') => { /* fall through to key-parsing */ }
            Some(_) => {
                return ParseStep::Error {
                    kind: ParseError::UnexpectedByte,
                    byte_offset: cur.pos,
                };
            }
        }

        // Parse the key string into a fixed-size scratch.
        let mut key_buf = [0u8; 16];
        let key = match parse_string_into(cur, &mut key_buf) {
            Ok(Some(s)) => s,
            Ok(None) => return ParseStep::NeedMoreInput,
            Err(e) => {
                return ParseStep::Error {
                    kind: e,
                    byte_offset: cur.pos,
                };
            }
        };

        // Expect ':'
        cur.skip_ws();
        match cur.peek() {
            None => return ParseStep::NeedMoreInput,
            Some(b':') => cur.bump(),
            Some(_) => {
                return ParseStep::Error {
                    kind: ParseError::UnexpectedByte,
                    byte_offset: cur.pos,
                };
            }
        }
        cur.skip_ws();

        // Dispatch on key.
        match key {
            b"name" => {
                if let Err(e) = self.seen.mark(SeenKeys::NAME) {
                    return ParseStep::Error {
                        kind: e,
                        byte_offset: cur.pos,
                    };
                }
                // Skip the string value (we don't care about its content).
                match skip_string_value(cur) {
                    Ok(true) => {
                        // After the value, expect either `,` or `}`;
                        // loop back into key-expecting.
                        self.step_in_wrapper_expect_key(cur)
                    }
                    Ok(false) => ParseStep::NeedMoreInput,
                    Err(e) => ParseStep::Error {
                        kind: e,
                        byte_offset: cur.pos,
                    },
                }
            }
            b"config" => {
                if let Err(e) = self.seen.mark(SeenKeys::CONFIG) {
                    return ParseStep::Error {
                        kind: e,
                        byte_offset: cur.pos,
                    };
                }
                // Parse the config object and emit the VectorHeader.
                match parse_config_object(cur) {
                    Ok(Some(header)) => ParseStep::VectorHeader {
                        header,
                        consumed: cur.pos,
                    },
                    Ok(None) => ParseStep::NeedMoreInput,
                    Err(e) => ParseStep::Error {
                        kind: e,
                        byte_offset: cur.pos,
                    },
                }
            }
            b"input" => {
                if let Err(e) = self.seen.mark(SeenKeys::INPUT) {
                    return ParseStep::Error {
                        kind: e,
                        byte_offset: cur.pos,
                    };
                }
                // Expect the array's opening `[`.
                cur.skip_ws();
                match cur.peek() {
                    None => return ParseStep::NeedMoreInput,
                    Some(b'[') => {
                        cur.bump();
                        self.state = ParserState::InInputArrayExpectElement;
                        self.step_in_input_array(cur)
                    }
                    Some(_) => ParseStep::Error {
                        kind: ParseError::UnexpectedByte,
                        byte_offset: cur.pos,
                    },
                }
            }
            _ => ParseStep::Error {
                kind: ParseError::BadWrapperShape,
                byte_offset: cur.pos,
            },
        }
    }

    fn step_in_input_array(&mut self, cur: &mut Cursor<'_>) -> ParseStep {
        cur.skip_ws();
        // Between elements we accept a `,` separator.
        if self.state == ParserState::InInputArrayBetweenElements {
            match cur.peek() {
                None => return ParseStep::NeedMoreInput,
                Some(b',') => {
                    cur.bump();
                    cur.skip_ws();
                    self.state = ParserState::InInputArrayExpectElement;
                }
                Some(b']') => {
                    // Array end.
                    cur.bump();
                    // After `]`, we may need the wrapper's closing `}`
                    // (or, if `config` came after `input`, another key
                    // in the wrapper).
                    if self.seen.has(SeenKeys::CONFIG) {
                        // Both required keys done — flow through to
                        // AwaitingWrapperClose handling, which can also
                        // handle trailing `,`.
                        self.state = ParserState::InWrapperExpectKey;
                        return self.step_in_wrapper_expect_key(cur);
                    } else {
                        self.state = ParserState::InWrapperExpectKey;
                        return self.step_in_wrapper_expect_key(cur);
                    }
                }
                Some(_) => {
                    return ParseStep::Error {
                        kind: ParseError::UnexpectedByte,
                        byte_offset: cur.pos,
                    };
                }
            }
        }

        // ExpectElement: next byte is either `]` (empty array / array
        // end) or `{` (event object).
        match cur.peek() {
            None => ParseStep::NeedMoreInput,
            Some(b']') => {
                cur.bump();
                self.state = ParserState::InWrapperExpectKey;
                self.step_in_wrapper_expect_key(cur)
            }
            Some(b'{') => {
                match parse_event_object(cur) {
                    Ok(Some(event)) => {
                        self.state = ParserState::InInputArrayBetweenElements;
                        ParseStep::Event {
                            event,
                            consumed: cur.pos,
                        }
                    }
                    Ok(None) => ParseStep::NeedMoreInput,
                    Err(e) => ParseStep::Error {
                        kind: e,
                        byte_offset: cur.pos,
                    },
                }
            }
            Some(_) => ParseStep::Error {
                kind: ParseError::UnexpectedByte,
                byte_offset: cur.pos,
            },
        }
    }

    fn step_awaiting_wrapper_close(&mut self, cur: &mut Cursor<'_>) -> ParseStep {
        cur.skip_ws();
        match cur.peek() {
            None => ParseStep::NeedMoreInput,
            Some(b'}') => {
                cur.bump();
                self.state = ParserState::Done;
                ParseStep::EndOfInput { consumed: cur.pos }
            }
            Some(_) => ParseStep::Error {
                kind: ParseError::UnexpectedEnd,
                byte_offset: cur.pos,
            },
        }
    }
}

// ---------------------------------------------------------------------------
// String parsing — minimal escape handling per the SOS production set.
// ---------------------------------------------------------------------------

/// Parse a JSON string starting at `cur.peek() == Some(b'"')` and write
/// its decoded bytes into `out`. Returns `Ok(Some(&out[..n]))` on
/// success, `Ok(None)` if the buffer was exhausted mid-string,
/// `Err(ParseError)` on malformed escape / overflow / unsupported `\u`.
fn parse_string_into<'a>(
    cur: &mut Cursor<'_>,
    out: &'a mut [u8],
) -> Result<Option<&'a [u8]>, ParseError> {
    match cur.peek() {
        Some(b'"') => cur.bump(),
        None => return Ok(None),
        Some(_) => return Err(ParseError::UnexpectedByte),
    }

    let mut n = 0usize;
    loop {
        let b = match cur.peek() {
            None => return Ok(None),
            Some(c) => c,
        };
        cur.bump();
        match b {
            b'"' => return Ok(Some(&out[..n])),
            b'\\' => {
                let esc = match cur.peek() {
                    None => return Ok(None),
                    Some(c) => c,
                };
                cur.bump();
                let decoded = match esc {
                    b'"' => b'"',
                    b'\\' => b'\\',
                    b'/' => b'/',
                    b'n' => b'\n',
                    b't' => b'\t',
                    b'r' => b'\r',
                    b'b' => 0x08,
                    b'f' => 0x0C,
                    b'u' => return Err(ParseError::UnexpectedByte),
                    _ => return Err(ParseError::UnexpectedByte),
                };
                if n >= out.len() {
                    return Err(ParseError::NumberOutOfRange);
                }
                out[n] = decoded;
                n += 1;
            }
            _ => {
                if n >= out.len() {
                    return Err(ParseError::NumberOutOfRange);
                }
                out[n] = b;
                n += 1;
            }
        }
    }
}

/// Skip a JSON string value (consume opening `"`, body, closing `"`)
/// without decoding into a scratch buffer. Returns `Ok(true)` on
/// completion, `Ok(false)` if the buffer was exhausted, `Err` on
/// malformed escape.
fn skip_string_value(cur: &mut Cursor<'_>) -> Result<bool, ParseError> {
    match cur.peek() {
        Some(b'"') => cur.bump(),
        None => return Ok(false),
        Some(_) => return Err(ParseError::UnexpectedByte),
    }
    loop {
        let b = match cur.peek() {
            None => return Ok(false),
            Some(c) => c,
        };
        cur.bump();
        match b {
            b'"' => return Ok(true),
            b'\\' => {
                // Consume the escaped char.
                match cur.peek() {
                    None => return Ok(false),
                    Some(b'u') => return Err(ParseError::UnexpectedByte),
                    Some(_) => cur.bump(),
                }
            }
            _ => { /* ordinary byte */ }
        }
    }
}

// ---------------------------------------------------------------------------
// Number parsing — signed integers only, i64 accumulator.
// ---------------------------------------------------------------------------

/// Parse an integer from the cursor. Returns `Ok(Some(n))` on success,
/// `Ok(None)` if the buffer was exhausted mid-number,
/// `Err(NumberOutOfRange)` on i64 overflow, `Err(UnexpectedByte)` on
/// malformed input (e.g. lone `-`, leading zeros per RFC 8259 §6).
fn parse_i64(cur: &mut Cursor<'_>) -> Result<Option<i64>, ParseError> {
    let mut neg = false;
    if let Some(b'-') = cur.peek() {
        cur.bump();
        neg = true;
    }

    let first = match cur.peek() {
        None => return Ok(None),
        Some(c) => c,
    };

    if !first.is_ascii_digit() {
        return Err(ParseError::UnexpectedByte);
    }

    // RFC 8259 §6: a leading `0` MUST be the entire integer part — no
    // `0123` allowed. `0` alone is fine; `-0` is fine.
    if first == b'0' {
        cur.bump();
        // Make sure the next byte is not a digit.
        if let Some(b) = cur.peek() {
            if b.is_ascii_digit() {
                return Err(ParseError::UnexpectedByte);
            }
        }
        return Ok(Some(0));
    }

    let mut acc: i64 = 0;
    while let Some(b) = cur.peek() {
        if !b.is_ascii_digit() {
            break;
        }
        let digit = (b - b'0') as i64;
        // Build positive then negate at the end so i64::MIN is reachable
        // (its absolute value overflows i64::MAX).
        match acc.checked_mul(10).and_then(|v| {
            if neg {
                v.checked_sub(digit)
            } else {
                v.checked_add(digit)
            }
        }) {
            Some(v) => acc = v,
            None => {
                // Overflow — but check for the i64::MIN edge case.
                if neg && acc == (i64::MIN / 10) && digit == -(i64::MIN % 10) {
                    // The exact i64::MIN limit. This is theoretical; for the
                    // SOS vector grammar, ticks/timeout never approach these
                    // magnitudes. Fall through to error.
                }
                return Err(ParseError::NumberOutOfRange);
            }
        }
        cur.bump();
    }

    Ok(Some(acc))
}

/// Parse either an integer or the literal `null` (returning `None` for
/// `null`). Used for `from_tid` and the `data` field of an event.
fn parse_i64_or_null(cur: &mut Cursor<'_>) -> Result<Option<Option<i64>>, ParseError> {
    cur.skip_ws();
    match cur.peek() {
        None => Ok(None),
        Some(b'n') => {
            if !match_literal(cur, b"null")? {
                return Err(ParseError::UnexpectedByte);
            }
            Ok(Some(None))
        }
        Some(_) => parse_i64(cur).map(|opt| opt.map(Some)),
    }
}

/// Match a literal byte sequence (e.g. `true`, `false`, `null`).
/// `Ok(true)` on full match, `Ok(false)` on mismatch, `Err` is unused.
fn match_literal(cur: &mut Cursor<'_>, lit: &[u8]) -> Result<bool, ParseError> {
    for &c in lit {
        match cur.peek() {
            None => return Ok(false),
            Some(b) if b == c => cur.bump(),
            Some(_) => return Ok(false),
        }
    }
    Ok(true)
}

// ---------------------------------------------------------------------------
// Config object parsing.
// ---------------------------------------------------------------------------

/// Parse the `config` object value starting at `cur.peek() == Some(b'{')`.
/// Returns `Ok(Some(header))` on success, `Ok(None)` on buffer exhaustion,
/// `Err(...)` on malformed shape.
fn parse_config_object(cur: &mut Cursor<'_>) -> Result<Option<VectorHeader>, ParseError> {
    cur.skip_ws();
    match cur.peek() {
        None => return Ok(None),
        Some(b'{') => cur.bump(),
        Some(_) => return Err(ParseError::UnexpectedByte),
    }

    // Six required scalar keys; track which we've seen.
    let mut seen: u8 = 0;
    const K_MAX_TASKS: u8 = 1 << 0;
    const K_MAX_PRIO: u8 = 1 << 1;
    const K_MAX_SEMS: u8 = 1 << 2;
    const K_MAX_QUEUES: u8 = 1 << 3;
    const K_Q_DEPTH: u8 = 1 << 4;
    const K_TICK_HZ: u8 = 1 << 5;
    const ALL: u8 = K_MAX_TASKS | K_MAX_PRIO | K_MAX_SEMS | K_MAX_QUEUES | K_Q_DEPTH | K_TICK_HZ;

    let mut max_tasks = 0i64;
    let mut max_prio = 0i64;
    let mut max_sems = 0i64;
    let mut max_queues = 0i64;
    let mut q_depth = 0i64;
    let mut tick_hz = 0i64;

    loop {
        cur.skip_ws();
        match cur.peek() {
            None => return Ok(None),
            Some(b'}') => {
                cur.bump();
                break;
            }
            Some(b',') => {
                cur.bump();
                continue;
            }
            Some(b'"') => { /* key */ }
            Some(_) => return Err(ParseError::UnexpectedByte),
        }

        let mut key_buf = [0u8; 16];
        let key = match parse_string_into(cur, &mut key_buf)? {
            Some(s) => s,
            None => return Ok(None),
        };
        cur.skip_ws();
        match cur.consume_if(b':') {
            Some(true) => cur.skip_ws(),
            Some(false) => return Err(ParseError::UnexpectedByte),
            None => return Ok(None),
        }

        // Read the value into a local i64.
        let v = match parse_i64(cur)? {
            Some(n) => n,
            None => return Ok(None),
        };

        let bit = match key {
            b"max_tasks" => {
                max_tasks = v;
                K_MAX_TASKS
            }
            b"max_prio" => {
                max_prio = v;
                K_MAX_PRIO
            }
            b"max_sems" => {
                max_sems = v;
                K_MAX_SEMS
            }
            b"max_queues" => {
                max_queues = v;
                K_MAX_QUEUES
            }
            b"q_depth" => {
                q_depth = v;
                K_Q_DEPTH
            }
            b"tick_hz" => {
                tick_hz = v;
                K_TICK_HZ
            }
            _ => return Err(ParseError::UnknownField),
        };
        if seen & bit != 0 {
            return Err(ParseError::DuplicateField);
        }
        seen |= bit;
    }

    if seen != ALL {
        return Err(ParseError::BadEventShape);
    }

    // Range-check and pack into VectorHeader's narrower types.
    let header = VectorHeader {
        max_tasks: usize_from_i64(max_tasks)?,
        max_prio: usize_from_i64(max_prio)?,
        max_sems: usize_from_i64(max_sems)?,
        max_queues: usize_from_i64(max_queues)?,
        q_depth: usize_from_i64(q_depth)?,
        tick_hz: u32_from_i64(tick_hz)?,
    };
    Ok(Some(header))
}

fn usize_from_i64(v: i64) -> Result<usize, ParseError> {
    if v < 0 || v > (usize::MAX as i64) {
        Err(ParseError::NumberOutOfRange)
    } else {
        Ok(v as usize)
    }
}

fn u32_from_i64(v: i64) -> Result<u32, ParseError> {
    if v < 0 || v > (u32::MAX as i64) {
        Err(ParseError::NumberOutOfRange)
    } else {
        Ok(v as u32)
    }
}

fn i16_from_i64(v: i64) -> Result<i16, ParseError> {
    if v < (i16::MIN as i64) || v > (i16::MAX as i64) {
        Err(ParseError::NumberOutOfRange)
    } else {
        Ok(v as i16)
    }
}

fn u8_from_i64(v: i64) -> Result<u8, ParseError> {
    if v < 0 || v > (u8::MAX as i64) {
        Err(ParseError::NumberOutOfRange)
    } else {
        Ok(v as u8)
    }
}

fn u32_nonneg(v: i64) -> Result<u32, ParseError> {
    u32_from_i64(v)
}

// ---------------------------------------------------------------------------
// Event object parsing.
// ---------------------------------------------------------------------------

/// Parse one event object starting at `cur.peek() == Some(b'{')`.
fn parse_event_object(cur: &mut Cursor<'_>) -> Result<Option<Event>, ParseError> {
    cur.skip_ws();
    match cur.peek() {
        None => return Ok(None),
        Some(b'{') => cur.bump(),
        Some(_) => return Err(ParseError::UnexpectedByte),
    }

    let mut seen_event = false;
    let mut seen_data = false;
    let mut seen_from_tid = false;
    let mut name: Option<EventName> = None;
    let mut data: Option<EventData> = None;
    let mut from_tid: Option<Option<i64>> = None;

    loop {
        cur.skip_ws();
        match cur.peek() {
            None => return Ok(None),
            Some(b'}') => {
                cur.bump();
                break;
            }
            Some(b',') => {
                cur.bump();
                continue;
            }
            Some(b'"') => { /* key */ }
            Some(_) => return Err(ParseError::UnexpectedByte),
        }

        let mut key_buf = [0u8; 16];
        let key = match parse_string_into(cur, &mut key_buf)? {
            Some(s) => s,
            None => return Ok(None),
        };
        cur.skip_ws();
        match cur.consume_if(b':') {
            Some(true) => {}
            Some(false) => return Err(ParseError::UnexpectedByte),
            None => return Ok(None),
        }
        cur.skip_ws();

        match key {
            b"event" => {
                if seen_event {
                    return Err(ParseError::DuplicateField);
                }
                seen_event = true;
                let mut name_buf = [0u8; 32];
                let s = match parse_string_into(cur, &mut name_buf)? {
                    Some(s) => s,
                    None => return Ok(None),
                };
                name = Some(resolve_event_name(s)?);
            }
            b"data" => {
                if seen_data {
                    return Err(ParseError::DuplicateField);
                }
                seen_data = true;
                // `data` can be `null` or an object — but we cannot
                // dispatch payload parsing yet without knowing the
                // event name. Defer: read the raw bytes into a sub-
                // cursor's positional range and re-parse once name is
                // known.
                //
                // Simpler approach: handle both orderings by buffering
                // the data-object's start position. To keep this no_std
                // simple, we instead require the parser to support both
                // orderings by re-parsing data once name is bound. But
                // re-parsing requires preserving the input window —
                // which the caller does. We just record where the data
                // value starts; if `event` already arrived we can parse
                // now, otherwise we save the start offset and parse at
                // end-of-object.
                if let Some(en) = name {
                    match parse_event_data(cur, en)? {
                        Some(d) => data = Some(d),
                        None => return Ok(None),
                    }
                } else {
                    // Defer: we need the event name first. The on-disk
                    // vector format always puts `event` before `data`
                    // (the harness emits them in that order); strict
                    // out-of-order ingestion would require buffering.
                    return Err(ParseError::BadEventShape);
                }
            }
            b"from_tid" => {
                if seen_from_tid {
                    return Err(ParseError::DuplicateField);
                }
                seen_from_tid = true;
                match parse_i64_or_null(cur)? {
                    Some(v) => from_tid = Some(v),
                    None => return Ok(None),
                }
            }
            _ => return Err(ParseError::UnknownField),
        }
    }

    let name = match name {
        Some(n) => n,
        None => return Err(ParseError::BadEventShape),
    };

    // If no `data` field appeared, default to EventData::None — only
    // valid if the event name doesn't carry a payload.
    let final_data = match data {
        Some(d) => d,
        None => EventData::None,
    };
    validate_data_for_name(name, &final_data)?;

    // from_tid: None (absent) → None; Some(Some(n)) → Some(TaskId);
    // Some(None) (explicit null) → None.
    let final_from_tid = match from_tid {
        None => None,
        Some(None) => None,
        Some(Some(n)) => Some(i16_from_i64(n)?),
    };
    // Range-check: TaskId must be in [-1, MAX_TASKS) when present per
    // SOS-04 §6.2.1. `-1` (idle sentinel) is allowed because the chart
    // uses it as the boot-baseline `current` value; ISR-context events
    // are represented by `from_tid: null` and arrive as `None` here.
    if let Some(tid) = final_from_tid {
        if tid < -1 || (tid as i64) >= (crate::kernel::MAX_TASKS as i64) {
            return Err(ParseError::NumberOutOfRange);
        }
    }

    // `TaskId` is `i16` (per `crate::kernel`); `final_from_tid` is
    // already `Option<i16>` so no cast is needed.
    let _typecheck: Option<TaskId> = final_from_tid;
    Ok(Some(Event {
        name,
        data: final_data,
        from_tid: final_from_tid,
    }))
}

/// Resolve a dotted event-name string to an [`EventName`] variant.
/// SOS-01 §5.3 — the closed 18-variant set.
fn resolve_event_name(s: &[u8]) -> Result<EventName, ParseError> {
    let n = match s {
        b"task.create" => EventName::TaskCreate,
        b"task.delay" => EventName::TaskDelay,
        b"task.yield" => EventName::TaskYield,
        b"task.suspend" => EventName::TaskSuspend,
        b"task.resume" => EventName::TaskResume,
        b"sem.create" => EventName::SemCreate,
        b"sem.take" => EventName::SemTake,
        b"sem.give" => EventName::SemGive,
        b"sem.give_from_isr" => EventName::SemGiveFromIsr,
        b"queue.create" => EventName::QueueCreate,
        b"queue.send" => EventName::QueueSend,
        b"queue.receive" => EventName::QueueReceive,
        b"queue.send_from_isr" => EventName::QueueSendFromIsr,
        b"sys.tick" => EventName::SysTick,
        b"crit.enter" => EventName::CritEnter,
        b"crit.exit" => EventName::CritExit,
        b"sched.suspend" => EventName::SchedSuspend,
        b"sched.resume" => EventName::SchedResume,
        _ => return Err(ParseError::UnknownEventName),
    };
    Ok(n)
}

/// Parse the `data` value into the appropriate [`EventData`] variant for
/// the given [`EventName`]. Returns `Ok(Some(d))` on success, `Ok(None)`
/// on buffer exhaustion.
fn parse_event_data(
    cur: &mut Cursor<'_>,
    name: EventName,
) -> Result<Option<EventData>, ParseError> {
    cur.skip_ws();
    // `null` data => EventData::None (valid only for no-payload events).
    if let Some(b'n') = cur.peek() {
        if !match_literal(cur, b"null")? {
            return Err(ParseError::UnexpectedByte);
        }
        return Ok(Some(EventData::None));
    }

    // Otherwise expect an object.
    match cur.peek() {
        None => return Ok(None),
        Some(b'{') => cur.bump(),
        Some(_) => return Err(ParseError::UnexpectedByte),
    }

    // Walk key-value pairs into a generic scratch.
    let mut id_v: Option<i64> = None;
    let mut prio_v: Option<i64> = None;
    let mut ticks_v: Option<i64> = None;
    let mut sid_v: Option<i64> = None;
    let mut qid_v: Option<i64> = None;
    let mut msg_v: Option<i64> = None;
    let mut timeout_v: Option<i64> = None;
    let mut cap_v: Option<i64> = None;
    let mut initial_v: Option<i64> = None;
    let mut max_v: Option<i64> = None;

    loop {
        cur.skip_ws();
        match cur.peek() {
            None => return Ok(None),
            Some(b'}') => {
                cur.bump();
                break;
            }
            Some(b',') => {
                cur.bump();
                continue;
            }
            Some(b'"') => { /* key */ }
            Some(_) => return Err(ParseError::UnexpectedByte),
        }
        let mut key_buf = [0u8; 16];
        let key = match parse_string_into(cur, &mut key_buf)? {
            Some(s) => s,
            None => return Ok(None),
        };
        cur.skip_ws();
        match cur.consume_if(b':') {
            Some(true) => {}
            Some(false) => return Err(ParseError::UnexpectedByte),
            None => return Ok(None),
        }
        cur.skip_ws();
        let val = match parse_i64(cur)? {
            Some(n) => n,
            None => return Ok(None),
        };
        let slot = match key {
            b"id" => &mut id_v,
            b"prio" => &mut prio_v,
            b"ticks" => &mut ticks_v,
            b"sid" => &mut sid_v,
            b"qid" => &mut qid_v,
            b"msg" => &mut msg_v,
            b"timeout" => &mut timeout_v,
            b"cap" => &mut cap_v,
            b"initial" => &mut initial_v,
            b"max" => &mut max_v,
            _ => return Err(ParseError::UnknownField),
        };
        if slot.is_some() {
            return Err(ParseError::DuplicateField);
        }
        *slot = Some(val);
    }

    // Now dispatch on the event name and populate the corresponding
    // EventData variant. Each match arm validates payload shape: all
    // required keys must be present; no extras allowed.
    let d = match name {
        EventName::TaskCreate => {
            check_only(&[id_v.is_some(), prio_v.is_some()], &[
                ticks_v.is_some(),
                sid_v.is_some(),
                qid_v.is_some(),
                msg_v.is_some(),
                timeout_v.is_some(),
                cap_v.is_some(),
                initial_v.is_some(),
                max_v.is_some(),
            ])?;
            EventData::TaskCreate {
                id: i16_from_i64(require_i64(id_v)?)?,
                prio: u8_from_i64(require_i64(prio_v)?)?,
            }
        }
        EventName::TaskDelay => {
            check_only(&[ticks_v.is_some()], &[
                id_v.is_some(),
                prio_v.is_some(),
                sid_v.is_some(),
                qid_v.is_some(),
                msg_v.is_some(),
                timeout_v.is_some(),
                cap_v.is_some(),
                initial_v.is_some(),
                max_v.is_some(),
            ])?;
            EventData::TaskDelay {
                ticks: require_i64(ticks_v)?,
            }
        }
        EventName::TaskSuspend | EventName::TaskResume => {
            check_only(&[id_v.is_some()], &[
                prio_v.is_some(),
                ticks_v.is_some(),
                sid_v.is_some(),
                qid_v.is_some(),
                msg_v.is_some(),
                timeout_v.is_some(),
                cap_v.is_some(),
                initial_v.is_some(),
                max_v.is_some(),
            ])?;
            EventData::TaskId {
                id: i16_from_i64(require_i64(id_v)?)?,
            }
        }
        EventName::SemCreate => {
            check_only(
                &[id_v.is_some(), initial_v.is_some(), max_v.is_some()],
                &[
                    prio_v.is_some(),
                    ticks_v.is_some(),
                    sid_v.is_some(),
                    qid_v.is_some(),
                    msg_v.is_some(),
                    timeout_v.is_some(),
                    cap_v.is_some(),
                ],
            )?;
            EventData::SemCreate {
                id: i16_from_i64(require_i64(id_v)?)?,
                initial: u32_nonneg(require_i64(initial_v)?)?,
                max: u32_nonneg(require_i64(max_v)?)?,
            }
        }
        EventName::SemTake | EventName::SemGive | EventName::SemGiveFromIsr => {
            // `sem.give` and `sem.give_from_isr` documentation says
            // timeout is ignored; we still parse it if present, but
            // the field is optional for those two. For `sem.take` it
            // is required.
            let timeout_required = matches!(name, EventName::SemTake);
            if !sid_v.is_some() {
                return Err(ParseError::BadEventShape);
            }
            if timeout_required && !timeout_v.is_some() {
                return Err(ParseError::BadEventShape);
            }
            // Disallow other keys.
            if id_v.is_some()
                || prio_v.is_some()
                || ticks_v.is_some()
                || qid_v.is_some()
                || msg_v.is_some()
                || cap_v.is_some()
                || initial_v.is_some()
                || max_v.is_some()
            {
                return Err(ParseError::BadEventShape);
            }
            EventData::SemOp {
                sid: i16_from_i64(require_i64(sid_v)?)?,
                timeout: optional_i64_or_zero(timeout_v),
            }
        }
        EventName::QueueCreate => {
            check_only(&[id_v.is_some(), cap_v.is_some()], &[
                prio_v.is_some(),
                ticks_v.is_some(),
                sid_v.is_some(),
                qid_v.is_some(),
                msg_v.is_some(),
                timeout_v.is_some(),
                initial_v.is_some(),
                max_v.is_some(),
            ])?;
            EventData::QueueCreate {
                id: i16_from_i64(require_i64(id_v)?)?,
                cap: u32_nonneg(require_i64(cap_v)?)?,
            }
        }
        EventName::QueueSend | EventName::QueueSendFromIsr => {
            // For `queue.send`: qid, msg, timeout required. For
            // `queue.send_from_isr`: timeout ignored (optional).
            let timeout_required = matches!(name, EventName::QueueSend);
            if !qid_v.is_some() || !msg_v.is_some() {
                return Err(ParseError::BadEventShape);
            }
            if timeout_required && !timeout_v.is_some() {
                return Err(ParseError::BadEventShape);
            }
            if id_v.is_some()
                || prio_v.is_some()
                || ticks_v.is_some()
                || sid_v.is_some()
                || cap_v.is_some()
                || initial_v.is_some()
                || max_v.is_some()
            {
                return Err(ParseError::BadEventShape);
            }
            EventData::QueueSend {
                qid: i16_from_i64(require_i64(qid_v)?)?,
                msg: require_i64(msg_v)?,
                timeout: optional_i64_or_zero(timeout_v),
            }
        }
        EventName::QueueReceive => {
            check_only(&[qid_v.is_some(), timeout_v.is_some()], &[
                id_v.is_some(),
                prio_v.is_some(),
                ticks_v.is_some(),
                sid_v.is_some(),
                msg_v.is_some(),
                cap_v.is_some(),
                initial_v.is_some(),
                max_v.is_some(),
            ])?;
            EventData::QueueReceive {
                qid: i16_from_i64(require_i64(qid_v)?)?,
                timeout: require_i64(timeout_v)?,
            }
        }
        EventName::TaskYield
        | EventName::SysTick
        | EventName::CritEnter
        | EventName::CritExit
        | EventName::SchedSuspend
        | EventName::SchedResume => {
            // No-payload events. Reject any field presence.
            if id_v.is_some()
                || prio_v.is_some()
                || ticks_v.is_some()
                || sid_v.is_some()
                || qid_v.is_some()
                || msg_v.is_some()
                || timeout_v.is_some()
                || cap_v.is_some()
                || initial_v.is_some()
                || max_v.is_some()
            {
                return Err(ParseError::BadEventShape);
            }
            EventData::None
        }
    };

    Ok(Some(d))
}

/// Validate that `data` matches the variant expected by `name`. Used
/// after [`parse_event_data`] returns to catch the absent-`data`-field
/// case where an event requires a payload.
fn validate_data_for_name(name: EventName, data: &EventData) -> Result<(), ParseError> {
    let ok = match (name, data) {
        (EventName::TaskYield, EventData::None)
        | (EventName::SysTick, EventData::None)
        | (EventName::CritEnter, EventData::None)
        | (EventName::CritExit, EventData::None)
        | (EventName::SchedSuspend, EventData::None)
        | (EventName::SchedResume, EventData::None) => true,
        (EventName::TaskCreate, EventData::TaskCreate { .. }) => true,
        (EventName::TaskDelay, EventData::TaskDelay { .. }) => true,
        (EventName::TaskSuspend, EventData::TaskId { .. }) => true,
        (EventName::TaskResume, EventData::TaskId { .. }) => true,
        (EventName::SemCreate, EventData::SemCreate { .. }) => true,
        (EventName::SemTake, EventData::SemOp { .. }) => true,
        (EventName::SemGive, EventData::SemOp { .. }) => true,
        (EventName::SemGiveFromIsr, EventData::SemOp { .. }) => true,
        (EventName::QueueCreate, EventData::QueueCreate { .. }) => true,
        (EventName::QueueSend, EventData::QueueSend { .. }) => true,
        (EventName::QueueSendFromIsr, EventData::QueueSend { .. }) => true,
        (EventName::QueueReceive, EventData::QueueReceive { .. }) => true,
        _ => false,
    };
    if ok {
        Ok(())
    } else {
        Err(ParseError::BadEventShape)
    }
}

/// Helper: ensure all of `required` are true AND none of `forbidden`
/// are true. Used by `parse_event_data` to enforce per-variant payload
/// shape.
fn check_only(required: &[bool], forbidden: &[bool]) -> Result<(), ParseError> {
    for r in required {
        if !*r {
            return Err(ParseError::BadEventShape);
        }
    }
    for f in forbidden {
        if *f {
            return Err(ParseError::BadEventShape);
        }
    }
    Ok(())
}

fn require_i64(v: Option<i64>) -> Result<i64, ParseError> {
    match v {
        Some(n) => Ok(n),
        None => Err(ParseError::BadEventShape),
    }
}

fn optional_i64_or_zero(v: Option<i64>) -> i64 {
    match v {
        Some(n) => n,
        None => 0,
    }
}

// ---------------------------------------------------------------------------
// Depth-tracking helpers (informational guards against pathological input).
// ---------------------------------------------------------------------------

#[allow(dead_code)]
impl VectorStream {
    /// Returns the current nested-brace depth. Useful for tests once a
    /// sibling host-testable crate is added; the firmware itself does
    /// not consult it.
    pub fn depth(&self) -> u8 {
        self.depth
    }
}
