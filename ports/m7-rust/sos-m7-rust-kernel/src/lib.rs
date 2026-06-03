//! sos-m7-rust-kernel — the embeddable SOS-04 M7 kernel core.
//!
//! Per SOS-04-B-EMBEDDABLE-KERNEL.md PCDN-SOS-04-B-001 = (B): the SOS-04
//! kernel core (state machine, exception handler bodies, hand-compiled
//! `<script>` bodies, and the event payload contract) is extracted out of
//! the conformance `bin` (`sos-m7-rust`) into this dependency-light
//! `no_std` library so that BOTH the conformance front-end AND foreign
//! host applications (e.g. the disco-analyzer `analyzer-cm7` build) can
//! link a single kernel core. "One kernel core, two front-ends"
//! (INV-S-EMBED-2).
//!
//! ## Scope of this crate (wave 1, PCDN-001 only)
//!
//! This crate is the result of a **behaviour-preserving extraction**
//! (INV-S-EMBED-1): the modules below are relocated unchanged from the
//! `sos-m7-rust` bin. No new API, no task-entry priming (PCDN-002), and
//! no syscall front-end (PCDN-003) land here yet — those are later waves.
//! The §5.5 host-app library API surface is therefore **not** present.
//!
//! ## What lives here vs. in the conformance bin
//!
//! - **Here (kernel core):** [`kernel`] (static pools, `Datamodel`,
//!   `init`), [`event`] (the typed event payload contract), [`scripts`]
//!   (hand-compiled chart `<script>` bodies + `dispatch_event`
//!   macrostep), [`handlers`] (the PendSV / SysTick / SVCall exception
//!   bodies — SOS-04 §6.4/§6.6/§6.5).
//! - **In the `sos-m7-rust` bin (conformance front-end):** UART
//!   transport, JSON vector parsing, BSP/clock bring-up, the on-device
//!   trace adapter, the USART1 RX interrupt, and the macrostep dispatch
//!   loop. The bin links this crate and calls into it exactly as it
//!   called the in-crate modules before the extraction.
//!
//! ## Trace immutability
//!
//! The trace wire format and its byte-equality (SOS-03 INV-S-CONF-1)
//! are unaffected: the trace writer is its own crate (`sos-m7-rust-trace`)
//! and the bin's `trace.rs` adapter still bridges this crate's
//! [`kernel::Datamodel`] to it. No serialized model state changes here.

#![no_std]

pub mod embed;
pub mod event;
// The exception-handler bodies are Cortex-M inline ARM asm (`core::arch::asm!`
// with ARMv7-M instructions) and the `#[exception]` cortex-m-rt symbols; they
// only compile on the embedded target. Gating to `target_arch = "arm"` lets
// the rest of the kernel core (and the `embed` host unit tests, SOS-04-B
// §8 gate (c)/wave-2 priming test) build on the host. The conformance bin and
// host apps build for `thumbv7em-none-eabihf` (arm), so the handlers are
// always present in any real firmware image. INV-S-EMBED-1: no model/trace
// change — this is a build-target gate only.
#[cfg(target_arch = "arm")]
pub mod handlers;
pub mod kernel;
pub mod scripts;
