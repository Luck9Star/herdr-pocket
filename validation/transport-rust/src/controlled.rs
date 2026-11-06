//! One authenticated SSH connection, with explicit, bounded observation epochs.
use super::*;
use std::sync::atomic::AtomicUsize;
use std::{sync::Weak, time::Instant as StdInstant};
use tokio::sync::oneshot;

#[derive(Default)]
struct OwnedIo {
    count: AtomicUsize,
    changed: Notify,
}
struct IoReservation(Arc<OwnedIo>);
impl OwnedIo {
    fn reserve(self: &Arc<Self>) -> IoReservation {
        self.count.fetch_add(1, Ordering::SeqCst);
        IoReservation(self.clone())
    }
    async fn settled(&self) {
        loop {
            let wake = self.changed.notified();
            tokio::pin!(wake);
            wake.as_mut().enable();
            if self.count.load(Ordering::SeqCst) == 0 {
                return;
            }
            wake.await;
        }
    }
}
impl Drop for IoReservation {
    fn drop(&mut self) {
        self.0.count.fetch_sub(1, Ordering::SeqCst);
        self.0.changed.notify_waiters();
    }
}
struct OwnedDialer<'a> {
    inner: &'a dyn transport::Dialer,
    io: Arc<OwnedIo>,
}
impl transport::Dialer for OwnedDialer<'_> {
    fn dial(&self, host: String, port: u16, cancel: Cancellation) -> transport::DialFuture<'_> {
        let pending = self.io.reserve();
        Box::pin(async move {
            let result = self.inner.dial(host, port, cancel).await.map(|stream| {
                Box::new(OwnedStream {
                    inner: Some(stream),
                    _reservation: self.io.reserve(),
                }) as Box<dyn transport::ByteStream>
            });
            drop(pending);
            result
        })
    }
}
struct OwnedStream {
    inner: Option<Box<dyn transport::ByteStream>>,
    _reservation: IoReservation,
}
impl Drop for OwnedStream {
    fn drop(&mut self) {
        if let Some(mut stream) = self.inner.take() {
            stream.abort();
            drop(stream);
        }
    }
}
impl transport::ByteStream for OwnedStream {
    fn abort(&mut self) {
        if let Some(stream) = &mut self.inner {
            stream.abort();
        }
    }
    fn route_identity(&self) -> Option<transport::OverlayRouteIdentity> {
        self.inner
            .as_ref()
            .and_then(|stream| stream.route_identity())
    }
}
impl AsyncRead for OwnedStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut **self.get_mut().inner.as_mut().unwrap()).poll_read(cx, buf)
    }
}
impl AsyncWrite for OwnedStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut **self.get_mut().inner.as_mut().unwrap()).poll_write(cx, buf)
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut **self.get_mut().inner.as_mut().unwrap()).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut **self.get_mut().inner.as_mut().unwrap()).poll_shutdown(cx)
    }
}

const CONTROL_WAIT: Duration = Duration::from_secs(10);
const CLOSE_WAIT: Duration = Duration::from_secs(5);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ObservationPhase {
    Starting,
    Active,
    Pausing,
    Paused,
    Resuming,
    Closed,
}

