//! The macrostep harness. See SOS-02 §6.2 for the execution model.

use crate::datamodel::Datamodel;
use crate::error::SimError;
use crate::event::{Event, EventName};
use crate::script_provider::ScriptProvider;
use crate::trace::Trace;
use crate::vector::{Config, Vector};

/// Safety cap on the per-macrostep internal-event drain loop. The chart's
/// `<transition>` bodies raise at most `sched.run` once per external event,
/// and the scheduler transition does not re-raise, so quiescence is reached
/// in 1–2 iterations under correct behaviour. The cap guards against a
/// runaway script that re-arms `resched` indefinitely.
const MAX_MICROSTEP_ITERATIONS: usize = 100;

/// Canonical name of the chart's `<state id="boot"><onentry><script>` block
/// per SOS-02 §6.3. The harness invokes this directly during construction —
/// `kernel.boot.done` is an *internal* event in the chart and is therefore
/// not a member of `EventName` (which models only external events).
const SCRIPT_BOOT_ONENTRY: &str = "script_boot_onentry_0";

/// Canonical name of the scheduler's `sched.run` transition body per
/// SOS-02 §6.3. The harness invokes this whenever a transition body sets
/// `dm.resched = true`, modelling the chart's `<raise event="sched.run"/>`.
const SCRIPT_SCHED_RUN: &str = "script_sched_idle_sched_run_0";

/// Top-level kernel instance. Owns a [`Datamodel`], a [`ScriptProvider`]
/// (the v1 default is [`crate::HandCompiledScripts`]), and a [`Trace`]
/// buffer.
///
/// One `Simulator` value hosts exactly one kernel — INV-S-SIM-10.
pub struct Simulator<P: ScriptProvider> {
    /// The mutable kernel state.
    dm: Datamodel,
    /// Script-execution backend (v1: `HandCompiledScripts`).
    scripts: P,
    /// Trace buffer accumulated during `run_vector`.
    trace: Trace,
}

impl<P: ScriptProvider> Simulator<P> {
    /// Construct a fresh simulator sized per `config`. Drives the boot
    /// macrostep to quiescence and emits the `after_input_idx = -1`
    /// baseline trace record per SOS-02 §6.2 and §6.4.
    pub fn new(config: Config, scripts: P) -> Self {
        let dm = Datamodel::new(&config);
        let mut sim = Simulator {
            dm,
            scripts,
            trace: Trace {
                records: Vec::new(),
            },
        };

        // Run the chart's `<state id="boot"><onentry><script>` body to
        // drive the boot macrostep, then drain any internal events
        // (`sched.run`) the boot script raised, to quiescence.
        let boot_ev = Event {
            // The boot script does not read `_event.data`; any
            // placeholder event satisfies the signature.
            name: EventName::TaskYield,
            data: serde_json::Value::Null,
            from_tid: None,
        };
        // Errors during boot turn into a panic — boot must succeed to
        // produce a coherent baseline; a faulty boot is a simulator
        // bug, not a vector-input bug.
        sim.run_macrostep(SCRIPT_BOOT_ONENTRY, &boot_ev)
            .expect("boot macrostep must reach quiescence");

        // Emit the SOS-02 §6.2 step-6 boot-quiescence baseline record.
        sim.trace.records.push(Trace::snapshot(&sim.dm, -1));

        sim
    }

    /// Run a complete vector to completion. Returns a borrow of the
    /// accumulated trace on success. See SOS-02 §6.2 for the step model.
    pub fn run_vector(&mut self, vector: &Vector) -> Result<&Trace, SimError> {
        for (idx, event) in vector.input.iter().enumerate() {
            // Per SOS-00 §7.1, `from_tid` is an injection mechanism:
            // before dispatching, set `current` to the issuer's task id.
            // ISR-context events carry `from_tid: None`; leave `current`
            // untouched in that case.
            if let Some(tid) = event.from_tid {
                self.dm.current = tid;
            }
            self.step(event.clone())?;
            // INV-S-SIM-6: one trace record per macrostep quiescence.
            self.trace
                .records
                .push(Trace::snapshot(&self.dm, idx as i64));
        }
        Ok(&self.trace)
    }

