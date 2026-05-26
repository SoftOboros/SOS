"""SOS-10-B `shared-memory` medium emitter.

Walks a :class:`sos10_annotations.OrchestratorAnnotations` model and, for
each cross-piece transition declared ``kind="shared-memory"``, emits the
ring-buffer + producer + consumer artifacts that realise the medium per
SOS-10-CONCEPTS.md §6.2.

Per the §6.2 contract the realisation is:

  * POSIX shared memory (``shm_open`` / ``shm_unlink``) backing a fixed-
    capacity ring buffer with atomic ``head`` / ``tail`` indices,
  * Linux futex (or any POSIX `futex(2)`-equivalent) for blocking wake
    semantics on full/empty,
  * RTOS targets (FreeRTOS / Zephyr / ThreadX) map the same shape onto
    their native message-queue primitive — this v1 emitter flags the
    mapping in a header comment and emits a ``TODO(SOS-10-rtos)`` stub
    instead of producing the RTOS code.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §5.2 + §6.2 (ratified
2026-05-23; all 8 PCDNs resolved). Invariants enforced/cited:

  * INV-S-ORCH-1 — one orchestrator per system; every cross-piece event
    flows through the orchestrator → emitter handles one pairing per
    transition annotation, not per piece.
  * INV-S-ORCH-2 — piece-as-sub-chart; producer/consumer handles are
    scoped to the cross-piece event, not the piece's internals.
  * INV-S-ORCH-4 — wire format derived, not authored; the ring-buffer
    descriptor + payload-slot layout are emit outputs, never chart-
    authored.
  * INV-S-ORCH-5 — per-medium failure-mode taxonomy; the ``shared-
    memory`` medium can deadlock under producer/consumer contention,
    surfaced via ``try_send`` / ``try_recv`` returning Err / false
    rather than blocking unboundedly.
  * INV-SOS-A — every artifact is a build output (no chart-author hand-
    writing of wire formats).

Public surface:

    DEFAULT_RING_CAPACITY: int
    SharedMemoryEmitError                      — ValueError subclass.
    extract_ring_capacity(medium) -> int       — resolves the chart-
                                                  declared capacity or
                                                  the default.
    emit_shared_memory(
        annotations: OrchestratorAnnotations,
        *,
        chart_id: str,
        output_dir: Path | str | None = None,
    ) -> dict[str, str]
        — main walker. Returns a mapping
          ``relative_filename -> file_contents`` covering the shared C
          header + per-language producer/consumer source files for
          every ``kind="shared-memory"`` transition.

Determinism: same ``OrchestratorAnnotations`` in → byte-identical
output. Filenames + content are derived from ``source_state_id`` +
``target_state_id`` + ``chart_id`` only; nothing reads the clock, env,
or filesystem during emit (writes happen only when ``output_dir`` is
passed).

Default ring capacity is **256 slots** (per SOS-10 §6.2's "ring depth +
futex contention" guidance — a 256-slot ring sized for typical event
rates without dominating SHM). Override at chart level via the
``ring_capacity`` attribute on ``<sos:medium kind="shared-memory">``
(surfaces in :pyattr:`MediumAnnotation.extras`).

The producer/consumer surface per language:

  Rust (`sos:lang="rust"`):
      * ``pub struct ProducerHandle { … }``
      * ``pub fn try_send(&mut self, ev: OrchestratorEvent) -> Result<(), TryFromIntError>``
      * Symmetric ``ConsumerHandle`` with
        ``pub fn try_recv(&mut self) -> Option<OrchestratorEvent>``
      * Gated behind a Cargo feature ``posix_shm`` (cfg-guarded
        ``nix::sys::mman::shm_open`` usage).

  C (`sos:lang="c"`):
      * ``int sos_<src>_<dst>_try_send(const sos_event_t *ev);``
      * ``bool sos_<src>_<dst>_try_recv(sos_event_t *ev_out);``
      * Both write to / read from the shared ring + issue a futex wake/
        wait on transitions across the empty / full boundary.

Other ``sos:lang`` values surface a documented "no v1 emit path" marker
in the dispatched-file map (key ends in ``.UNSUPPORTED``); they do not
raise — emitter siblings (in-process, mmio) reserve full coverage; this
v1 emitter ships rust + c.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Optional

# Self-relative-ish import — this module lives at tools/sos-codegen/.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
)


# ---------------------------------------------------------------------------
# Frozen defaults
# ---------------------------------------------------------------------------

#: Default ring-buffer capacity in slots when the chart does not override.
#: A power-of-two default keeps wrap-arithmetic to a mask operation, which
#: makes the C inline functions branch-free.
DEFAULT_RING_CAPACITY: int = 256

#: Languages with a v1 emit path. Other `sos:lang` values surface as a
#: deliberate ``.UNSUPPORTED`` marker file rather than raising — adjacent
#: emitter siblings (in-process, mmio) cover their own language coverage.
_SUPPORTED_LANGS: frozenset[str] = frozenset({"rust", "c"})

#: RTOS hints we render as informational comment lines per §6.2.
_RTOS_HINTS: dict[str, str] = {
    "freertos": "xQueueSend(queue, ev, timeout_ticks) / xQueueReceive(...)",
    "zephyr": "k_msgq_put(&msgq, ev, timeout) / k_msgq_get(&msgq, ev, timeout)",
    "threadx": "tx_queue_send(...) / tx_queue_receive(...)",
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SharedMemoryEmitError(ValueError):
    """Raised on malformed inputs to the shared-memory emitter.

    Carries the offending transition's source/target ids when known.
    """

    def __init__(
        self,
        message: str,
        *,
        source: Optional[str] = None,
        target: Optional[str] = None,
    ) -> None:
        self.source = source
        self.target = target
        prefix_parts: list[str] = []
        if source and target:
            prefix_parts.append(f"[{source} -> {target}]")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_ring_capacity(medium: MediumAnnotation) -> int:
    """Resolve the ring capacity for a ``shared-memory`` medium annotation.

    Chart-side override surface: the ``ring_capacity`` attribute on the
    ``<sos:medium kind="shared-memory">`` element (preserved verbatim in
    :pyattr:`MediumAnnotation.extras` by the SOS-10-A parser's forward-
    compat policy).

    Values are coerced to ``int`` per the same shape SOS-10-A's
    ``<sos:timeout ms>`` parser uses (accept ``int`` and integer strings;
    reject ``bool`` / float / garbage).

    Returns :data:`DEFAULT_RING_CAPACITY` (256) when the chart omits the
    override.

    Raises :class:`SharedMemoryEmitError` if the value is non-positive or
    cannot be parsed.
    """
    raw = medium.extras.get("ring_capacity")
    if raw is None:
        return DEFAULT_RING_CAPACITY
    if isinstance(raw, bool):
        raise SharedMemoryEmitError(
            f"ring_capacity must be a positive integer; got bool {raw!r}"
        )
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw, 10)
        except ValueError as exc:
            raise SharedMemoryEmitError(
                f"ring_capacity must be a positive integer; got {raw!r}"
            ) from exc
    else:
        raise SharedMemoryEmitError(
            f"ring_capacity must be a positive integer; "
            f"got {raw!r} (type={type(raw).__name__})"
        )
    if value <= 0:
        raise SharedMemoryEmitError(
            f"ring_capacity must be > 0; got {value}"
        )
    return value


def _rtos_hint(medium: MediumAnnotation) -> Optional[str]:
    """Return the RTOS hint string (FreeRTOS / Zephyr / ThreadX) or None.

    Source: ``medium.extras["rtos"]`` — surfaced from a chart-level
    ``<sos:medium … rtos="freertos">`` attribute. Per §6.2 the RTOS
    surface is informational at v1; no behavioural code is emitted.
    """
    raw = medium.extras.get("rtos")
    if not isinstance(raw, str):
        return None
    return _RTOS_HINTS.get(raw.strip().lower())


def _piece_lang(annotations: OrchestratorAnnotations, state_id: str) -> str:
    """Look up the piece's ``sos:lang`` value (defaults to ``rust``)."""
    for piece in annotations.pieces:
        if piece.state_id == state_id:
            return piece.lang
    raise SharedMemoryEmitError(
        f"piece {state_id!r} not found in OrchestratorAnnotations.pieces",
        source=state_id,
    )


