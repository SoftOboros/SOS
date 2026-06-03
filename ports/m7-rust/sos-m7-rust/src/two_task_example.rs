//! SOS-04-B §8(d) acceptance target — a minimal two-task host example.
//!
//! This is the SOS-side mirror of disco-analyzer DAA-08 G-A1/G-A2: it
//! demonstrates that the **complete §5.5 embeddable-kernel API composes**
//! into a real host application —
//!
//!   * `create_sem` + `create_task` + `start_scheduler` at boot,
//!   * a worker task (prio > 0) that loops on `sem_take(s, -1)`,
//!   * an IRQ-style site that calls `sem_give_from_isr(s)` (returns the
//!     yield hint),
//!   * a `SysTick` body that calls `on_sys_tick()`,
//!   * the kernel's default idle (task 0 / prio 0) provided implicitly.
//!
//! **Build / run status.** This example need only **build** for
//! `thumbv7em-none-eabihf`; actually running it exercises the Cortex-M PendSV
//! save/restore asm and is **bench-gated** (cannot run on host). It is
//! compiled **only** behind the `two-task-example` Cargo feature and replaces
//! the conformance `#[entry]` when that feature is on, so the default
//! conformance build path is byte-for-byte untouched (INV-S-EMBED-1).
//!
//! Build command:
//! ```sh
//! env -u RUSTFLAGS -u CARGO_ENCODED_RUSTFLAGS \
//!   cargo build --release --target thumbv7em-none-eabihf \
//!   -p sos-m7-rust --features two-task-example
//! ```
//!
//! It is NOT the conformance firmware: the conformance bin builds with the
//! feature OFF (the default), keeping the §8(c) byte-equal trace gate intact.

use cortex_m_rt::{entry, exception};
use sos_m7_rust_kernel::embed;
use sos_m7_rust_kernel::kernel;

/// The single binary semaphore the worker blocks on and the IRQ gives.
const SEM_HANDSHAKE: u8 = 0;

/// Worker task id / priority. Idle is task 0 / prio 0 (kernel default), so a
/// prio-1 worker outranks it and is selected first by `start_scheduler`.
const WORKER_TID: kernel::TaskId = 1;
const WORKER_PRIO: u8 = 1;

/// Worker stack-bytes count consumed at create (informational — the kernel
/// owns the `TASK_STACKS` pool region per `TASK_STACK_BYTES`).
///
/// The worker task body. `extern "C" fn() -> !` per PCDN-002: it never
/// returns. Each iteration blocks on the handshake semaphore until an ISR
/// gives it, then "does work" (here a no-op the optimiser cannot elide).
extern "C" fn worker_entry() -> ! {
    loop {
        // Block until the IRQ-style giver releases the sem. timeout -1 =
        // block forever (the analyzer's `AudioSemaphore::take_blocking()`).
        embed::sem_take(SEM_HANDSHAKE, -1);

        // "Process" — a volatile bump so the body has an observable effect
        // and is not optimised to an empty spin.
        unsafe {
            let p = &raw mut WORKER_WAKEUPS;
            core::ptr::write_volatile(p, core::ptr::read_volatile(p).wrapping_add(1));
        }
    }
}

/// Observable side effect of a worker wakeup (probe-rs readable).
#[no_mangle]
static mut WORKER_WAKEUPS: u32 = 0;

/// An IRQ-style giver site. In a real host this is a peripheral / HSEM
/// doorbell ISR; here it is a free function a vector entry would call. It
/// gives the handshake sem from ISR context and returns the kernel's yield
/// hint (true ⇒ a higher-priority task — the worker — was made ready, so the
/// ISR epilogue should let PendSV switch to it). PendSV is already pended by
/// the envelope; the hint is the analyzer's `give_from_isr() -> bool` mirror.
///
/// # Safety
/// Call only from ISR context (a kernel-aware IRQ ≥ 0xA0, SOS-00 §6.1).
#[no_mangle]
pub unsafe extern "C" fn handshake_irq_body() -> bool {
    embed::sem_give_from_isr(SEM_HANDSHAKE)
}

/// SysTick handler — routes to the kernel's §5.5 tick body, which advances
/// delays/deadlines and pends PendSV iff `current` changed.
#[exception]
fn SysTick() {
    embed::on_sys_tick();
}

/// Two-task example boot. Replaces the conformance `#[entry]` under the
/// `two-task-example` feature.
#[entry]
fn main() -> ! {
    // Bring up the kernel datamodel (idle task 0 / prio 0 materialised).
    kernel::init();

    // SAFETY: boot context, single-threaded, before `start_scheduler` — the
    // construction-API safety precondition (§5.5).
    unsafe {
        // Binary handshake semaphore: initial 0, max 1.
        embed::create_sem(SEM_HANDSHAKE, 0, 1);

        // Worker task (prio 1 > idle's 0): primes its PSP frame to `worker_entry`.
        embed::create_task(WORKER_TID, WORKER_PRIO, worker_entry);

        // Touch the IRQ-style giver's address so the linker keeps it (a real
        // host wires it into its vector table; here we only need it linked).
        core::hint::black_box(handshake_irq_body as *const ());

        // Start: first PendSV switches into the highest-prio READY task
        // (the worker). Never returns.
        embed::start_scheduler()
    }
}
