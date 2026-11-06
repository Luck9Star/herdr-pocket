//! Fixed herdr 0.9.5 / protocol 22 session invalidation stream.
//! Wire source: stock 2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01.
//! The events/response/subscriptions blobs also match bc8c28988f75c538d4ca058b702f5adbea30566e,
//! src/api/{server.rs,subscriptions.rs,schema/events.rs,schema/response.rs}.
//! No event payload is applied to the dashboard and no input/PTY request exists here.
use crate::controlled::{close_channel, current, locked, snapshot};
use crate::*;
use tokio::sync::watch;

pub const REFRESH_COALESCE: Duration = Duration::from_millis(100);
pub const REFRESH_FALLBACK: Duration = Duration::from_secs(30);
const RETRY_DELAY: Duration = Duration::from_millis(500);
const EVENT_LIMIT: usize = 1_048_576;
const MAX_REVISION: u64 = 9_007_199_254_740_991;
const TYPES: &[&str] = &[
    "workspace.created",
    "workspace.updated",
    "workspace.metadata_updated",
    "workspace.renamed",
    "workspace.moved",
    "workspace.reordered",
    "workspace.closed",
    "workspace.focused",
    "tab.created",
    "tab.closed",
    "tab.focused",
    "tab.renamed",
    "tab.moved",
    "pane.created",
    "pane.closed",
    "pane.updated",
    "pane.focused",
    "pane.moved",
    "pane.exited",
    "pane.agent_detected",
    "layout.updated",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum SessionWatchPhase {
    Stale,
    Refreshing,
    Fresh,
    Unavailable,
}
#[derive(Clone, Debug, Serialize)]
pub struct SessionWatchUpdate {
    pub epoch: u64,
    pub revision: u64,
    pub phase: SessionWatchPhase,
    pub reason: &'static str,
    /// Only authoritative snapshot metadata; None preserves the last cache.
    pub panes: Option<Vec<Pane>>,
}

type Listener = Arc<dyn Fn(SessionWatchUpdate) + Send + Sync>;
type Target = Arc<Mutex<Option<(String, String)>>>;
#[derive(Clone)]
struct Latest {
    value: Option<Value>,
    selectable: bool,
}
#[derive(Clone, Copy)]
struct Signal {
    started: bool,
    live: bool,
    dirty: u64,
    reason: &'static str,
}
impl Default for Signal {
    fn default() -> Self {
        Self {
            started: false,
            live: false,
            dirty: 0,
            reason: "subscribing",
        }
    }
}

/// Connection-owned epoch task. Its caller always joins before reporting pause.
/// Drop cancels as a last resort; normal paths await stop to retire SSH channels.
pub(crate) struct EpochWatch {
    stop: Cancellation,
    task: Option<tokio::task::JoinHandle<Result<()>>>,
    latest: watch::Receiver<Latest>,
    control: ObservationControl,
    epoch: u64,
    pub(crate) target: Target,
}
impl Drop for EpochWatch {
    fn drop(&mut self) {
        self.stop.cancel();
    }
}
impl EpochWatch {
    pub(crate) fn start(
        ssh: Arc<client::Handle<Pinned>>,
        mut config: RemoteConfig,
        cancel: Cancellation,
        control: ObservationControl,
        epoch: u64,
        listener: Listener,
        target: Option<(String, String)>,
    ) -> Self {
        // Only the already authenticated transport and socket path are used.
        config.private_key_pem.zeroize();
        let stop = Cancellation::default();
        let target = Arc::new(Mutex::new(target));
        let (tx, latest) = watch::channel(Latest {
            value: None,
            selectable: false,
        });
        let publisher = Arc::new(Publisher {
            cancel: cancel.clone(),
            control: control.clone(),
            epoch,
            stop: stop.clone(),
            latest: tx,
            listener,
            publication: Mutex::new((0, SessionWatchPhase::Stale, "")),
        });
        let state = State {
            ssh,
            config,
            cancel,
            control: control.clone(),
            epoch,
            target: target.clone(),
            publisher,
            stop: stop.clone(),
        };
        Self {
            stop,
            task: Some(tokio::spawn(state.run())),
            latest,
            target,
            control,
            epoch,
        }
    }
    pub(crate) async fn first(&mut self) -> Result<Value> {
        loop {
            if let Some(value) = self.latest.borrow().value.clone() {
                return Ok(value);
            }
            let latest = &mut self.latest;
            let task = self.task.as_mut().ok_or("watch_ended")?;
            tokio::select! { biased;
                result = task => { self.task.take(); return if !current(&self.control,self.epoch) {Err("observation_paused")} else {result.map_err(|_|"watch_failed")?.and(Err("watch_ended"))}; }
                result = latest.changed() => { result.map_err(|_|"watch_ended")?; }
            }
        }
    }
    pub(crate) fn selected(&self, intent: &DashboardTarget) -> Result<Value> {
        let latest = self.latest.borrow();
        if !latest.selectable {
            return Err("dashboard_stale");
        }
        let value = latest.value.as_ref().ok_or("dashboard_stale")?;
        let terminal = snapshot_terminal(value, &intent.pane_id)?;
        if terminal != intent.terminal_id {
            return Err("resume_target_changed");
        }
        *locked(&self.target) = Some((intent.pane_id.clone(), terminal));
        Ok(value.clone())
    }
    pub(crate) async fn during<T>(&mut self, future: impl Future<Output = Result<T>>) -> Result<T> {
        let task = self.task.as_mut().ok_or("watch_ended")?;
        tokio::select! { biased;
            result = task => { self.task.take(); if !current(&self.control,self.epoch) {Err("observation_paused")} else {result.map_err(|_|"watch_failed")?.and(Err("watch_ended"))} }
            result = future => result,
        }
    }
    pub(crate) async fn stop(&mut self) -> Result<()> {
        self.stop.cancel();
        if let Some(task) = self.task.take() {
            task.await.map_err(|_| "watch_failed")?
        } else {
            Ok(())
        }
    }
}

struct Publisher {
    cancel: Cancellation,
    control: ObservationControl,
    epoch: u64,
    stop: Cancellation,
    latest: watch::Sender<Latest>,
    listener: Listener,
    publication: Mutex<(u64, SessionWatchPhase, &'static str)>,
}
impl Publisher {
    fn emit(
        &self,
        phase: SessionWatchPhase,
        reason: &'static str,
        value: Option<Value>,
        valid: impl FnOnce() -> bool,
    ) -> Result<bool> {
        let mut publication = locked(&self.publication);
        if self.cancel.is_cancelled()
            || self.stop.is_cancelled()
            || !current(&self.control, self.epoch)
            || !valid()
        {
            return Ok(false);
        }
        if value.is_none() && publication.1 == phase && publication.2 == reason {
            return Ok(true);
        }
        publication.0 = publication
            .0
            .checked_add(1)
            .filter(|n| *n <= MAX_REVISION)
            .ok_or("watch_limit")?;
        publication.1 = phase;
        publication.2 = reason;
        let has_snapshot = value.is_some();
        let panes = value.as_ref().map(snapshot_panes).transpose()?;
        self.latest.send_modify(|latest| {
            if let Some(value) = value {
                latest.value = Some(value);
            }
            latest.selectable = phase == SessionWatchPhase::Fresh
                || (phase == SessionWatchPhase::Unavailable && has_snapshot);
        });
        (self.listener)(SessionWatchUpdate {
            epoch: self.epoch,
            revision: publication.0,
            phase,
            reason,
            panes,
        });
        Ok(true)
    }
}

struct State {
    ssh: Arc<client::Handle<Pinned>>,
    config: RemoteConfig,
    cancel: Cancellation,
    control: ObservationControl,
    epoch: u64,
    target: Target,
    publisher: Arc<Publisher>,
    stop: Cancellation,
}
impl State {
    fn active(&self) -> bool {
        !self.cancel.is_cancelled()
            && !self.stop.is_cancelled()
            && current(&self.control, self.epoch)
    }
    fn publish(
        &self,
        phase: SessionWatchPhase,
        reason: &'static str,
        value: Option<Value>,
    ) -> Result<()> {
        self.publisher
            .emit(phase, reason, value, || true)
            .map(|_| ())
    }
    async fn delay(&self, duration: Duration) {
        tokio::select! { biased; _=self.cancel.wait()=>{},_=self.stop.wait()=>{},_=self.control.changed(self.epoch)=>{},_=tokio::time::sleep(duration)=>{} }
    }
    async fn run(mut self) -> Result<()> {
        let result = self.run_inner().await;
        if let Err(reason) = result {
            let _ = self.publish(SessionWatchPhase::Stale, reason, None);
        }
        result
    }
    async fn run_inner(&mut self) -> Result<()> {
        let mut ids = Vec::new();
        let mut failures = 0usize;
        self.publish(SessionWatchPhase::Stale, "starting", None)?;
        while self.active() {
            let mut subscription = Subscription::start(
                self.ssh.clone(),
                self.config.socket_path.clone(),
                self.cancel.clone(),
                self.control.clone(),
                self.epoch,
                ids.clone(),
                self.publisher.clone(),
            );
            let outcome = self.reconcile(&mut subscription, &mut ids).await;
            // Retirement is awaited before a replacement subscription or pause ACK.
            let retired = subscription.stop().await;
            if !self.active() {
                return retired;
            }
            retired?;
            match outcome {
                Ok(Reconcile::Membership) => {
                    failures = 0;
                }
                Ok(Reconcile::Stopped) => return Ok(()),
                Err("watch_unsupported") => {
                    self.publish(SessionWatchPhase::Unavailable, "watch_unsupported", None)?;
                    // A missing event method disables watching, not SSH/observe.
                    if let Some(value) = snapshot(
                        &self.ssh,
                        &self.config,
                        &self.cancel,
                        &self.control,
                        self.epoch,
                    )
                    .await?
                    {
                        self.check_target(&value)?;
                        self.publish(
                            SessionWatchPhase::Unavailable,
                            "watch_unsupported",
                            Some(value),
                        )?;
                    }
                    while self.active() {
                        self.delay(REFRESH_FALLBACK).await;
                    }
                    return Ok(());
                }
                Err("resume_target_changed") => return Err("resume_target_changed"),
                Err(reason) => {
                    self.publish(SessionWatchPhase::Stale, reason, None)?;
                    ids.clear();
                    failures = failures.saturating_add(1);
                    // At most one subscription plus one snapshot; retry rate is bounded.
                    self.delay(RETRY_DELAY * failures.min(4) as u32).await;
                }
            }
        }
        Ok(())
    }
    fn check_target(&self, value: &Value) -> Result<()> {
        if let Some((pane, terminal)) = &*locked(&self.target)
            && snapshot_terminal(value, pane).ok().as_ref() != Some(terminal)
        {
            return Err("resume_target_changed");
        }
        Ok(())
    }
    async fn reconcile(
        &mut self,
        sub: &mut Subscription,
        ids: &mut Vec<String>,
    ) -> Result<Reconcile> {
        loop {
            if !self.active() {
                return Ok(Reconcile::Stopped);
            }
            let signal = *sub.signal.borrow();
            if signal.started {
                break;
            }
            if signal.reason != "subscribing" {
                return Err(signal.reason);
            }
            tokio::select! { biased; _=self.cancel.wait()=>return Ok(Reconcile::Stopped),_=self.stop.wait()=>return Ok(Reconcile::Stopped),_=self.control.changed(self.epoch)=>return Ok(Reconcile::Stopped),v=sub.signal.changed()=>{v.map_err(|_|"watch_ended")?;} }
        }
        loop {
            if !self.active() {
                return Ok(Reconcile::Stopped);
            }
            let before = *sub.signal.borrow_and_update();
            if !before.live {
                return Err(before.reason);
            }
            self.publish(SessionWatchPhase::Refreshing, "refreshing", None)?;
            let result = snapshot(
                &self.ssh,
                &self.config,
                &self.cancel,
                &self.control,
                self.epoch,
            )
            .await;
            let Some(value) = result? else {
                return Ok(Reconcile::Stopped);
            };
            if !self.active() {
                return Ok(Reconcile::Stopped);
            }
            let panes = snapshot_panes(&value)?;
            self.check_target(&value)?;
            let after = *sub.signal.borrow();
            if !after.live {
                return Err(after.reason);
            }
            let mut actual: Vec<_> = panes.iter().map(|p| p.pane_id.clone()).collect();
            actual.sort();
            if actual != *ids {
                self.publish(SessionWatchPhase::Stale, "membership_changed", None)?;
                *ids = actual;
                return Ok(Reconcile::Membership);
            }
            if before.dirty != after.dirty {
                self.publish(SessionWatchPhase::Stale, "changed_during_refresh", None)?;
                self.delay(REFRESH_COALESCE).await;
                continue;
            }
            if !self
                .publisher
                .emit(SessionWatchPhase::Fresh, "snapshot", Some(value), || {
                    let current = *sub.signal.borrow();
                    current.live && current.dirty == before.dirty
                })?
            {
                self.delay(REFRESH_COALESCE).await;
                continue;
            }
            // No queue of event bodies, only the last dirty counter. A single
            // non-sliding coalescing window bounds refreshes during event storms.
            tokio::select! { biased;
                _=self.cancel.wait()=>return Ok(Reconcile::Stopped),
                _=self.stop.wait()=>return Ok(Reconcile::Stopped),
                _=self.control.changed(self.epoch)=>return Ok(Reconcile::Stopped),
                v=sub.signal.changed()=>{v.map_err(|_|"watch_ended")?;},
                _=tokio::time::sleep(REFRESH_FALLBACK)=>{},
            }
            let signal = *sub.signal.borrow();
            self.publish(
                SessionWatchPhase::Stale,
                if signal.live {
                    "invalidated"
                } else {
                    signal.reason
                },
                None,
            )?;
            if !signal.live {
                return Err(signal.reason);
            }
            self.delay(REFRESH_COALESCE).await;
        }
    }
}
enum Reconcile {
    Membership,
    Stopped,
}

fn request(id: &str, panes: &[String]) -> Vec<u8> {
    let subscriptions: Vec<_> = TYPES
        .iter()
        .map(|name| serde_json::json!({"type":name}))
        .chain(
            panes
                .iter()
                .map(|pane| serde_json::json!({"type":"pane.agent_status_changed","pane_id":pane})),
        )
        .collect();
    let mut wire=serde_json::to_vec(&serde_json::json!({"id":id,"method":"events.subscribe","params":{"subscriptions":subscriptions}})).unwrap();
    wire.push(b'\n');
    wire
}
fn line(raw: &[u8], id: &str, panes: &[String], started: bool) -> Result<()> {
    let value: Value = serde_json::from_slice(raw).map_err(|_| "watch_invalid")?;
    if value.get("id").is_some() {
        if value["id"].as_str() != Some(id) {
            return Err("watch_invalid");
        }
        if value.get("error").is_some() {
            return Err(match value["error"]["code"].as_str() {
                Some("events_lost") => "events_lost",
                Some("unknown_method" | "method_not_found" | "invalid_method") => "watch_unsupported",
                Some("invalid_request") if panes.is_empty() => "watch_unsupported",
                _ => "watch_rejected",
            });
        }
        return if !started && value["result"]["type"] == "subscription_started" {
            Ok(())
        } else {
            Err("watch_invalid")
        };
    }
    if !started || !value["data"].is_object() {
        return Err("watch_invalid");
    }
    let event = value["event"].as_str().ok_or("watch_invalid")?;
    if TYPES.iter().any(|kind| kind.replace('.', "_") == event) {
        return Ok(());
    }
    if event == "pane.agent_status_changed"
        && panes
            .iter()
            .any(|p| value["data"]["pane_id"].as_str() == Some(p))
    {
        return Ok(());
    }
    Err("watch_invalid")
}
struct Subscription {
    stop: Cancellation,
    task: tokio::task::JoinHandle<Result<()>>,
    signal: watch::Receiver<Signal>,
}
impl Subscription {
    fn start(
        ssh: Arc<client::Handle<Pinned>>,
        socket: String,
        cancel: Cancellation,
        control: ObservationControl,
        epoch: u64,
        panes: Vec<String>,
        publisher: Arc<Publisher>,
    ) -> Self {
        let stop = Cancellation::default();
        let task_stop = stop.clone();
        let (tx, signal) = watch::channel(Signal::default());
        let task = tokio::spawn(async move {
            let result = pump(
                &ssh, &socket, &cancel, &control, epoch, &task_stop, &panes, &tx, &publisher,
            )
            .await;
            tx.send_modify(|s| {
                s.live = false;
                s.reason = result.as_ref().err().copied().unwrap_or("watch_stopped");
            });
            result
        });
        Self { stop, task, signal }
    }
    async fn stop(self) -> Result<()> {
        self.stop.cancel();
        match self.task.await.map_err(|_| "watch_failed")? {
            // Protocol/loss errors were already published. Channel cleanup errors
            // cancel the owning connection inside close_channel.
            Err("observe_close_failed" | "observe_ended" | "observe_limit" | "timeout") => {
                Err("watch_close_failed")
            }
            _ => Ok(()),
        }
    }
}
#[allow(clippy::too_many_arguments)]
async fn pump(
    ssh: &client::Handle<Pinned>,
    socket: &str,
    cancel: &Cancellation,
    control: &ObservationControl,
    epoch: u64,
    stop: &Cancellation,
    panes: &[String],
    signal: &watch::Sender<Signal>,
    publisher: &Publisher,
) -> Result<()> {
    let id = input::random_id().ok_or("watch_failed")?;
    let opened = bounded(
        cancel,
        8,
        "watch_open_failed",
        ssh.channel_open_direct_streamlocal(socket),
    )
    .await;
    let mut channel = match opened {
        Ok(channel) => channel,
        Err(reason) => {
            // A late confirmation cannot be retired without its channel ID.
            // Close this SSH instead of accumulating unresolved opens on retry.
            cancel.cancel();
            return Err(reason);
        }
    };
    let result=async {
        if stop.is_cancelled() || !current(control,epoch) {return Ok(());}
        bounded(cancel,8,"watch_write_failed",channel.data_bytes(request(&id,panes))).await?;
        let deadline=Instant::now()+Duration::from_secs(8);
        let mut pending=Vec::new(); let mut started=false;
        loop {
            let message=tokio::select! {biased;
                _=cancel.wait()=>return Ok(()),_=stop.wait()=>return Ok(()),_=control.changed(epoch)=>return Ok(()),
                msg=async {if started {Ok(channel.wait().await)} else {before_first_frame(cancel,deadline,channel.wait()).await}}=>msg?,
            };
            match message {
                Some(ChannelMsg::Data{data})=>for byte in data.iter() {
                    pending.push(*byte); if pending.len()>EVENT_LIMIT {return Err("watch_limit");}
                    if *byte==b'\n' {
                        line(&pending,&id,panes,started)?; pending.clear();
                        signal.send_modify(|s| {if !started {s.started=true;s.live=true;s.reason="subscribed";} else if s.dirty<MAX_REVISION {s.dirty+=1;} else {s.live=false;s.reason="watch_limit";}});
                        if started {publisher.emit(SessionWatchPhase::Stale,"invalidated",None,||true)?;}
                        started=true;
                        if !signal.borrow().live {return Err("watch_limit");}
                    }
                },
                Some(ChannelMsg::Eof|ChannelMsg::Close|ChannelMsg::Failure)|None=>return Err("watch_disconnected"),
                Some(ChannelMsg::ExtendedData{..})=>return Err("watch_invalid"),
                _=>{},
            }
        }
    }.await;
    // Publish loss immediately, before a slow peer's channel retirement finishes.
    if let Err(reason) = result {
        signal.send_modify(|s| {
            s.live = false;
            s.reason = reason;
        });
        let _ = publisher.emit(SessionWatchPhase::Stale, reason, None, || true);
    }
    close_channel(ssh, cancel, &mut channel).await?;
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixed_release_fixture_request_and_wire_names_match() {
        let fixture: Value =
            serde_json::from_str(include_str!("../../shared/session-watch-v1.json")).unwrap();
        let global: Vec<_> = fixture["globalSubscriptions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert_eq!(global, TYPES);
        let id = fixture["wire"]["request"]["id"].as_str().unwrap();
        let wire: Value = serde_json::from_slice(&request(id, &[])).unwrap();
        assert_eq!(wire, fixture["wire"]["request"]);
        assert!(
            line(
                &serde_json::to_vec(&fixture["wire"]["ack"]).unwrap(),
                id,
                &[],
                false
            )
            .is_ok()
        );
        for key in ["created", "closed", "exited"] {
            assert!(
                line(
                    &serde_json::to_vec(&fixture["wire"][key]).unwrap(),
                    id,
                    &[],
                    true
                )
                .is_ok()
            );
        }
        let status = serde_json::to_vec(&fixture["wire"]["status"]).unwrap();
        assert!(line(&status, id, &["w1:p1".into()], true).is_ok());
        assert_eq!(line(&status, id, &[], true), Err("watch_invalid"));
        assert_eq!(
            line(
                &serde_json::to_vec(&fixture["wire"]["lost"]).unwrap(),
                id,
                &[],
                true
            ),
            Err("events_lost")
        );
    }
    #[test]
    fn uncorrelated_ack_early_event_and_unknown_type_are_rejected() {
        assert_eq!(
            line(
                br#"{"id":"other","result":{"type":"subscription_started"}}"#,
                "ours",
                &[],
                false
            ),
            Err("watch_invalid")
        );
        assert_eq!(
            line(br#"{"event":"pane_created","data":{}}"#, "ours", &[], false),
            Err("watch_invalid")
        );
        assert_eq!(
            line(br#"{"event":"pane.created","data":{}}"#, "ours", &[], true),
            Err("watch_invalid")
        );
        assert_eq!(
            line(
                br#"{"id":"ours","error":{"code":"invalid_request"}}"#,
                "ours",
                &[],
                false
            ),
            Err("watch_unsupported")
        );
        // A pane can disappear between the snapshot and its scoped request.
        // This rejection must rebuild membership instead of disabling watch.
        assert_eq!(
            line(
                br#"{"id":"ours","error":{"code":"invalid_request"}}"#,
                "ours",
                &["w1:p1".into()],
                false
            ),
            Err("watch_rejected")
        );
    }
}