#[cfg(all(test, unix))]
mod tests;
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct ObservationSnapshot {
    pub epoch: u64,
    pub phase: ObservationPhase,
}
pub struct ControlledInputHooks {
    pub recovery: recovery::SharedRecovery,
    pub ready: Arc<dyn Fn(u64, Arc<input::LiveInput>) + Send + Sync>,
    pub state: Arc<dyn Fn(ObservationSnapshot) + Send + Sync>,
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Pause,
    Resume,
}
struct Pending {
    epoch: u64,
    ack: oneshot::Sender<Result<ObservationSnapshot>>,
}
struct Gate {
    snapshot: ObservationSnapshot,
    pending: Option<Pending>,
    attached: bool,
    connection: Option<Cancellation>,
    lease_cancel: Cancellation,
    input: Option<Arc<input::LiveInput>>,
    listener: Option<Arc<dyn Fn(ObservationSnapshot) + Send + Sync>>,
}
struct ControlInner {
    gate: Mutex<Gate>,
    changed: Notify,
}
#[derive(Clone)]
pub struct ObservationControl {
    inner: Arc<ControlInner>,
}
fn locked<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|p| p.into_inner())
}
impl Default for ObservationControl {
    fn default() -> Self {
        Self::new()
    }
}
impl ObservationControl {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(ControlInner {
                gate: Mutex::new(Gate {
                    snapshot: ObservationSnapshot {
                        epoch: 1,
                        phase: ObservationPhase::Starting,
                    },
                    pending: None,
                    attached: false,
                    connection: None,
                    lease_cancel: Cancellation::default(),
                    input: None,
                    listener: None,
                }),
                changed: Notify::new(),
            }),
        }
    }
    pub fn snapshot(&self) -> ObservationSnapshot {
        locked(&self.inner.gate).snapshot
    }
    pub fn pause(&self) -> Result<ObservationAck> {
        self.command(Kind::Pause)
    }
    pub fn resume(&self) -> Result<ObservationAck> {
        self.command(Kind::Resume)
    }
    fn command(&self, kind: Kind) -> Result<ObservationAck> {
        let (tx, rx) = oneshot::channel();
        let (epoch, listener, snapshot) = {
            let mut gate = locked(&self.inner.gate);
            if gate.snapshot.phase == ObservationPhase::Closed {
                return Err("control_closed");
            }
            if kind == Kind::Pause && gate.snapshot.phase == ObservationPhase::Paused {
                let _ = tx.send(Ok(gate.snapshot));
                return Ok(ObservationAck::new(self, gate.snapshot.epoch, rx));
            }
            if kind == Kind::Resume && gate.snapshot.phase != ObservationPhase::Paused {
                return Err("control_not_paused");
            }
            if gate.pending.is_some() {
                if kind == Kind::Pause && gate.snapshot.phase == ObservationPhase::Resuming {
                    if let Some(old) = gate.pending.take() {
                        let _ = old.ack.send(Err("control_superseded"));
                    }
                } else {
                    return Err("control_busy");
                }
            }
            gate.snapshot.epoch = gate.snapshot.epoch.checked_add(1).ok_or("control_closed")?;
            if let Some(input) = gate.input.take() {
                input.retire_for_pause();
            }
            gate.lease_cancel.cancel();
            gate.lease_cancel = Cancellation::default();
            gate.snapshot.phase = if kind == Kind::Pause {
                ObservationPhase::Pausing
            } else {
                ObservationPhase::Resuming
            };
            let epoch = gate.snapshot.epoch;
            gate.pending = Some(Pending { epoch, ack: tx });
            (epoch, gate.listener.clone(), gate.snapshot)
        };
        self.inner.changed.notify_waiters();
        if let Some(listener) = listener {
            listener(snapshot);
        }
        Ok(ObservationAck::new(self, epoch, rx))
    }
    fn attach(
        &self,
        cancel: Cancellation,
        listener: Option<Arc<dyn Fn(ObservationSnapshot) + Send + Sync>>,
    ) -> Result<()> {
        let snapshot = {
            let mut gate = locked(&self.inner.gate);
            if gate.attached || gate.snapshot.phase == ObservationPhase::Closed {
                return Err("control_in_use");
            }
            gate.attached = true;
            gate.connection = Some(cancel);
            gate.listener = listener.clone();
            gate.snapshot
        };
        if let Some(listener) = listener {
            listener(snapshot);
        }
        Ok(())
    }
    fn finish(
        &self,
        epoch: u64,
        phase: ObservationPhase,
        input: Option<Arc<input::LiveInput>>,
    ) -> bool {
        let (listener, snapshot, ack) = {
            let mut gate = locked(&self.inner.gate);
            if gate.snapshot.epoch != epoch || gate.snapshot.phase == ObservationPhase::Closed {
                if let Some(input) = input {
                    input.retire_for_pause();
                }
                return false;
            }
            gate.snapshot.phase = phase;
            gate.input = input;
            let ack = if gate
                .pending
                .as_ref()
                .is_some_and(|pending| pending.epoch == epoch)
            {
                gate.pending.take().map(|p| p.ack)
            } else {
                None
            };
            (gate.listener.clone(), gate.snapshot, ack)
        };
        if let Some(listener) = listener {
            listener(snapshot);
        }
        if let Some(ack) = ack {
            let _ = ack.send(Ok(snapshot));
        }
        true
    }
    fn close(&self) {
        self.close_if(None);
    }
    fn close_if(&self, expected: Option<u64>) {
        let (listener, snapshot, cancel) = {
            let mut gate = locked(&self.inner.gate);
            if expected.is_some_and(|epoch| {
                gate.pending
                    .as_ref()
                    .is_none_or(|pending| pending.epoch != epoch)
            }) {
                return;
            }
            if gate.snapshot.phase == ObservationPhase::Closed {
                return;
            }
            if let Some(input) = gate.input.take() {
                input.invalidate();
            }
            gate.lease_cancel.cancel();
            gate.snapshot.phase = ObservationPhase::Closed;
            if let Some(pending) = gate.pending.take() {
                let _ = pending.ack.send(Err("control_closed"));
            }
            (gate.listener.take(), gate.snapshot, gate.connection.clone())
        };
        if let Some(cancel) = cancel {
            cancel.cancel();
        }
        self.inner.changed.notify_waiters();
        if let Some(listener) = listener {
            listener(snapshot);
        }
    }
    fn abandon(&self, epoch: u64) {
        self.close_if(Some(epoch));
    }
    fn lease_cancel(&self, epoch: u64) -> Result<Cancellation> {
        let gate = locked(&self.inner.gate);
        if gate.snapshot.epoch != epoch {
            Err("control_superseded")
        } else {
            Ok(gate.lease_cancel.clone())
        }
    }
    async fn changed(&self, epoch: u64) {
        loop {
            let notification = self.inner.changed.notified();
            tokio::pin!(notification);
            notification.as_mut().enable();
            if self.snapshot().epoch != epoch || self.snapshot().phase == ObservationPhase::Closed {
                return;
            }
            notification.await;
        }
    }
}
pub struct ObservationAck {
    control: Weak<ControlInner>,
    epoch: u64,
    rx: oneshot::Receiver<Result<ObservationSnapshot>>,
    deadline: StdInstant,
    timer: Option<Pin<Box<tokio::time::Sleep>>>,
    settled: bool,
}
impl ObservationAck {
    fn new(
        control: &ObservationControl,
        epoch: u64,
        rx: oneshot::Receiver<Result<ObservationSnapshot>>,
    ) -> Self {
        Self {
            control: Arc::downgrade(&control.inner),
            epoch,
            rx,
            deadline: StdInstant::now() + CONTROL_WAIT,
            timer: None,
            settled: false,
        }
    }
}
impl Future for ObservationAck {
    type Output = Result<ObservationSnapshot>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        if this.settled {
            return Poll::Ready(Err("control_closed"));
        }
        if let Poll::Ready(value) = Pin::new(&mut this.rx).poll(cx) {
            this.settled = true;
            return Poll::Ready(value.unwrap_or(Err("control_closed")));
        }
        let timer = this.timer.get_or_insert_with(|| {
            Box::pin(tokio::time::sleep_until(Instant::from_std(this.deadline)))
        });
        if timer.as_mut().poll(cx).is_ready() {
            this.settled = true;
            if let Some(inner) = this.control.upgrade() {
                ObservationControl { inner }.abandon(this.epoch);
            }
            return Poll::Ready(Err("control_timeout"));
        }
        Poll::Pending
    }
}
impl Drop for ObservationAck {
    fn drop(&mut self) {
        if !self.settled
            && let Some(inner) = self.control.upgrade()
        {
            ObservationControl { inner }.abandon(self.epoch);
        }
    }
}
struct Guard(ObservationControl);
impl Drop for Guard {
    fn drop(&mut self) {
        self.0.close();
    }
}