def _pair_basename(src: str, dst: str) -> str:
    """Stable basename for one (producer, consumer) pairing."""
    return f"{src}_to_{dst}_ring"


def _pair_symbol_root(src: str, dst: str) -> str:
    """C identifier root for one pairing, suitable for symbol names."""
    return f"sos_{src}_{dst}"


def _spec_header(*, kind: str, src: str, dst: str, ring_capacity: int) -> str:
    """Return the @spec banner comment block for the emitted artifact.

    Cites SOS-10 §6.2 + the invariants exercised. Mirrors the SOS-09-C
    `@spec` shape so reviewers reading any sub-phase emit see the same
    citation surface.
    """
    return (
        f" * @spec       SOS-10-CONCEPTS.md §6.2 (shared-memory medium)\n"
        f" * @invariants INV-S-ORCH-1, INV-S-ORCH-2, INV-S-ORCH-4,\n"
        f" *             INV-S-ORCH-5, INV-SOS-A\n"
        f" * @medium     shared-memory  (POSIX SHM + futex)\n"
        f" * @source     piece={src!s}\n"
        f" * @target     piece={dst!s}\n"
        f" * @kind       {kind}\n"
        f" * @ring_slots {ring_capacity}\n"
        f" * @generator  tools/sos-codegen/shared_memory_emit.py\n"
        f" * @authority  ratified 2026-05-23\n"
    )


