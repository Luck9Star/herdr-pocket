//! Paired-form observation bridge. The dashboard and terminal share one
//! authenticated SSH owner; the UI can only select the exact reviewed row.
use crate::dashboard_review::DashboardReview;
use crate::{
    self as transport, Audit, Cancellation, ControlledInputHooks, DashboardTarget, DeviceSigner,
    ObservationControl, ObservationSnapshot, Pane, RemoteConfig, StreamFrame, input::LiveInput,
    session_watch::SessionWatchUpdate,
};
use serde::Serialize;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
use tokio::sync::oneshot;

#[derive(Serialize, Clone)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ObserveEvent {
    Stage {
        generation: u64,
        stage: &'static str,
    },
    Observation {
        generation: u64,
        snapshot: ObservationSnapshot,
    },
    DashboardWatch {
        generation: u64,
        update: SessionWatchUpdate,
    },
    SelectionReady {
        generation: u64,
        epoch: u64,
    },
    TargetBound {
        generation: u64,
        epoch: u64,
        pane_id: String,
        terminal_id: String,
    },
    Frame {
        generation: u64,
        epoch: u64,
        frame: StreamFrame,
    },
    InputReady {
        generation: u64,
        epoch: u64,
        unknown: bool,
        recovery_status: &'static str,
    },
}

#[derive(Default)]
struct Pending {
    dashboard: DashboardReview,
    select: Option<(u64, oneshot::Sender<DashboardTarget>)>,
    selected: Option<DashboardTarget>,
    ack: Option<(u64, u64, oneshot::Sender<()>)>,
    input: Option<(u64, Arc<LiveInput>)>,
}

pub struct DirectObservation {
    generation: u64,
    cancel: Cancellation,
    control: ObservationControl,
    retired: AtomicBool,
    pending: Mutex<Pending>,
}
type Emit = Arc<dyn Fn(ObserveEvent) -> transport::Result<()> + Send + Sync>;

impl DirectObservation {
    pub fn new(generation: u64, cancel: Cancellation) -> Arc<Self> {
        Arc::new(Self {
            generation,
            cancel,
            control: ObservationControl::new(),
            retired: AtomicBool::new(false),
            pending: Mutex::new(Pending::default()),
        })
    }

    pub fn cancel(&self) {
        self.retired.store(true, Ordering::SeqCst);
        self.cancel.cancel();
        if let Ok(mut p) = self.pending.lock() {
            p.select.take();
            p.ack.take();
            if let Some((_, input)) = p.input.take() {
                input.invalidate();
            }
        }
    }

    pub fn input(&self, generation: u64) -> transport::Result<Arc<LiveInput>> {
        if generation != self.generation || self.cancel.is_cancelled() {
            return Err("input_stale");
        }
        self.pending
            .lock()
            .map_err(|_| "state_unavailable")?
            .input
            .as_ref()
            .filter(|(epoch, _)| *epoch == self.control.snapshot().epoch)
            .map(|(_, input)| input.clone())
            .ok_or("input_stale")
    }

    pub fn select(
        &self,
        generation: u64,
        epoch: u64,
        revision: u64,
        pane: String,
        terminal: String,
    ) -> transport::Result<()> {
        if generation != self.generation
            || self.cancel.is_cancelled()
            || self.control.snapshot().epoch != epoch
        {
            return Err("stale_selection");
        }
        let mut p = self.pending.lock().map_err(|_| "state_unavailable")?;
        if !p.select.as_ref().is_some_and(|(e, _)| *e == epoch) {
            return Err("stale_selection");
        }
        let target = p.dashboard.select(epoch, revision, pane, terminal)?;
        p.select
            .take()
            .unwrap()
            .1
            .send(target.clone())
            .map_err(|_| "cancelled")?;
        p.selected = Some(target);
        Ok(())
    }

    pub fn ack(&self, generation: u64, epoch: u64, seq: u64) -> transport::Result<()> {
        if generation != self.generation
            || self.cancel.is_cancelled()
            || self.control.snapshot().epoch != epoch
        {
            return Err("stale_ack");
        }
        let mut p = self.pending.lock().map_err(|_| "state_unavailable")?;
        if !p
            .ack
            .as_ref()
            .is_some_and(|(e, s, _)| *e == epoch && *s == seq)
        {
            return Err("stale_ack");
        }
        p.ack.take().unwrap().2.send(()).map_err(|_| "cancelled")
    }