/// Reuses one authenticated SSH transport. Every resumed observer revalidates
/// its immutable target and confirms a fresh full frame before input readiness.
#[allow(clippy::too_many_arguments)]
pub async fn observe_interactive_controlled_with_dialer<Select, SelectFuture, Frame, FrameFuture>(
    config: RemoteConfig,
    device: Option<(String, Arc<dyn DeviceSigner>)>,
    cancel: Cancellation,
    audit: Arc<Audit>,
    progress: impl Fn(&'static str) + Send + Sync,
    select: Select,
    frame: Frame,
    hooks: Option<ControlledInputHooks>,
    control: ObservationControl,
    dialer: &dyn transport::Dialer,
) -> Result<()>
where
    Select: Fn(Vec<Pane>) -> SelectFuture,
    SelectFuture: Future<Output = Result<String>>,
    Frame: Fn(u64, StreamFrame) -> FrameFuture,
    FrameFuture: Future<Output = Result<()>>,
{
    control.attach(cancel.clone(), hooks.as_ref().map(|h| h.state.clone()))?;
    let _guard = Guard(control.clone());
    let _cancel = CancelOnDrop(cancel.clone());
    let io = Arc::new(OwnedIo::default());
    let owned = OwnedDialer {
        inner: dialer,
        io: io.clone(),
    };
    let result = run_controlled(
        config,
        device,
        cancel.clone(),
        audit,
        progress,
        select,
        frame,
        hooks,
        control,
        &owned,
    )
    .await;
    cancel.cancel();
    // Keep the frontend's closing slot until owned dial futures and the
    // actual SSH driver's I/O have dropped. Native reservations are separate.
    io.settled().await;
    result
}

#[allow(clippy::too_many_arguments)]
async fn run_controlled<Select, SelectFuture, Frame, FrameFuture>(
    config: RemoteConfig,
    device: Option<(String, Arc<dyn DeviceSigner>)>,
    cancel: Cancellation,
    audit: Arc<Audit>,
    progress: impl Fn(&'static str) + Send + Sync,
    select: Select,
    frame: Frame,
    hooks: Option<ControlledInputHooks>,
    control: ObservationControl,
    dialer: &dyn transport::Dialer,
) -> Result<()>
where
    Select: Fn(Vec<Pane>) -> SelectFuture,
    SelectFuture: Future<Output = Result<String>>,
    Frame: Fn(u64, StreamFrame) -> FrameFuture,
    FrameFuture: Future<Output = Result<()>>,
{
    let external = if let Some((public_key, signer)) = device {
        let key = PublicKey::from_openssh(&public_key).map_err(|_| "invalid_device_key")?;
        if key.algorithm() != Algorithm::Ed25519
            || key.to_openssh().map_err(|_| "invalid_device_key")? != public_key
        {
            return Err("invalid_device_key");
        }
        Some(ExternalSigner { key, signer })
    } else {
        None
    };
    let (ssh, route) =
        authenticate_observer(&config, &cancel, audit.clone(), &progress, external, dialer).await?;
    let mut target: Option<(String, String)> = None;
    loop {
        if cancel.is_cancelled() {
            return Err("cancelled");
        }
        let state = control.snapshot();
        match state.phase {
            ObservationPhase::Closed => return Err("cancelled"),
            ObservationPhase::Pausing => {
                control.finish(state.epoch, ObservationPhase::Paused, None);
                continue;
            }
            ObservationPhase::Paused => {
                tokio::select! {biased;_=cancel.wait()=>return Err("cancelled"),_=control.changed(state.epoch)=>{}}
                continue;
            }
            _ => {}
        }
        let Some(value) = snapshot(&ssh, &config, &cancel, &control, state.epoch).await? else {
            continue;
        };
        audit.snapshot_received.store(true, Ordering::SeqCst);
        progress("snapshot-received");
        if let Some((pane, terminal)) = &target {
            if snapshot_terminal(&value, pane)? != *terminal {
                return Err("resume_target_changed");
            }
        } else {
            let panes = snapshot_panes(&value)?;
            let selected = tokio::select! {biased;_=cancel.wait()=>return Err("cancelled"),_=control.changed(state.epoch)=>continue,result=select(panes)=>result?};
            target = Some((selected.clone(), snapshot_terminal(&value, &selected)?));
        }
        let (pane, terminal) = target.as_ref().unwrap();
        let supported = if hooks.is_some() {
            let Some(supported) =
                capabilities(&ssh, &config, &cancel, &control, state.epoch).await?
            else {
                continue;
            };
            supported
        } else {
            false
        };
        if !current(&control, state.epoch) {
            continue;
        }
        if hooks.is_some() && !supported {
            progress("input-unavailable");
        }
        let mut channel = bounded(&cancel, 8, "observe_failed", ssh.channel_open_session()).await?;
        let observing = observe_epoch(
            &ssh,
            &config,
            &cancel,
            &audit,
            &control,
            state.epoch,
            &mut channel,
            pane,
            terminal,
            route.clone(),
            supported,
            hooks.as_ref(),
            &frame,
        )
        .await;
        match observing {
            Ok(()) => {
                close_channel(&ssh, &cancel, &mut channel).await?;
            }
            Err(code) => return Err(code),
        }
    }
}
fn current(control: &ObservationControl, epoch: u64) -> bool {
    control.snapshot().epoch == epoch && control.snapshot().phase != ObservationPhase::Closed
}

async fn close_channel(
    ssh: &client::Handle<Pinned>,
    cancel: &Cancellation,
    channel: &mut russh::Channel<client::Msg>,
) -> Result<()> {
    let result = retire_channel(ssh, cancel, channel).await;
    if result.is_err() {
        cancel.cancel();
    }
    result
}
async fn retire_channel(
    ssh: &client::Handle<Pinned>,
    cancel: &Cancellation,
    channel: &mut russh::Channel<client::Msg>,
) -> Result<()> {
    let until = Instant::now() + CLOSE_WAIT;
    before_first_frame(cancel, until, channel.close())
        .await?
        .map_err(|_| "observe_close_failed")?;
    let mut discarded = 0usize;
    loop {
        match before_first_frame(cancel, until, channel.wait()).await? {
            Some(ChannelMsg::Close) | None => {
                if ssh.is_closed() {
                    return Err("observe_ended");
                }
                return Ok(());
            }
            Some(ChannelMsg::Data { data }) | Some(ChannelMsg::ExtendedData { data, .. }) => {
                discarded = discarded.checked_add(data.len()).ok_or("observe_limit")?;
                if discarded > TOTAL_LIMIT {
                    return Err("observe_limit");
                }
            }
            _ => {} // EOF alone is not local sender-index retirement.
        }
    }
}
async fn snapshot(
    ssh: &client::Handle<Pinned>,
    config: &RemoteConfig,
    cancel: &Cancellation,
    control: &ObservationControl,
    epoch: u64,
) -> Result<Option<Value>> {
    let bytes = rpc_closed(
        ssh,
        &config.socket_path,
        cancel,
        control,
        epoch,
        b"{\"id\":\"pocket-readonly\",\"method\":\"session.snapshot\",\"params\":{}}\n",
        LINE_LIMIT,
    )
    .await?;
    bytes
        .map(|bytes| serde_json::from_slice(&bytes).map_err(|_| "invalid_snapshot"))
        .transpose()
}
async fn capabilities(
    ssh: &client::Handle<Pinned>,
    config: &RemoteConfig,
    cancel: &Cancellation,
    control: &ObservationControl,
    epoch: u64,
) -> Result<Option<bool>> {
    let id = input::random_id().ok_or("input_storage_unavailable")?;
    let mut wire = serde_json::to_vec(
        &serde_json::json!({"id":id,"method":"pocket.input.capabilities","params":{}}),
    )
    .map_err(|_| "input_unavailable")?;
    wire.push(b'\n');
    Ok(rpc_closed(
        ssh,
        &config.socket_path,
        cancel,
        control,
        epoch,
        &wire,
        8192,
    )
    .await?
    .map(|bytes| input::capability_reply(&bytes, &id)))
}
#[allow(clippy::too_many_arguments)]
async fn rpc_closed(
    ssh: &client::Handle<Pinned>,
    socket: &str,
    cancel: &Cancellation,
    control: &ObservationControl,
    epoch: u64,
    wire: &[u8],
    limit: usize,
) -> Result<Option<Vec<u8>>> {
    let mut channel = bounded(
        cancel,
        8,
        "socket_unavailable",
        ssh.channel_open_direct_streamlocal(socket),
    )
    .await?;
    let read = async {
        bounded(
            cancel,
            8,
            "snapshot_failed",
            channel.data_bytes(wire.to_vec()),
        )
        .await?;
        let mut bytes = Vec::new();
        loop {
            match channel.wait().await {
                Some(ChannelMsg::Data { data }) => {
                    for byte in data.iter() {
                        bytes.push(*byte);
                        if bytes.len() > limit {
                            return Err("snapshot_limit");
                        }
                        if *byte == b'\n' {
                            return Ok(bytes);
                        }
                    }
                }
                Some(ChannelMsg::Eof | ChannelMsg::Close | ChannelMsg::Failure) | None => {
                    return Err("snapshot_failed");
                }
                Some(ChannelMsg::ExtendedData { .. }) => return Err("invalid_snapshot"),
                _ => {}
            }
        }
    };
    let value = tokio::select! {biased;_=cancel.wait()=>return Err("cancelled"),_=control.changed(epoch)=>None,result=timeout(Duration::from_secs(8),read)=>Some(result.map_err(|_|"timeout")??)};
    close_channel(ssh, cancel, &mut channel).await?;
    Ok(value)
}

#[allow(clippy::too_many_arguments)]
async fn observe_epoch<Frame, FrameFuture>(
    ssh: &Arc<client::Handle<Pinned>>,
    config: &RemoteConfig,
    cancel: &Cancellation,
    audit: &Audit,
    control: &ObservationControl,
    epoch: u64,
    channel: &mut russh::Channel<client::Msg>,
    pane: &str,
    terminal: &str,
    route: Option<transport::OverlayRouteIdentity>,
    supported: bool,
    hooks: Option<&ControlledInputHooks>,
    frame: &Frame,
) -> Result<()>
where
    Frame: Fn(u64, StreamFrame) -> FrameFuture,
    FrameFuture: Future<Output = Result<()>>,
{
    if !current(control, epoch) {
        return Ok(());
    }
    tokio::select! {biased;_=cancel.wait()=>return Err("cancelled"),_=control.changed(epoch)=>return Ok(()),value=bounded(cancel,8,"observe_failed",channel.exec(true,observe_command(config,terminal)?))=>{value?;}}
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut bytes = Vec::new();
    let mut sequence = None;
    let mut stderr = 0usize;
    let mut ready = false;
    loop {
        let msg = tokio::select! {biased;_=cancel.wait()=>return Err("cancelled"),_=control.changed(epoch)=>return Ok(()),
        value=async {if sequence.is_none(){before_first_frame(cancel,deadline,channel.wait()).await}else{Ok(channel.wait().await)}}=>value?};
        match msg {
            Some(ChannelMsg::Data { data }) => {
                for byte in data.iter() {
                    bytes.push(*byte);
                    if bytes.len() > LINE_LIMIT {
                        return Err("observe_limit");
                    }
                    if *byte == b'\n' {
                        let value = serde_json::from_slice(&bytes).map_err(|_| "invalid_frame")?;
                        bytes.clear();
                        let parsed = parse_stream_frame(value, sequence)?;
                        if sequence.is_none() && Instant::now() >= deadline {
                            return Err("timeout");
                        }
                        sequence = Some(parsed.seq);
                        let full = parsed.full;
                        tokio::select! {biased;_=cancel.wait()=>return Err("cancelled"),_=control.changed(epoch)=>return Ok(()),result=frame(epoch,parsed)=>{result?;}}
                        if !current(control, epoch) {
                            return Ok(());
                        }
                        if full {
                            audit.full_frame_received.store(true, Ordering::SeqCst);
                        }
                        if !ready {
                            ready = true;
                            let lease_cancel = match control.lease_cancel(epoch) {
                                Ok(cancel) => cancel,
                                Err(_) => return Ok(()),
                            };
                            let input = if supported {
                                hooks.map(|hooks| {
                                    Arc::new(input::LiveInput::new_observation(
                                        ssh.clone(),
                                        input::InputIdentity {
                                            route: route.clone(),
                                            host: config.host.clone(),
                                            port: config.port,
                                            user: config.username.clone(),
                                            host_key: config.expected_host_key.clone(),
                                            socket: config.socket_path.clone(),
                                            herdr: config.herdr_path.clone(),
                                            session: config.session.clone(),
                                            pane: pane.into(),
                                            terminal: terminal.into(),
                                        },
                                        cancel.clone(),
                                        lease_cancel,
                                        hooks.recovery.clone(),
                                    ))
                                })
                            } else {
                                None
                            };
                            if control.finish(epoch, ObservationPhase::Active, input.clone()) {
                                if let (Some(input), Some(hooks)) = (input, hooks)
                                    && current(control, epoch)
                                {
                                    (hooks.ready)(epoch, input);
                                }
                            } else {
                                return Ok(());
                            }
                        }
                    }
                }
            }
            Some(ChannelMsg::ExtendedData { data, .. }) => {
                stderr = stderr.checked_add(data.len()).ok_or("observe_limit")?;
                if stderr > 65536 {
                    return Err("observe_limit");
                }
            }
            Some(
                ChannelMsg::Failure
                | ChannelMsg::ExitStatus { .. }
                | ChannelMsg::Close
                | ChannelMsg::Eof,
            )
            | None => return Err("observe_ended"),
            _ => {}
        }
    }
}