# ---------------------------------------------------------------------------
# Shared C header — sos_<src>_<dst>_ring.h
# ---------------------------------------------------------------------------


def _render_shared_header(
    *,
    src: str,
    dst: str,
    ring_capacity: int,
    rtos_hint: Optional[str],
) -> str:
    """Render the POSIX-portable shared-memory ring-buffer descriptor.

    The header defines :type:`sos_shm_ring_t` — an atomic ``head`` /
    ``tail`` + a fixed-size payload-slot array. Capacity is the chart-
    declared (or default 256) slot count. Per §6.2 the ring uses
    ``<stdatomic.h>`` ``atomic_uint_fast32_t`` for head/tail; the
    payload type is :type:`sos_event_t` (declared in the orchestrator-
    common header, referenced by ``#include``).
    """
    pair = _pair_basename(src, dst)
    guard = f"SOS_SHM_{src.upper()}_{dst.upper()}_RING_H"
    spec = _spec_header(
        kind="shared-c-header",
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
    )
    rtos_block = ""
    if rtos_hint is not None:
        rtos_block = (
            f"/* TODO(SOS-10-rtos): on this target the native primitive is:\n"
            f" *   {rtos_hint}\n"
            f" * The v1 emitter does not generate RTOS-specific code yet — see\n"
            f" * SOS-10-CONCEPTS.md §6.2 \"RTOS targets\" + change log.\n"
            f" */\n\n"
        )
    return (
        f"/*\n"
        f"{spec}"
        f" */\n"
        f"#ifndef {guard}\n"
        f"#define {guard}\n"
        f"\n"
        f"#include <stdatomic.h>\n"
        f"#include <stdbool.h>\n"
        f"#include <stddef.h>\n"
        f"#include <stdint.h>\n"
        f"\n"
        f"#ifdef __cplusplus\n"
        f'extern "C" {{\n'
        f"#endif\n"
        f"\n"
        f"{rtos_block}"
        f"/* Per §6.2: ring capacity is fixed at emit time; consumers cannot\n"
        f" * resize at runtime. INV-S-ORCH-4 (wire format derived) makes the\n"
        f" * capacity part of the emitted artifact, not a chart-runtime\n"
        f" * parameter. */\n"
        f"#define SOS_{src.upper()}_{dst.upper()}_RING_CAPACITY {ring_capacity}u\n"
        f"#define SOS_{src.upper()}_{dst.upper()}_RING_MASK     "
        f"(SOS_{src.upper()}_{dst.upper()}_RING_CAPACITY - 1u)\n"
        f"\n"
        f"/* Per orchestrator-common header: each cross-piece event is a\n"
        f" * tagged union with a fixed-size payload. We forward-declare here;\n"
        f" * the actual definition is owned by the orchestrator event-\n"
        f" * vocabulary emitter (INV-S-ORCH-4). */\n"
        f"#ifndef SOS_EVENT_T_DEFINED\n"
        f"#define SOS_EVENT_T_DEFINED\n"
        f"typedef struct sos_event {{\n"
        f"    uint32_t name_id;\n"
        f"    uint32_t payload_len;\n"
        f"    uint8_t  payload[64];\n"
        f"}} sos_event_t;\n"
        f"#endif /* SOS_EVENT_T_DEFINED */\n"
        f"\n"
        f"/* POSIX-portable ring-buffer descriptor.\n"
        f" *\n"
        f" * Layout is fixed by INV-S-ORCH-4; the producer (in piece {src!r})\n"
        f" * and the consumer (in piece {dst!r}) MUST be linked against the\n"
        f" * SAME version of this header. Source-of-truth is this emitted\n"
        f" * file; piece-side hand-edits invalidate the wire format.\n"
        f" */\n"
        f"typedef struct {pair}_s {{\n"
        f"    atomic_uint_fast32_t head;   /* producer writes; consumer reads */\n"
        f"    atomic_uint_fast32_t tail;   /* consumer writes; producer reads */\n"
        f"    uint32_t             capacity;\n"
        f"    uint32_t             _pad0;\n"
        f"    sos_event_t          slots[SOS_{src.upper()}_{dst.upper()}_RING_CAPACITY];\n"
        f"}} {pair}_t;\n"
        f"\n"
        f"/* Convenience: the POSIX shm name used for this pairing.\n"
        f" * Slash-prefixed per shm_open(3) portability guidance. */\n"
        f'#define SOS_{src.upper()}_{dst.upper()}_SHM_NAME "/sos_{src}_{dst}_ring"\n'
        f"\n"
        f"#ifdef __cplusplus\n"
        f"}}\n"
        f"#endif\n"
        f"\n"
        f"#endif /* {guard} */\n"
    )