    /// This is the production entry used by remote_observe, also executed by
    /// the isolated transport fixture tests. No reconnect or write replay.
    #[allow(clippy::too_many_arguments)]
    pub async fn run(
        self: Arc<Self>,
        config: RemoteConfig,
        device: Option<(String, Arc<dyn DeviceSigner>)>,
        audit: Arc<Audit>,
        progress: Arc<dyn Fn(&'static str) + Send + Sync>,
        emit: Emit,
        recovery: transport::recovery::SharedRecovery,
        dialer: &dyn transport::transport::Dialer,
    ) -> transport::Result<()> {
        struct Cleanup(Arc<DirectObservation>);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                self.0.cancel();
            }
        }
        let _cleanup = Cleanup(self.clone());
        // Authentication consumes its signer wrapper. Retain the exact device
        // signer until the owned SSH transport has fully settled.
        let _signer = device.as_ref().map(|(_, signer)| signer.clone());
        let generation = self.generation;
        let weak = Arc::downgrade(&self);
        let event = emit.clone();
        self.control
            .set_dashboard_listener(Arc::new(move |update| {
                let Some(this) = weak.upgrade().filter(|s| !s.cancel.is_cancelled()) else {
                    return;
                };
                let accepted = this.pending.lock().ok().is_some_and(|mut p| {
                    p.dashboard.update(this.control.snapshot().epoch, &update)
                });
                if accepted && event(ObserveEvent::DashboardWatch { generation, update }).is_err() {
                    this.cancel();
                }
            }))?;
        let selecting = self.clone();
        let event = emit.clone();
        let select = move |_: Vec<Pane>| {
            let this = selecting.clone();
            let event = event.clone();
            async move {
                let epoch = this.control.snapshot().epoch;
                let (tx, rx) = oneshot::channel();
                {
                    let mut p = this.pending.lock().map_err(|_| "state_unavailable")?;
                    if this.cancel.is_cancelled() {
                        return Err("cancelled");
                    }
                    p.selected = None;
                    p.select = Some((epoch, tx));
                }
                event(ObserveEvent::SelectionReady { generation, epoch })?;
                rx.await.map_err(|_| "cancelled")
            }
        };
        let framing = self.clone();
        let event = emit.clone();
        let frame = move |epoch: u64, frame: StreamFrame| {
            let this = framing.clone();
            let event = event.clone();
            async move {
                let (tx, rx) = oneshot::channel();
                let target = {
                    let mut p = this.pending.lock().map_err(|_| "state_unavailable")?;
                    if this.cancel.is_cancelled() || this.control.snapshot().epoch != epoch {
                        return Err("cancelled");
                    }
                    let target = p.selected.clone().ok_or("target_unavailable")?;
                    p.ack = Some((epoch, frame.seq, tx));
                    target
                };
                if frame.full {
                    event(ObserveEvent::TargetBound {
                        generation,
                        epoch,
                        pane_id: target.pane_id,
                        terminal_id: target.terminal_id,
                    })?;
                }
                event(ObserveEvent::Frame {
                    generation,
                    epoch,
                    frame,
                })?;
                rx.await.map_err(|_| "cancelled")
            }
        };
        let state_owner = Arc::downgrade(&self);
        let event = emit.clone();
        let ready_owner = Arc::downgrade(&self);
        let ready_event = emit.clone();
        let hooks = ControlledInputHooks {
            recovery,
            state: Arc::new(move |snapshot| {
                if let Some(this) = state_owner.upgrade() {
                    if event(ObserveEvent::Observation {
                        generation,
                        snapshot,
                    })
                    .is_err()
                    {
                        this.cancel();
                    }
                }
            }),
            ready: Arc::new(move |epoch, input| {
                let Some(this) = ready_owner.upgrade() else {
                    input.invalidate();
                    return;
                };
                let Ok(mut p) = this.pending.lock() else {
                    input.invalidate();
                    this.cancel.cancel();
                    return;
                };
                if this.cancel.is_cancelled() || this.control.snapshot().epoch != epoch {
                    input.invalidate();
                    return;
                }
                let unknown = input.unknown();
                let recovery_status = input.recovery_status();
                p.input = Some((epoch, input));
                drop(p);
                if ready_event(ObserveEvent::InputReady {
                    generation,
                    epoch,
                    unknown,
                    recovery_status,
                })
                .is_err()
                {
                    this.cancel();
                }
            }),
        };
        let stopping = self.clone();
        let stages = move |stage| {
            progress(stage);
            if emit(ObserveEvent::Stage { generation, stage }).is_err() {
                stopping.cancel();
            }
        };
        let result = transport::observe_interactive_controlled_target_with_dialer(
            config,
            device,
            self.cancel.clone(),
            audit,
            stages,
            select,
            frame,
            Some(hooks),
            self.control.clone(),
            dialer,
        )
        .await;
        // Watch teardown may race its terminal wait and report watch_ended.
        // An explicit owner cancellation is consistently cancellation to UI.
        if self.retired.load(Ordering::SeqCst) {
            Err("cancelled")
        } else {
            result
        }
    }
}