    /// Drive one external event through the macrostep harness, then run
    /// internal events to quiescence. Does NOT emit a trace record;
    /// `run_vector` owns the emission point per INV-S-SIM-6.
    pub fn step(&mut self, event: Event) -> Result<(), SimError> {
        let script_name = script_name_for_event(event.name);
        self.run_macrostep(script_name, &event)
    }

    /// Borrow the current datamodel for inspection.
    pub fn datamodel(&self) -> &Datamodel {
        &self.dm
    }

    /// Borrow the accumulated trace.
    pub fn trace(&self) -> &Trace {
        &self.trace
    }

    /// Borrow the script provider.
    pub fn scripts(&self) -> &P {
        &self.scripts
    }

    /// Run one transition body, then drain internal-event raises to
    /// quiescence. The internal-event surface in the chart is exactly
    /// `<raise event="sched.run"/>`, which we model as the boolean
    /// `dm.resched`; the boot macrostep additionally raises
    /// `kernel.boot.done` whose only consumer is the `boot → running`
    /// transition (purely structural, no script body).
    ///
    /// Quiescence is `dm.resched == false` after the most recent
    /// dispatch. The loop is capped by `MAX_MICROSTEP_ITERATIONS` to
    /// surface runaway re-arming as a `SimError::Runtime` rather than a
    /// hang.
    fn run_macrostep(&mut self, script_name: &str, event: &Event) -> Result<(), SimError> {
        // External-event (or boot-onentry) transition body.
        self.scripts.run_script(script_name, &mut self.dm, event)?;

        // Internal-event drain: while a body raised sched.run, dispatch
        // the scheduler transition and re-check.
        let mut iter = 0usize;
        let internal_ev = Event {
            name: EventName::TaskYield, // placeholder; scheduler ignores ev
            data: serde_json::Value::Null,
            from_tid: None,
        };
        while self.dm.resched {
            self.dm.resched = false;
            self.scripts
                .run_script(SCRIPT_SCHED_RUN, &mut self.dm, &internal_ev)?;
            iter += 1;
            if iter >= MAX_MICROSTEP_ITERATIONS {
                return Err(SimError::Runtime(
                    "macrostep did not reach quiescence within MAX_MICROSTEP_ITERATIONS".into(),
                ));
            }
        }
        Ok(())
    }
}

/// Map an external event name to its canonical SOS-02 §6.3 script name.
///
/// One arm per ExternalEventName variant (18 entries — see SOS-01 §5.3
/// and the SOS-02 §6.3 script-name table).
fn script_name_for_event(name: EventName) -> &'static str {
    match name {
        EventName::TaskCreate => "script_sys_idle_task_create_0",
        EventName::TaskDelay => "script_sys_idle_task_delay_0",
        EventName::TaskYield => "script_sys_idle_task_yield_0",
        EventName::TaskSuspend => "script_sys_idle_task_suspend_0",
        EventName::TaskResume => "script_sys_idle_task_resume_0",
        EventName::SemCreate => "script_sys_idle_sem_create_0",
        EventName::SemTake => "script_sys_idle_sem_take_0",
        EventName::SemGive => "script_sys_idle_sem_give_0",
        EventName::SemGiveFromIsr => "script_sys_idle_sem_give_from_isr_0",
        EventName::QueueCreate => "script_sys_idle_queue_create_0",
        EventName::QueueSend => "script_sys_idle_queue_send_0",
        EventName::QueueReceive => "script_sys_idle_queue_receive_0",
        EventName::QueueSendFromIsr => "script_sys_idle_queue_send_from_isr_0",
        EventName::SysTick => "script_tick_idle_sys_tick_0",
        EventName::CritEnter => "script_prot_idle_crit_enter_0",
        EventName::CritExit => "script_prot_idle_crit_exit_0",
        EventName::SchedSuspend => "script_prot_idle_sched_suspend_0",
        EventName::SchedResume => "script_prot_idle_sched_resume_0",
    }
}