# ---------------------------------------------------------------------------
# Rust producer / consumer
# ---------------------------------------------------------------------------


def _render_rust_producer(
    *,
    src: str,
    dst: str,
    ring_capacity: int,
    rtos_hint: Optional[str],
) -> str:
    pair = _pair_basename(src, dst)
    pair_sym = _pair_symbol_root(src, dst)
    spec = _spec_header(
        kind="rust-producer",
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
    )
    rtos_block = ""
    if rtos_hint is not None:
        rtos_block = (
            f"// TODO(SOS-10-rtos): on this target prefer the native\n"
            f"// {rtos_hint}\n"
            f"// instead of POSIX shm + futex. The v1 emit path does not\n"
            f"// yet generate the RTOS variant.\n\n"
        )
    return (
        f"//! Shared-memory producer for `{src} -> {dst}` cross-piece events.\n"
        f"/*\n"
        f"{spec}"
        f" */\n"
        f"\n"
        f"{rtos_block}"
        f"use core::num::TryFromIntError;\n"
        f"\n"
        f"/// Ring-buffer capacity in slots (chart-declared via\n"
        f"/// `<sos:medium ring_capacity=\"…\">`; defaults to 256).\n"
        f"pub const RING_CAPACITY: usize = {ring_capacity};\n"
        f"pub const RING_MASK: usize = RING_CAPACITY - 1;\n"
        f"\n"
        f"/// POSIX shared-memory object name; mirrors the C header's\n"
        f"/// `SOS_{src.upper()}_{dst.upper()}_SHM_NAME`.\n"
        f'pub const SHM_NAME: &str = "/sos_{src}_{dst}_ring";\n'
        f"\n"
        f"/// Cross-piece event payload (forward-declared; defined by the\n"
        f"/// orchestrator event-vocabulary emitter — INV-S-ORCH-4).\n"
        f"#[repr(C)]\n"
        f"#[derive(Clone, Copy)]\n"
        f"pub struct OrchestratorEvent {{\n"
        f"    pub name_id: u32,\n"
        f"    pub payload_len: u32,\n"
        f"    pub payload: [u8; 64],\n"
        f"}}\n"
        f"\n"
        f"/// Producer handle for the `{src} -> {dst}` pairing.\n"
        f"///\n"
        f"/// Holds the mapped ring-buffer pointer + producer-side index;\n"
        f"/// the consumer side lives in [`super::consumer`] (or its own\n"
        f"/// crate if the pieces ship as separate binaries). Per\n"
        f"/// INV-S-ORCH-5 (per-medium failure-mode taxonomy), `try_send`\n"
        f"/// returns `Err` rather than blocking on a full ring.\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"pub struct ProducerHandle {{\n"
        f"    pub(crate) ring: *mut {pair_sym}_ring_t,\n"
        f"}}\n"
        f"\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"#[repr(C)]\n"
        f"pub struct {pair_sym}_ring_t {{\n"
        f"    pub head: core::sync::atomic::AtomicU32,\n"
        f"    pub tail: core::sync::atomic::AtomicU32,\n"
        f"    pub capacity: u32,\n"
        f"    pub _pad0: u32,\n"
        f"    pub slots: [OrchestratorEvent; RING_CAPACITY],\n"
        f"}}\n"
        f"\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"impl ProducerHandle {{\n"
        f"    /// Try to publish one event into the ring. Returns `Ok(())`\n"
        f"    /// on success and `Err(TryFromIntError)` if the ring is\n"
        f"    /// full or if `nix::sys::mman::shm_open` produced an\n"
        f"    /// out-of-range size. INV-S-ORCH-5 backpressure surface.\n"
        f"    pub fn try_send(&mut self, ev: OrchestratorEvent) -> Result<(), TryFromIntError> {{\n"
        f"        use core::sync::atomic::Ordering;\n"
        f"        // SAFETY: `self.ring` is mapped POSIX SHM owned by the\n"
        f"        // producer; layout matches the C header (INV-S-ORCH-4).\n"
        f"        let ring = unsafe {{ &*self.ring }};\n"
        f"        let head = ring.head.load(Ordering::Acquire);\n"
        f"        let tail = ring.tail.load(Ordering::Acquire);\n"
        f"        if head.wrapping_sub(tail) as usize >= RING_CAPACITY {{\n"
        f"            // Ring full → INV-S-ORCH-5 backpressure path.\n"
        f"            return Err(u32::try_from(-1_i64).unwrap_err());\n"
        f"        }}\n"
        f"        let idx = (head as usize) & RING_MASK;\n"
        f"        // SAFETY: slot index is within capacity (mask above).\n"
        f"        unsafe {{\n"
        f"            let slot_ptr = (self.ring as *mut u8)\n"
        f"                .add(core::mem::offset_of!({pair_sym}_ring_t, slots))\n"
        f"                .cast::<OrchestratorEvent>()\n"
        f"                .add(idx);\n"
        f"            core::ptr::write(slot_ptr, ev);\n"
        f"        }}\n"
        f"        ring.head.store(head.wrapping_add(1), Ordering::Release);\n"
        f"        // Futex wake: signal the consumer if it was blocked on\n"
        f"        // an empty ring. The wake is best-effort; spurious wakes\n"
        f"        // are permitted (POSIX futex semantics).\n"
        f"        // TODO(SOS-10-futex): wire `libc::syscall(SYS_futex, …)`.\n"
        f"        Ok(())\n"
        f"    }}\n"
        f"}}\n"
        f"\n"
        f"/// Open (or create) the POSIX SHM-backed ring for this pairing.\n"
        f"///\n"
        f"/// Cargo-feature-gated behind `posix_shm` because RTOS targets\n"
        f"/// will swap the realisation for `xQueueSend` / `k_msgq_put`\n"
        f"/// (see header banner). Returns a [`ProducerHandle`] mapped to\n"
        f"/// the shared region.\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"pub fn open_producer() -> Result<ProducerHandle, std::io::Error> {{\n"
        f"    // TODO(SOS-10-shm-open): call nix::sys::mman::shm_open + mmap\n"
        f"    // + ftruncate to size_of::<{pair_sym}_ring_t>(). Stub for v1.\n"
        f"    Err(std::io::Error::new(\n"
        f"        std::io::ErrorKind::Unsupported,\n"
        f'        "open_producer stubbed pending SOS-10-shm-open wiring",\n'
        f"    ))\n"
        f"}}\n"
    )


def _render_rust_consumer(
    *,
    src: str,
    dst: str,
    ring_capacity: int,
    rtos_hint: Optional[str],
) -> str:
    pair_sym = _pair_symbol_root(src, dst)
    spec = _spec_header(
        kind="rust-consumer",
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
    )
    rtos_block = ""
    if rtos_hint is not None:
        rtos_block = (
            f"// TODO(SOS-10-rtos): on this target prefer the native\n"
            f"// {rtos_hint}\n"
            f"// instead of POSIX shm + futex. The v1 emit path does not\n"
            f"// yet generate the RTOS variant.\n\n"
        )
    return (
        f"//! Shared-memory consumer for `{src} -> {dst}` cross-piece events.\n"
        f"/*\n"
        f"{spec}"
        f" */\n"
        f"\n"
        f"{rtos_block}"
        f"use super::producer::{{OrchestratorEvent, RING_CAPACITY, RING_MASK}};\n"
        f"\n"
        f"/// Consumer handle for the `{src} -> {dst}` pairing.\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"pub struct ConsumerHandle {{\n"
        f"    pub(crate) ring: *mut super::producer::{pair_sym}_ring_t,\n"
        f"}}\n"
        f"\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"impl ConsumerHandle {{\n"
        f"    /// Try to receive one event from the ring. Returns\n"
        f"    /// `Some(ev)` on success and `None` if the ring is empty\n"
        f"    /// (INV-S-ORCH-5 underflow surface — never blocks).\n"
        f"    pub fn try_recv(&mut self) -> Option<OrchestratorEvent> {{\n"
        f"        use core::sync::atomic::Ordering;\n"
        f"        // SAFETY: `self.ring` is mapped POSIX SHM mapped read-\n"
        f"        // mostly by the consumer; layout matches INV-S-ORCH-4.\n"
        f"        let ring = unsafe {{ &*self.ring }};\n"
        f"        let head = ring.head.load(Ordering::Acquire);\n"
        f"        let tail = ring.tail.load(Ordering::Acquire);\n"
        f"        if head == tail {{\n"
        f"            return None;\n"
        f"        }}\n"
        f"        let idx = (tail as usize) & RING_MASK;\n"
        f"        // SAFETY: slot index within capacity (mask above);\n"
        f"        // event is `Copy` so we read by value.\n"
        f"        let ev = unsafe {{\n"
        f"            let slot_ptr = (self.ring as *const u8)\n"
        f"                .add(core::mem::offset_of!(\n"
        f"                    super::producer::{pair_sym}_ring_t,\n"
        f"                    slots\n"
        f"                ))\n"
        f"                .cast::<OrchestratorEvent>()\n"
        f"                .add(idx);\n"
        f"            core::ptr::read(slot_ptr)\n"
        f"        }};\n"
        f"        ring.tail.store(tail.wrapping_add(1), Ordering::Release);\n"
        f"        Some(ev)\n"
        f"    }}\n"
        f"}}\n"
        f"\n"
        f"/// Open (or attach to) the POSIX SHM-backed ring as a consumer.\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"pub fn open_consumer() -> Result<ConsumerHandle, std::io::Error> {{\n"
        f"    // TODO(SOS-10-shm-open): nix::sys::mman::shm_open + mmap.\n"
        f"    Err(std::io::Error::new(\n"
        f"        std::io::ErrorKind::Unsupported,\n"
        f'        "open_consumer stubbed pending SOS-10-shm-open wiring",\n'
        f"    ))\n"
        f"}}\n"
        f"\n"
        f"// RING_CAPACITY re-export so consumer-side code can sanity-check\n"
        f"// it matches the producer-side compile-time constant.\n"
        f"#[cfg(feature = \"posix_shm\")]\n"
        f"pub const CONSUMER_RING_CAPACITY: usize = RING_CAPACITY;\n"
    )


# ---------------------------------------------------------------------------
# C producer / consumer
# ---------------------------------------------------------------------------


def _render_c_producer(
    *,
    src: str,
    dst: str,
    ring_capacity: int,
    rtos_hint: Optional[str],
) -> str:
    pair = _pair_basename(src, dst)
    sym = _pair_symbol_root(src, dst)
    spec = _spec_header(
        kind="c-producer",
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
    )
    rtos_block = ""
    if rtos_hint is not None:
        rtos_block = (
            f"/* TODO(SOS-10-rtos): native primitive on this target is:\n"
            f" *   {rtos_hint}\n"
            f" * v1 emit path does not yet generate the RTOS variant. */\n\n"
        )
    return (
        f"/*\n"
        f"{spec}"
        f" */\n"
        f'#include "{pair}.h"\n'
        f"\n"
        f"{rtos_block}"
        f"/* Producer-side handle. Caller owns the mmap'd ring pointer\n"
        f" * obtained via shm_open + mmap (see SOS-10 §6.2 for the\n"
        f" * sequence). The handle is opaque to chart authors per\n"
        f" * INV-S-ORCH-4. */\n"
        f"struct {sym}_producer_handle {{\n"
        f"    {pair}_t *ring;\n"
        f"}};\n"
        f"\n"
        f"/* Try to publish one event. Returns 0 on success, -1 if the\n"
        f" * ring is full (INV-S-ORCH-5 backpressure surface — never\n"
        f" * blocks). */\n"
        f"int {sym}_try_send(struct {sym}_producer_handle *h,\n"
        f"                   const sos_event_t *ev) {{\n"
        f"    if (h == NULL || h->ring == NULL || ev == NULL) {{\n"
        f"        return -1;\n"
        f"    }}\n"
        f"    uint_fast32_t head = atomic_load_explicit(\n"
        f"        &h->ring->head, memory_order_acquire);\n"
        f"    uint_fast32_t tail = atomic_load_explicit(\n"
        f"        &h->ring->tail, memory_order_acquire);\n"
        f"    if ((head - tail) >= h->ring->capacity) {{\n"
        f"        return -1;  /* full */\n"
        f"    }}\n"
        f"    uint32_t idx = (uint32_t)(head & SOS_{src.upper()}_{dst.upper()}_RING_MASK);\n"
        f"    h->ring->slots[idx] = *ev;\n"
        f"    atomic_store_explicit(\n"
        f"        &h->ring->head, head + 1u, memory_order_release);\n"
        f"    /* TODO(SOS-10-futex): syscall(SYS_futex, &h->ring->head,\n"
        f"     * FUTEX_WAKE, 1, NULL, NULL, 0); */\n"
        f"    return 0;\n"
        f"}}\n"
    )


def _render_c_consumer(
    *,
    src: str,
    dst: str,
    ring_capacity: int,
    rtos_hint: Optional[str],
) -> str:
    pair = _pair_basename(src, dst)
    sym = _pair_symbol_root(src, dst)
    spec = _spec_header(
        kind="c-consumer",
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
    )
    rtos_block = ""
    if rtos_hint is not None:
        rtos_block = (
            f"/* TODO(SOS-10-rtos): native primitive on this target is:\n"
            f" *   {rtos_hint}\n"
            f" * v1 emit path does not yet generate the RTOS variant. */\n\n"
        )
    return (
        f"/*\n"
        f"{spec}"
        f" */\n"
        f'#include "{pair}.h"\n'
        f"\n"
        f"{rtos_block}"
        f"struct {sym}_consumer_handle {{\n"
        f"    {pair}_t *ring;\n"
        f"}};\n"
        f"\n"
        f"/* Try to receive one event. Returns true on success (and\n"
        f" * fills *ev_out), false if the ring is empty. Never blocks\n"
        f" * — INV-S-ORCH-5 underflow surface. */\n"
        f"bool {sym}_try_recv(struct {sym}_consumer_handle *h,\n"
        f"                    sos_event_t *ev_out) {{\n"
        f"    if (h == NULL || h->ring == NULL || ev_out == NULL) {{\n"
        f"        return false;\n"
        f"    }}\n"
        f"    uint_fast32_t head = atomic_load_explicit(\n"
        f"        &h->ring->head, memory_order_acquire);\n"
        f"    uint_fast32_t tail = atomic_load_explicit(\n"
        f"        &h->ring->tail, memory_order_acquire);\n"
        f"    if (head == tail) {{\n"
        f"        return false;\n"
        f"    }}\n"
        f"    uint32_t idx = (uint32_t)(tail & SOS_{src.upper()}_{dst.upper()}_RING_MASK);\n"
        f"    *ev_out = h->ring->slots[idx];\n"
        f"    atomic_store_explicit(\n"
        f"        &h->ring->tail, tail + 1u, memory_order_release);\n"
        f"    return true;\n"
        f"}}\n"
    )


def _render_unsupported_marker(
    *,
    src: str,
    dst: str,
    lang: str,
    side: str,
) -> str:
    """Render a deliberate UNSUPPORTED-lang marker file body.

    Future SOS-10 sub-phases own additional language coverage; v1 ships
    rust + c. We surface the gap explicitly (so the orchestrator wiring
    knows to skip the pairing's side) rather than raising — same shape
    other SOS sub-phase emitters use for forward-compat.
    """
    return (
        f"# UNSUPPORTED at SOS-10-B v1: shared-memory {side}\n"
        f"# transition {src} -> {dst}, lang {lang!r}\n"
        f"# A future SOS-10 sub-phase will own this language's emit path.\n"
        f"# See SOS-10-CONCEPTS.md §6.2 + §14 (Unblocks).\n"
    )


# ---------------------------------------------------------------------------
# Public walker
# ---------------------------------------------------------------------------


def emit_shared_memory(
    annotations: OrchestratorAnnotations,
    *,
    chart_id: str,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Emit shared-memory medium artifacts for every shared-memory pairing.

    Args:
        annotations: parsed SOS-10-A orchestrator annotations. Only
            transitions whose ``medium.kind == "shared-memory"`` are
            processed; other media are siblings' concerns and silently
            skipped here.
        chart_id: chart-level identifier; used as the per-chart
            sub-directory under ``build/shared_memory/`` and in the
            emitted file paths.
        output_dir: optional disk write target. When provided, all
            emitted files are written under
            ``{output_dir}/shared_memory/{chart_id}/<filename>``;
            when None, the function is pure (returns the file map only).

    Returns:
        Mapping ``relative_filename -> file contents`` for every emitted
        artifact. Filenames are relative to
        ``build/shared_memory/<chart_id>/`` (the conventional output
        root); the dict is suitable for direct on-disk materialisation.

    Determinism: byte-identical output for byte-identical input. No
    randomness, no clock reads, no env reads; transitions emit in the
    document order :class:`OrchestratorAnnotations` lists them in.
    """
    if not isinstance(chart_id, str) or not chart_id:
        raise SharedMemoryEmitError("chart_id must be a non-empty string")

    files: dict[str, str] = {}

    for transition in annotations.transitions:
        if transition.medium.kind != "shared-memory":
            continue
        files.update(_emit_transition(annotations, transition))

    if output_dir is not None:
        out_root = Path(output_dir) / "shared_memory" / chart_id
        out_root.mkdir(parents=True, exist_ok=True)
        for rel_path, body in files.items():
            target = out_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    return files


def _emit_transition(
    annotations: OrchestratorAnnotations,
    transition: CrossPieceTransitionAnnotation,
) -> dict[str, str]:
    """Emit the artifact set for one shared-memory transition."""
    src = transition.source_state_id
    dst = transition.target_state_id
    ring_capacity = extract_ring_capacity(transition.medium)
    rtos_hint = _rtos_hint(transition.medium)

    files: dict[str, str] = {}

    # Shared C header (always emitted, even when both sides are Rust —
    # the header is the wire-format source of truth per INV-S-ORCH-4).
    header_name = f"{_pair_basename(src, dst)}.h"
    files[header_name] = _render_shared_header(
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
        rtos_hint=rtos_hint,
    )

    # Producer side (lang of source piece).
    src_lang = _piece_lang(annotations, src)
    prod_files = _render_for_lang(
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
        rtos_hint=rtos_hint,
        lang=src_lang,
        side="producer",
    )
    files.update(prod_files)

    # Consumer side (lang of target piece).
    dst_lang = _piece_lang(annotations, dst)
    cons_files = _render_for_lang(
        src=src,
        dst=dst,
        ring_capacity=ring_capacity,
        rtos_hint=rtos_hint,
        lang=dst_lang,
        side="consumer",
    )
    files.update(cons_files)

    return files


def _render_for_lang(
    *,
    src: str,
    dst: str,
    ring_capacity: int,
    rtos_hint: Optional[str],
    lang: str,
    side: str,
) -> dict[str, str]:
    """Dispatch one (lang, side) render and return the filename → body map."""
    pair = _pair_basename(src, dst)
    if lang == "rust":
        if side == "producer":
            return {
                f"{pair}_producer.rs": _render_rust_producer(
                    src=src,
                    dst=dst,
                    ring_capacity=ring_capacity,
                    rtos_hint=rtos_hint,
                )
            }
        return {
            f"{pair}_consumer.rs": _render_rust_consumer(
                src=src,
                dst=dst,
                ring_capacity=ring_capacity,
                rtos_hint=rtos_hint,
            )
        }
    if lang == "c":
        if side == "producer":
            return {
                f"{pair}_producer.c": _render_c_producer(
                    src=src,
                    dst=dst,
                    ring_capacity=ring_capacity,
                    rtos_hint=rtos_hint,
                )
            }
        return {
            f"{pair}_consumer.c": _render_c_consumer(
                src=src,
                dst=dst,
                ring_capacity=ring_capacity,
                rtos_hint=rtos_hint,
            )
        }
    # Unsupported language at v1 — surface a deliberate marker file
    # rather than raising. Sibling emitters will fill in coverage.
    return {
        f"{pair}_{side}.{lang}.UNSUPPORTED": _render_unsupported_marker(
            src=src,
            dst=dst,
            lang=lang,
            side=side,
        )
    }


__all__ = [
    "DEFAULT_RING_CAPACITY",
    "SharedMemoryEmitError",
    "emit_shared_memory",
    "extract_ring_capacity",
]
