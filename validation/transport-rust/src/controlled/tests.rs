//! Self-created loopback SSH peers only; no host authorization or user keys.
use super::*;
use crate::input::SendOutcome;
use russh::{Channel, ChannelId, server};
use std::{collections::HashSet, path::PathBuf, process::Command, sync::atomic::AtomicUsize};
use std::collections::VecDeque;
use tokio::{
    io::{AsyncRead, AsyncWrite, ReadBuf},
    sync::mpsc,
};

struct Temp(PathBuf);
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
#[derive(Default)]
struct Stats {
    connections: AtomicUsize,
    auths: AtomicUsize,
    device_key: Mutex<Option<PublicKey>>,
    execs: AtomicUsize,
    terminal_delta: AtomicBool,
    snapshots: AtomicUsize,
    snapshot_active: AtomicUsize,
    snapshot_high: AtomicUsize,
    closes: AtomicUsize,
    terminal: Mutex<String>,
    writes: Mutex<Vec<Vec<u8>>>,
    hold_receipt: AtomicBool,
    hold_panes: Mutex<HashSet<String>>,
    released_requests: Mutex<HashSet<String>>,
    requests: Mutex<Vec<(String, String, String)>>,
    receipts: Mutex<Vec<(String, bool)>>,
    input_journal: Mutex<Option<PathBuf>>,
    persisted_before_input: AtomicUsize,
    receipt: Notify,
    block_after_exec: AtomicBool,
    block_reads: AtomicBool,
    watch_subscribers: AtomicUsize,
    watch_active: AtomicUsize,
    watch_high: AtomicUsize,
    watch_ids: Mutex<Vec<Vec<String>>>,
    events: Mutex<Vec<mpsc::UnboundedSender<Option<Value>>>>,
    panes: Mutex<Option<Vec<Value>>>,
    hold_snapshot: AtomicBool,
    snapshot_gate: Notify,
    watch_unsupported: AtomicBool,
    methods: Mutex<Vec<String>>,
    // Synthetic fault channels stay registered until the actual peer CLOSE.
    snapshot_fault_mode: AtomicUsize,
    snapshot_fault_channels: Mutex<HashSet<ChannelId>>,
    snapshot_fault_closed: AtomicUsize,
    snapshot_overlap: AtomicUsize,
    hold_streamlocal_open: AtomicBool,
    held_streamlocal_count: AtomicUsize,
    held_streamlocal: Mutex<Vec<(Channel<server::Msg>, server::ChannelOpenHandle)>>,
}
#[derive(Clone)]
struct Peer {
    stats: Arc<Stats>,
    key: PublicKey,
}
impl server::Handler for Peer {
    type Error = russh::Error;
    async fn auth_publickey(
        &mut self,
        user: &str,
        key: server::VerifiedPublicKey<'_>,
    ) -> std::result::Result<server::Auth, Self::Error> {
        self.stats.auths.fetch_add(1, Ordering::SeqCst);
        Ok(
            if user == "fixture" && (key.public_key.key_data() == self.key.key_data()
                || locked(&self.stats.device_key).as_ref().is_some_and(|allowed| key.public_key.key_data() == allowed.key_data())) {
                server::Auth::Accept
            } else {
                server::Auth::reject()
            },
        )
    }
    async fn channel_open_session(
        &mut self,
        _: Channel<server::Msg>,
        reply: server::ChannelOpenHandle,
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        reply.accept().await;
        Ok(())
    }
    async fn exec_request(
        &mut self,
        channel: ChannelId,
        _: &[u8],
        session: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        self.stats.execs.fetch_add(1, Ordering::SeqCst);
        session.channel_success(channel)?;
        session.data(channel,b"{\"type\":\"terminal.frame\",\"seq\":1,\"full\":true,\"encoding\":\"ansi\",\"width\":80,\"height\":24,\"bytes\":\"eA==\"}\n".to_vec())?;
        if self.stats.terminal_delta.load(Ordering::SeqCst) {
            session.data(channel,b"{\"type\":\"terminal.frame\",\"seq\":2,\"full\":false,\"encoding\":\"ansi\",\"width\":80,\"height\":24,\"bytes\":\"eQ==\"}\n".to_vec())?;
        }
        if self.stats.block_after_exec.load(Ordering::SeqCst) {
            self.stats.block_reads.store(true, Ordering::SeqCst);
        }
        Ok(())
    }
    async fn channel_close(
        &mut self,
        channel: ChannelId,
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        self.stats.closes.fetch_add(1, Ordering::SeqCst);
        if locked(&self.stats.snapshot_fault_channels).remove(&channel) {
            self.stats
                .snapshot_fault_closed
                .fetch_add(1, Ordering::SeqCst);
        }
        Ok(())
    }
    async fn channel_open_direct_streamlocal(
        &mut self,
        channel: Channel<server::Msg>,
        _: &str,
        reply: server::ChannelOpenHandle,
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        if self.stats.hold_streamlocal_open.load(Ordering::SeqCst) {
            self.stats
                .held_streamlocal_count
                .fetch_add(1, Ordering::SeqCst);
            // Retain both objects: dropping the reply would auto-reject rather
            // than emulate a server that never confirms the open.
            locked(&self.stats.held_streamlocal).push((channel, reply));
            return Ok(());
        }
        let channel_id = channel.id();
        reply.accept().await;
        let stats = self.stats.clone();
        tokio::spawn(async move {
            let mut stream = channel.into_stream();
            let mut raw = Vec::new();
            if BufReader::new(&mut stream)
                .read_until(b'\n', &mut raw)
                .await
                .is_err()
            {
                return;
            }
            let Ok(request) = serde_json::from_slice::<Value>(&raw) else {
                return;
            };
            let method = request["method"].as_str().unwrap_or("");
            locked(&stats.methods).push(method.into());
            if method == "events.subscribe" {
                stats.watch_subscribers.fetch_add(1, Ordering::SeqCst);
                if stats.watch_unsupported.load(Ordering::SeqCst) {
                    let mut raw=serde_json::to_vec(&serde_json::json!({"id":request["id"],"error":{"code":"unknown_method","message":"fixture unsupported"}})).unwrap();
                    raw.push(b'\n');
                    let _ = stream.write_all(&raw).await;
                    let _ = stream.shutdown().await;
                    return;
                }
                let ids: Vec<String> = request["params"]["subscriptions"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter_map(|s| s["pane_id"].as_str().map(str::to_owned))
                    .collect();
                locked(&stats.watch_ids).push(ids.clone());
                let mut raw=serde_json::to_vec(&serde_json::json!({"id":request["id"],"result":{"type":"subscription_started"}})).unwrap();
                raw.push(b'\n');
                let (tx, mut events) = mpsc::unbounded_channel();
                locked(&stats.events).push(tx);
                let active = stats.watch_active.fetch_add(1, Ordering::SeqCst) + 1;
                stats.watch_high.fetch_max(active, Ordering::SeqCst);
                struct Retire(Arc<Stats>);
                impl Drop for Retire {
                    fn drop(&mut self) {
                        self.0.watch_active.fetch_sub(1, Ordering::SeqCst);
                    }
                }
                let _retire = Retire(stats.clone());
                if stream.write_all(&raw).await.is_err() {
                    return;
                }
                loop {
                    let mut input = [0u8; 1];
                    tokio::select! {biased;
                        result=stream.read(&mut input)=>{if matches!(result,Ok(0)|Err(_)){return;}},
                        event=events.recv()=> {
                            let Some(Some(mut event))=event else {let _=stream.shutdown().await;return;};
                            if event.get("error").is_some(){event["id"]=request["id"].clone();}
                            if event["event"]=="pane.agent_status_changed" && !ids.iter().any(|id|event["data"]["pane_id"].as_str()==Some(id)){continue;}
                            let lost=event.get("error").is_some();let mut raw=serde_json::to_vec(&event).unwrap();raw.push(b'\n');
                            if stream.write_all(&raw).await.is_err(){return;}
                            if lost {let _=stream.shutdown().await;return;}
                        }
                    }
                }
            }
            if method == "session.snapshot" {
                if !locked(&stats.snapshot_fault_channels).is_empty() {
                    stats.snapshot_overlap.fetch_add(1, Ordering::SeqCst);
                }
                let fault = stats.snapshot_fault_mode.load(Ordering::SeqCst);
                if fault != 0 {
                    stats.snapshots.fetch_add(1, Ordering::SeqCst);
                    locked(&stats.snapshot_fault_channels).insert(channel_id);
                    if fault == 1 {
                        // An unterminated response exceeding the production
                        // limit, with the channel held open after the write.
                        let oversized = vec![b'x'; LINE_LIMIT + 1];
                        let _ = stream.write_all(&oversized).await;
                    }
                    // Fault 2 sends no response. In both cases the peer waits
                    // for client EOF; channel_close records the actual CLOSE.
                    let mut input = [0u8; 1];
                    while matches!(stream.read(&mut input).await, Ok(n) if n != 0) {}
                    return;
                }
            }
            let response = match method {
                "session.snapshot" => {
                    stats.snapshots.fetch_add(1, Ordering::SeqCst);
                    let active = stats.snapshot_active.fetch_add(1, Ordering::SeqCst) + 1;
                    stats.snapshot_high.fetch_max(active, Ordering::SeqCst);
                    struct ReadGuard(Arc<Stats>);
                    impl Drop for ReadGuard {
                        fn drop(&mut self) {
                            self.0.snapshot_active.fetch_sub(1, Ordering::SeqCst);
                        }
                    }
                    let _read = ReadGuard(stats.clone());
                    let panes=locked(&stats.panes).clone().unwrap_or_else(||vec![serde_json::json!({"pane_id":"w1:p1","terminal_id":locked(&stats.terminal).clone()}),serde_json::json!({"pane_id":"w1:p2","terminal_id":"term_def"})]);
                    while stats.hold_snapshot.load(Ordering::SeqCst) {
                        let wake = stats.snapshot_gate.notified();
                        tokio::pin!(wake);
                        wake.as_mut().enable();
                        if !stats.hold_snapshot.load(Ordering::SeqCst) {
                            break;
                        }
                        wake.await;
                    }
                    serde_json::json!({"id":"pocket-readonly","result":{"type":"session_snapshot","snapshot":{"version":"0.9.5","protocol":22,"panes":panes}}})
                }
                "pocket.input.capabilities" => {
                    serde_json::json!({"id":request["id"],"result":{"type":"pocket_input_capabilities","version":1,"protocol":22,"atomic_terminal_guard":true,"raw_bytes":true,"max_input_bytes":4096}})
                }
                "pocket.input.send" => {
                    let bytes =
                        Base64::decode_vec(request["params"]["bytes_base64"].as_str().unwrap())
                            .unwrap();
                    if let Some(path) = locked(&stats.input_journal).as_ref() {
                        let ledger: Value = serde_json::from_slice(
                            &std::fs::read(path.join("pending.json")).unwrap(),
                        )
                        .unwrap();
                        assert!(
                            ledger["records"].as_array().unwrap().iter().any(|raw| {
                                let marker: Value =
                                    serde_json::from_str(raw.as_str().unwrap()).unwrap();
                                marker["request_id"] == request["id"]
                                    && marker["target"]["pane"] == request["params"]["pane_id"]
                                    && marker["target"]["terminal"]
                                        == request["params"]["expected_terminal_id"]
                            }),
                            "remote input arrived before its exact durable marker"
                        );
                        stats.persisted_before_input.fetch_add(1, Ordering::SeqCst);
                    }
                    locked(&stats.writes).push(bytes.clone());
                    let id = request["id"].as_str().unwrap().to_owned();
                    let pane = request["params"]["pane_id"].as_str().unwrap().to_owned();
                    locked(&stats.requests).push((
                        id.clone(),
                        pane.clone(),
                        request["params"]["expected_terminal_id"]
                            .as_str()
                            .unwrap()
                            .to_owned(),
                    ));
                    let held = || {
                        (stats.hold_receipt.load(Ordering::SeqCst)
                            || locked(&stats.hold_panes).contains(&pane))
                            && !locked(&stats.released_requests).contains(&id)
                    };
                    while held() {
                        let wake = stats.receipt.notified();
                        tokio::pin!(wake);
                        wake.as_mut().enable();
                        if !held() {
                            break;
                        }
                        wake.await;
                    }
                    serde_json::json!({"id":request["id"],"result":{"type":"pocket_input_accepted","pane_id":request["params"]["pane_id"],"terminal_id":request["params"]["expected_terminal_id"],"accepted_bytes":bytes.len()}})
                }
                _ => return,
            };
            let mut bytes = serde_json::to_vec(&response).unwrap();
            bytes.push(b'\n');
            let written = stream.write_all(&bytes).await.is_ok();
            if method == "pocket.input.send" {
                locked(&stats.receipts).push((request["id"].as_str().unwrap().into(), written));
            }
            let _ = stream.shutdown().await;
        });
        Ok(())
    }
}
struct Gated {
    inner: tokio::net::TcpStream,
    stats: Arc<Stats>,
}
impl AsyncRead for Gated {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if this.stats.block_reads.load(Ordering::SeqCst) {
            Poll::Pending
        } else {
            Pin::new(&mut this.inner).poll_read(cx, buf)
        }
    }
}
impl AsyncWrite for Gated {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.get_mut().inner).poll_write(cx, buf)
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().inner).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().inner).poll_shutdown(cx)
    }
}
struct Harness {
    temp: Temp,
    config: RemoteConfig,
    stats: Arc<Stats>,
    server: tokio::task::JoinHandle<()>,
    children: Arc<Mutex<Vec<tokio::task::JoinHandle<()>>>>,
}
impl Drop for Harness {
    fn drop(&mut self) {
        self.server.abort();
        for task in locked(&self.children).drain(..) {
            task.abort();
        }
    }
}
impl Harness {
    async fn new() -> Self {
        Self::with_window(65536).await
    }
    async fn with_window(window: u32) -> Self {
        use ring::rand::SecureRandom;
        let mut nonce = [0u8; 16];
        ring::rand::SystemRandom::new().fill(&mut nonce).unwrap();
        let temp = Temp(std::env::temp_dir().join(format!(
            "herdr-controlled-{}",
            nonce.iter().map(|b| format!("{b:02x}")).collect::<String>()
        )));
        std::fs::create_dir(&temp.0).unwrap();
        let path = temp.0.join("key");
        assert!(
            Command::new("ssh-keygen")
                .args(["-q", "-t", "ed25519", "-N", "", "-f"])
                .arg(&path)
                .status()
                .unwrap()
                .success()
        );
        let pem = std::fs::read_to_string(path).unwrap();
        let key = decode_secret_key(&pem, None).unwrap();
        let public = key.public_key().clone();
        let pin = public
            .to_openssh()
            .unwrap()
            .split_whitespace()
            .take(2)
            .collect::<Vec<_>>()
            .join(" ");
        let stats = Arc::new(Stats::default());
        *locked(&stats.terminal) = "term_abc".into();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server_config = Arc::new(server::Config {
            keys: vec![key],
            window_size: window,
            auth_rejection_time: Duration::ZERO,
            auth_rejection_time_initial: Some(Duration::ZERO),
            ..Default::default()
        });
        let server_stats = stats.clone();
        let children = Arc::new(Mutex::new(Vec::new()));
        let child_tasks = children.clone();
        let server = tokio::spawn(async move {
            loop {
                let Ok((socket, _)) = listener.accept().await else {
                    return;
                };
                server_stats.connections.fetch_add(1, Ordering::SeqCst);
                let peer = Peer {
                    stats: server_stats.clone(),
                    key: public.clone(),
                };
                let stream = Gated {
                    inner: socket,
                    stats: server_stats.clone(),
                };
                let config = server_config.clone();
                locked(&child_tasks).push(tokio::spawn(async move {
                    if let Ok(session) = server::run_stream(config, stream, peer).await {
                        let _ = session.await;
                    }
                }));
            }
        });
        Self {
            temp,
            stats,
            server,
            children,
            config: RemoteConfig {
                schema_version: 1,
                host: "127.0.0.1".into(),
                port,
                username: "fixture".into(),
                expected_host_key: pin,
                private_key_pem: pem,
                socket_path: "/tmp/controlled/herdr/sessions/fixture/herdr.sock".into(),
                herdr_path: "/fixture/herdr".into(),
                session: "fixture".into(),
                pane_id: "w1:p1".into(),
                review_confirmed: true,
                observe_canvas: Default::default(),
            },
        }
    }
    fn recovery(&self, name: &str) -> recovery::SharedRecovery {
        recovery::Recovery::open(self.temp.0.join(name))
    }
}
struct Counting {
    dials: AtomicUsize,
}
impl transport::Dialer for Counting {
    fn dial(&self, host: String, port: u16, cancel: Cancellation) -> transport::DialFuture<'_> {
        self.dials.fetch_add(1, Ordering::SeqCst);
        transport::SystemDialer.dial(host, port, cancel)
    }
}
struct Full {
    epoch: u64,
    frame: StreamFrame,
    ack: oneshot::Sender<Result<()>>,
}
struct View {
    control: ObservationControl,
    cancel: Cancellation,
    dials: Arc<Counting>,
    frames: mpsc::Receiver<Full>,
    ready: mpsc::Receiver<(u64, Arc<input::LiveInput>)>,
    task: tokio::task::JoinHandle<Result<()>>,
}
impl View {
    fn launch(config: RemoteConfig, recovery: Option<recovery::SharedRecovery>) -> Self {
        Self::launch_inner(config, recovery, false)
    }
    fn launch_watched(config: RemoteConfig, recovery: Option<recovery::SharedRecovery>) -> Self {
        Self::launch_inner(config, recovery, true)
    }
    fn launch_inner(
        config: RemoteConfig,
        recovery: Option<recovery::SharedRecovery>,
        watched: bool,
    ) -> Self {
        let control = ObservationControl::new();
        if watched {
            control.set_dashboard_listener(Arc::new(|_| {})).unwrap();
        }
        let cancel = Cancellation::default();
        let dials = Arc::new(Counting {
            dials: AtomicUsize::new(0),
        });
        let (frames_tx, frames) = mpsc::channel(2);
        let (ready_tx, ready) = mpsc::channel(2);
        let hooks = recovery.map(|recovery| ControlledInputHooks {
            recovery,
            ready: Arc::new(move |epoch, input| {
                let _ = ready_tx.try_send((epoch, input));
            }),
            state: Arc::new(|_| {}),
        });
        let task_control = control.clone();
        let task_cancel = cancel.clone();
        let task_dials = dials.clone();
        let selected = config.pane_id.clone();
        let task = tokio::spawn(async move {
            observe_interactive_controlled_with_dialer(
                config,
                None,
                task_cancel,
                Arc::new(Audit::default()),
                |_| {},
                move |_| {
                    let selected = selected.clone();
                    async move { Ok(selected) }
                },
                move |epoch, frame| {
                    let tx = frames_tx.clone();
                    async move {
                        let (ack, rx) = oneshot::channel();
                        tx.send(Full { epoch, frame, ack })
                            .await
                            .map_err(|_| "frame_failed")?;
                        rx.await.map_err(|_| "frame_ack_cancelled")?
                    }
                },
                hooks,
                task_control,
                task_dials.as_ref(),
            )
            .await
        });
        Self {
            control,
            cancel,
            dials,
            frames,
            ready,
            task,
        }
    }
    async fn frame(&mut self) -> Full {
        timeout(Duration::from_secs(5), self.frames.recv())
            .await
            .unwrap()
            .unwrap()
    }
    async fn accept(&mut self) -> u64 {
        let full = self.frame().await;
        assert!(full.frame.full);
        assert_eq!(full.frame.seq, 1);
        full.ack.send(Ok(())).unwrap();
        let epoch = full.epoch;
        until(|| self.control.snapshot().phase == ObservationPhase::Active).await;
        epoch
    }
    async fn input(&mut self) -> (u64, Arc<input::LiveInput>) {
        timeout(Duration::from_secs(5), self.ready.recv())
            .await
            .unwrap()
            .unwrap()
    }
}
async fn until(predicate: impl Fn() -> bool) {
    timeout(Duration::from_secs(5), async {
        while !predicate() {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn pause_resume_reuses_authenticated_ssh_and_other_connection_is_independent() {
    let harness = Harness::new().await;
    let shared = harness.recovery("shared");
    let mut a = View::launch(harness.config.clone(), Some(shared.clone()));
    let mut b = View::launch(harness.config.clone(), None);
    let original = a.accept().await;
    let (_, old) = a.input().await;
    b.accept().await;
    let mode = old.set_mode("direct", true).unwrap();
    let paused = a.control.pause().unwrap();
    assert_eq!(
        old.send(mode, b"unsent".to_vec(), false).await,
        Err("input_stale")
    );
    let result = paused.await;
    if result.is_err() {
        panic!(
            "pause {result:?}; close events {}; task {:?}",
            harness.stats.closes.load(Ordering::SeqCst),
            a.task.await
        );
    }
    assert_eq!(result.unwrap().phase, ObservationPhase::Paused);
    assert!(!a.cancel.is_cancelled());
    assert_eq!(b.control.snapshot().phase, ObservationPhase::Active);
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 2);
    assert_eq!(a.dials.dials.load(Ordering::SeqCst), 1);
    let resume = a.control.resume().unwrap();
    let epoch = a.accept().await;
    assert!(epoch > original);
    assert_eq!(resume.await.unwrap().epoch, epoch);
    let (ready_epoch, new) = a.input().await;
    assert_eq!(ready_epoch, epoch);
    assert_eq!(
        new.send(0, b"must remain observe".to_vec(), false).await,
        Err("input_stale")
    );
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 2);
    assert_eq!(harness.stats.connections.load(Ordering::SeqCst), 2);
    assert_eq!(a.dials.dials.load(Ordering::SeqCst), 1);
    assert_eq!(b.dials.dials.load(Ordering::SeqCst), 1);
    assert_eq!(harness.stats.snapshots.load(Ordering::SeqCst), 3);
    assert!(locked(&harness.stats.writes).is_empty());
    for _ in 0..8 {
        a.control.pause().unwrap().await.unwrap();
        let resume = a.control.resume().unwrap();
        let epoch = a.accept().await;
        assert_eq!(resume.await.unwrap().epoch, epoch);
        assert_eq!(a.input().await.0, epoch);
    }
    assert_eq!(a.dials.dials.load(Ordering::SeqCst), 1);
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 2);
    a.cancel.cancel();
    assert!(a.task.await.unwrap().is_err());
    assert_eq!(b.control.snapshot().phase, ObservationPhase::Active);
    b.cancel.cancel();
    assert!(b.task.await.unwrap().is_err());
}

#[tokio::test]
async fn replacement_target_refuses_resume_without_dial_or_input() {
    let harness = Harness::new().await;
    let mut view = View::launch(harness.config.clone(), Some(harness.recovery("journal")));
    view.accept().await;
    view.input().await;
    view.control.pause().unwrap().await.unwrap();
    *locked(&harness.stats.terminal) = "term_def".into();
    let resume = view.control.resume().unwrap();
    assert!(resume.await.is_err());
    assert_eq!(view.task.await.unwrap(), Err("resume_target_changed"));
    assert_eq!(harness.stats.execs.load(Ordering::SeqCst), 1);
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 1);
    assert_eq!(view.dials.dials.load(Ordering::SeqCst), 1);
    assert!(locked(&harness.stats.writes).is_empty());
}

#[tokio::test]
async fn pause_and_cancel_interrupt_pending_frame_ack_and_supersede_resume() {
    let harness = Harness::new().await;
    let mut view = View::launch(harness.config.clone(), Some(harness.recovery("journal")));
    let old = view.frame().await;
    let first = old.epoch;
    view.control.pause().unwrap().await.unwrap();
    assert!(old.ack.send(Ok(())).is_err());
    assert!(view.ready.try_recv().is_err());
    let resume = view.control.resume().unwrap();
    let resumed = view.frame().await;
    assert!(resumed.epoch > first);
    let pause = view.control.pause().unwrap();
    assert_eq!(resume.await, Err("control_superseded"));
    assert_eq!(pause.await.unwrap().phase, ObservationPhase::Paused);
    assert!(resumed.ack.send(Ok(())).is_err());
    assert!(view.ready.try_recv().is_err());
    let resume = view.control.resume().unwrap();
    let newest = view.frame().await;
    assert!(newest.epoch > resumed.epoch);
    view.cancel.cancel();
    assert!(
        newest.ack.send(Ok(())).is_err()
            || view.control.snapshot().phase != ObservationPhase::Active
    );
    assert!(resume.await.is_err());
    assert!(view.task.await.unwrap().is_err());
    assert_eq!(view.dials.dials.load(Ordering::SeqCst), 1);
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn pause_submitted_input_is_unknown_and_late_receipt_never_clears_new_epoch() {
    let harness = Harness::new().await;
    harness.stats.hold_receipt.store(true, Ordering::SeqCst);
    let recovery = harness.recovery("journal");
    let mut view = View::launch_watched(harness.config.clone(), Some(recovery.clone()));
    view.accept().await;
    let (_, old) = view.input().await;
    let mut other_config = harness.config.clone();
    other_config.pane_id = "w1:p2".into();
    let mut other = View::launch(other_config, Some(recovery.clone()));
    other.accept().await;
    other.input().await;
    let mode = old.set_mode("direct", true).unwrap();
    let sending =
        tokio::spawn(async move { old.send(mode, b"submitted-once".to_vec(), false).await });
    until(|| locked(&harness.stats.writes).len() == 1).await;
    view.control.pause().unwrap().await.unwrap();
    assert_eq!(sending.await.unwrap().unwrap(), SendOutcome::Unknown);
    assert_eq!(recovery.status(), "pending");
    assert!(!view.cancel.is_cancelled());
    assert_eq!(other.control.snapshot().phase, ObservationPhase::Active);
    assert!(!other.cancel.is_cancelled());
    let resume = view.control.resume().unwrap();
    view.accept().await;
    resume.await.unwrap();
    let (_, current) = view.input().await;
    harness.stats.hold_receipt.store(false, Ordering::SeqCst);
    harness.stats.receipt.notify_waiters();
    tokio::time::sleep(Duration::from_millis(30)).await;
    assert_eq!(recovery.status(), "pending");
    let next = current.set_mode("direct", true).unwrap();
    assert_eq!(
        current.send(next, b"do-not-replay".to_vec(), false).await,
        Err("input_stale")
    );
    assert_eq!(locked(&harness.stats.writes).len(), 1);
    assert_eq!(view.dials.dials.load(Ordering::SeqCst), 1);
    other.control.pause().unwrap().await.unwrap();
    let other_resume = other.control.resume().unwrap();
    other.accept().await;
    other_resume.await.unwrap();
    let (_, other_input) = other.input().await;
    let review = other_input.set_mode("observe", true).unwrap();
    assert_eq!(
        other_input.acknowledge_unknown(review),
        Err("input_original_target_required")
    );
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 2);
    assert_eq!(locked(&harness.stats.writes).len(), 1);
    view.cancel.cancel();
    assert!(view.task.await.unwrap().is_err());
    assert_eq!(other.control.snapshot().phase, ObservationPhase::Active);
    other.cancel.cancel();
    assert!(other.task.await.unwrap().is_err());
}

#[tokio::test]
async fn silent_peer_does_not_prevent_local_retirement_or_claim_remote_exit() {
    let harness = Harness::new().await;
    harness.stats.block_after_exec.store(true, Ordering::SeqCst);
    let mut view = View::launch(harness.config.clone(), None);
    view.accept().await;
    let closed = harness.stats.closes.load(Ordering::SeqCst);
    let pause = view.control.pause().unwrap();
    assert_eq!(
        timeout(Duration::from_secs(2), pause)
            .await
            .unwrap()
            .unwrap()
            .phase,
        ObservationPhase::Paused
    );
    assert_eq!(harness.stats.closes.load(Ordering::SeqCst), closed);
    assert!(!view.cancel.is_cancelled());
    assert!(harness.stats.block_reads.load(Ordering::SeqCst));
    view.cancel.cancel();
    assert!(view.task.await.unwrap().is_err());
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 1);
    assert_eq!(view.dials.dials.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn zero_window_queued_data_close_terminates_only_its_ssh_instead_of_retaining_pending_channel()
 {
    let blocked = Harness::with_window(0).await;
    let healthy = Harness::new().await;
    let mut other = View::launch(healthy.config.clone(), None);
    other.accept().await;
    let cancel = Cancellation::default();
    let dialer = Counting {
        dials: AtomicUsize::new(0),
    };
    let (ssh, _) = authenticate_observer(
        &blocked.config,
        &cancel,
        Arc::new(Audit::default()),
        &|_| {},
        None,
        &dialer,
    )
    .await
    .unwrap();
    let mut channel = ssh.channel_open_session().await.unwrap();
    // The Handle path deliberately bypasses ChannelWriteHalf's window wait,
    // putting actual bytes into Encrypted.pending_data at the zero-window peer.
    ssh.data(channel.id(), b"queued-but-not-delivered".to_vec())
        .await
        .unwrap();
    assert_eq!(
        close_channel(&ssh, &cancel, &mut channel).await,
        Err("timeout")
    );
    assert!(cancel.is_cancelled());
    timeout(Duration::from_secs(2), async {
        while !ssh.is_closed() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(
        timeout(Duration::from_secs(2), channel.wait())
            .await
            .unwrap()
            .is_none()
    );
    assert_eq!(blocked.stats.execs.load(Ordering::SeqCst), 0);
    assert!(locked(&blocked.stats.writes).is_empty());
    assert_eq!(other.control.snapshot().phase, ObservationPhase::Active);
    assert_eq!(healthy.stats.auths.load(Ordering::SeqCst), 1);
    cancel.cancel();
    other.cancel.cancel();
    assert!(other.task.await.unwrap().is_err());
}

#[tokio::test]
async fn explicit_user_selection_has_no_eight_second_timeout_and_cancel_still_interrupts() {
    let harness = Harness::new().await;
    let control = ObservationControl::new();
    let cancel = Cancellation::default();
    let waiting = Arc::new(AtomicBool::new(false));
    let selected = waiting.clone();
    let task_cancel = cancel.clone();
    let task_control = control.clone();
    let config = harness.config.clone();
    let task = tokio::spawn(async move {
        observe_interactive_controlled_with_dialer(
            config,
            None,
            task_cancel,
            Arc::new(Audit::default()),
            |_| {},
            move |_| {
                selected.store(true, Ordering::SeqCst);
                async { std::future::pending::<Result<String>>().await }
            },
            |_, _| async { Ok(()) },
            None,
            task_control,
            &transport::SystemDialer,
        )
        .await
    });
    until(|| waiting.load(Ordering::SeqCst)).await;
    tokio::time::sleep(Duration::from_millis(8200)).await;
    assert!(!task.is_finished());
    assert_eq!(harness.stats.auths.load(Ordering::SeqCst), 1);
    assert_eq!(harness.stats.execs.load(Ordering::SeqCst), 0);
    cancel.cancel();
    assert_eq!(
        timeout(Duration::from_secs(2), task)
            .await
            .unwrap()
            .unwrap(),
        Err("cancelled")
    );
    assert_eq!(control.snapshot().phase, ObservationPhase::Closed);
}

#[derive(Default)]
struct DropGate {
    entered: AtomicBool,
    release: Mutex<bool>,
    changed: std::sync::Condvar,
    dropped: AtomicBool,
}
struct DelayedDrop {
    inner: Option<Box<dyn transport::ByteStream>>,
    gate: Arc<DropGate>,
}
impl Drop for DelayedDrop {
    fn drop(&mut self) {
        self.gate.entered.store(true, Ordering::SeqCst);
        let mut release = locked(&self.gate.release);
        while !*release {
            release = self.gate.changed.wait(release).unwrap();
        }
        drop(self.inner.take());
        self.gate.dropped.store(true, Ordering::SeqCst);
    }
}
impl transport::ByteStream for DelayedDrop {
    fn abort(&mut self) {
        if let Some(inner) = &mut self.inner {
            inner.abort();
        }
    }
}
impl AsyncRead for DelayedDrop {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut **self.get_mut().inner.as_mut().unwrap()).poll_read(cx, buf)
    }
}
impl AsyncWrite for DelayedDrop {
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
struct DelayedDialer(Arc<DropGate>);
impl transport::Dialer for DelayedDialer {
    fn dial(&self, host: String, port: u16, cancel: Cancellation) -> transport::DialFuture<'_> {
        Box::pin(async move {
            let inner = transport::SystemDialer.dial(host, port, cancel).await?;
            Ok(Box::new(DelayedDrop {
                inner: Some(inner),
                gate: self.0.clone(),
            }) as Box<dyn transport::ByteStream>)
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn closing_owner_does_not_finish_before_actual_io_drop() {
    let harness = Harness::new().await;
    let gate = Arc::new(DropGate::default());
    let task_gate = gate.clone();
    let control = ObservationControl::new();
    let task_control = control.clone();
    let cancel = Cancellation::default();
    let task_cancel = cancel.clone();
    let config = harness.config.clone();
    let task = tokio::spawn(async move {
        observe_interactive_controlled_with_dialer(
            config,
            None,
            task_cancel,
            Arc::new(Audit::default()),
            |_| {},
            |_| async { Ok("w1:p1".into()) },
            |_, _| async { Ok(()) },
            None,
            task_control,
            &DelayedDialer(task_gate),
        )
        .await
    });
    until(|| control.snapshot().phase == ObservationPhase::Active).await;
    cancel.cancel();
    until(|| gate.entered.load(Ordering::SeqCst)).await;
    assert!(!task.is_finished());
    assert_ne!(control.snapshot().phase, ObservationPhase::Closed);
    *locked(&gate.release) = true;
    gate.changed.notify_all();
    assert_eq!(
        timeout(Duration::from_secs(2), task)
            .await
            .unwrap()
            .unwrap(),
        Err("cancelled")
    );
    assert!(gate.dropped.load(Ordering::SeqCst));
    assert_eq!(control.snapshot().phase, ObservationPhase::Closed);
}

struct Watching {
    control: ObservationControl,
    cancel: Cancellation,
    updates: mpsc::UnboundedReceiver<session_watch::SessionWatchUpdate>,
    frames: mpsc::UnboundedReceiver<u64>,
    task: tokio::task::JoinHandle<Result<()>>,
    choose: Arc<Notify>,
}
impl Watching {
    fn launch(h: &Harness, target: DashboardTarget, wait_for_choice: bool) -> Self {
        let control = ObservationControl::new();
        let cancel = Cancellation::default();
        let (tx, updates) = mpsc::unbounded_channel();
        control
            .set_dashboard_listener(Arc::new(move |update| {
                let _ = tx.send(update);
            }))
            .unwrap();
        let (frame_tx, frames) = mpsc::unbounded_channel();
        let config = h.config.clone();
        let choose = Arc::new(Notify::new());
        let gate = choose.clone();
        let c = control.clone();
        let stop = cancel.clone();
        let task = tokio::spawn(async move {
            observe_interactive_controlled_target_with_dialer(
                config,
                None,
                stop,
                Arc::new(Audit::default()),
                |_| {},
                move |_| {
                    let gate = gate.clone();
                    let target = target.clone();
                    async move {
                        if wait_for_choice {
                            gate.notified().await;
                        }
                        Ok(target)
                    }
                },
                move |epoch, frame| {
                    let tx = frame_tx.clone();
                    async move {
                        assert!(frame.full);
                        let _ = tx.send(epoch);
                        Ok(())
                    }
                },
                None,
                c,
                &transport::SystemDialer,
            )
            .await
        });
        Self {
            control,
            cancel,
            updates,
            frames,
            task,
            choose,
        }
    }
    async fn update(
        &mut self,
        predicate: impl Fn(&session_watch::SessionWatchUpdate) -> bool,
    ) -> session_watch::SessionWatchUpdate {
        timeout(Duration::from_secs(7), async {
            loop {
                let next = self.updates.recv().await.expect("watch ended");
                if predicate(&next) {
                    return next;
                }
            }
        })
        .await
        .unwrap()
    }
    async fn fresh(&mut self) -> session_watch::SessionWatchUpdate {
        self.update(|u| u.phase == session_watch::SessionWatchPhase::Fresh)
            .await
    }
    async fn full(&mut self) -> u64 {
        timeout(Duration::from_secs(7), self.frames.recv())
            .await
            .unwrap()
            .unwrap()
    }
    async fn stop(self) {
        self.cancel.cancel();
        assert!(
            timeout(Duration::from_secs(7), self.task)
                .await
                .unwrap()
                .unwrap()
                .is_err()
        );
    }
}
fn target(pane: &str, terminal: &str) -> DashboardTarget {
    DashboardTarget {
        pane_id: pane.into(),
        terminal_id: terminal.into(),
    }
}
fn event(h: &Harness, value: Option<Value>) {
    for tx in locked(&h.stats.events).iter() {
        let _ = tx.send(value.clone());
    }
}
fn changed(h: &Harness) {
    event(
        h,
        Some(
            serde_json::json!({"event":"pane_updated","data":{"type":"pane_updated","pane":{"pane_id":"w1:p2"}}}),
        ),
    );
}
fn set_panes(h: &Harness, panes: Value) {
    *locked(&h.stats.panes) = Some(panes.as_array().unwrap().clone());
}

// Exercise the exact bridge called by Tauri's just-paired remote_observe.
// This fixture never contacts a real host or installs a key authorization.
use crate::direct_observation::{DirectObservation, ObserveEvent};
struct DirectView {
    bridge: Arc<DirectObservation>,
    events: mpsc::UnboundedReceiver<ObserveEvent>,
    task: tokio::task::JoinHandle<Result<()>>,
    dials: Arc<Counting>,
    seen_frames: Vec<(u64, bool)>,
    pending_events: VecDeque<ObserveEvent>,
}
impl DirectView {
    fn launch(h: &Harness, device: Option<(String, Arc<dyn DeviceSigner>)>) -> Self {
        let bridge = DirectObservation::new(73, Cancellation::default());
        let runner = bridge.clone();
        let (tx, events) = mpsc::unbounded_channel();
        let emit = Arc::new(move |event| tx.send(event).map_err(|_| "client_closed"));
        let mut config = h.config.clone();
        if device.is_some() { config.private_key_pem.clear(); }
        let recovery = h.recovery("direct-input");
        let dials = Arc::new(Counting { dials: AtomicUsize::new(0) });
        let dialer = dials.clone();
        let task = tokio::spawn(async move {
            runner.run(config, device, Arc::new(Audit::default()), Arc::new(|_| {}), emit, recovery, dialer.as_ref()).await
        });
        Self { bridge, events, task, dials, seen_frames: Vec::new(), pending_events: VecDeque::new() }
    }
    async fn next(&mut self, predicate: impl Fn(&ObserveEvent) -> bool) -> ObserveEvent {
        // Dashboard publication wakes the selector before its listener emits
        // Fresh. With two workers, SelectionReady may arrive on either side of
        // Fresh; waiting for one must not discard the other (or an ACK frame).
        if let Some(index) = self.pending_events.iter().position(&predicate) {
            return self.pending_events.remove(index).unwrap();
        }
        timeout(Duration::from_secs(7), async {
            loop {
                let event = self.events.recv().await.expect("observation ended before expected event");
                if let ObserveEvent::Frame { frame, .. } = &event { self.seen_frames.push((frame.seq, frame.full)); }
                if predicate(&event) { return event; }
                self.pending_events.push_back(event);
            }
        }).await.unwrap()
    }
    async fn fresh(&mut self) -> session_watch::SessionWatchUpdate {
        match self.next(|e| matches!(e, ObserveEvent::DashboardWatch { update, .. } if update.phase == session_watch::SessionWatchPhase::Fresh)).await {
            ObserveEvent::DashboardWatch { update, .. } => update,
            _ => unreachable!(),
        }
    }
    async fn ready(&mut self) -> u64 {
        match self.next(|e| matches!(e, ObserveEvent::SelectionReady { .. })).await {
            ObserveEvent::SelectionReady { epoch, .. } => epoch,
            _ => unreachable!(),
        }
    }
    fn choose(&self, update: &session_watch::SessionWatchUpdate, terminal: &str) -> Result<()> {
        self.bridge.select(73, update.epoch, update.revision, "w1:p1".into(), terminal.into())
    }
    async fn stop(self, h: &Harness) {
        self.bridge.cancel();
        assert_eq!(timeout(Duration::from_secs(7), self.task).await.unwrap().unwrap(), Err("cancelled"));
        until(|| h.stats.watch_active.load(Ordering::SeqCst) == 0).await;
        // The peer's SSH driver must finish before Harness::drop can abort it.
        // This distinguishes real connection retirement from a closed UI slot.
        until(|| locked(&h.children).iter().all(|task| task.is_finished())).await;
        assert_eq!(self.dials.dials.load(Ordering::SeqCst), 1);
        assert_eq!(h.stats.connections.load(Ordering::SeqCst), 1);
        assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
        assert!(locked(&h.stats.writes).is_empty());
        assert!(!locked(&h.stats.methods).iter().any(|m| m.contains("resize") || m == "pocket.input.send"));
    }
}

// No peer is needed to prove the consumer keeps both event kinds. Closing the
// sender makes the old drop-unmatched implementation fail immediately rather
// than relying on a timing threshold. The SSH/ACK test below covers the bridge.
#[tokio::test]
async fn direct_view_retains_ready_and_fresh_in_both_arrival_and_wait_orders() {
    for ready_arrives_first in [false, true] {
        for wait_for_ready_first in [false, true] {
            let (tx, events) = mpsc::unbounded_channel();
            let ready = ObserveEvent::SelectionReady { generation: 73, epoch: 1 };
            let fresh = ObserveEvent::DashboardWatch {
                generation: 73,
                update: session_watch::SessionWatchUpdate {
                    epoch: 1, revision: 3, phase: session_watch::SessionWatchPhase::Fresh,
                    reason: "snapshot", panes: Some(vec![]),
                },
            };
            let ordered = if ready_arrives_first { [ready, fresh] } else { [fresh, ready] };
            for event in ordered { tx.send(event).unwrap_or_else(|_| panic!("fixture receiver closed")); }
            drop(tx);
            let mut view = DirectView {
                bridge: DirectObservation::new(73, Cancellation::default()), events,
                task: tokio::spawn(async { Ok(()) }),
                dials: Arc::new(Counting { dials: AtomicUsize::new(0) }),
                seen_frames: Vec::new(), pending_events: VecDeque::new(),
            };
            if wait_for_ready_first {
                assert_eq!(view.ready().await, 1);
                assert_eq!(view.fresh().await.revision, 3);
            } else {
                assert_eq!(view.fresh().await.revision, 3);
                assert_eq!(view.ready().await, 1);
            }
            assert!(view.pending_events.is_empty());
            assert!(view.events.try_recv().is_err());
            assert_eq!(view.task.await.unwrap(), Ok(()));
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn direct_paired_bridge_watch_and_terminal_share_signer_and_full_delta_ack() {
    use crate::pairing::{KeyStore, VolatileKeyStore};
    struct Signer { store: Arc<VolatileKeyStore>, handle: String, calls: Arc<AtomicUsize> }
    impl DeviceSigner for Signer {
        fn sign(&self, data: &[u8]) -> std::result::Result<Vec<u8>, ()> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.store.sign(&self.handle, data).map_err(|_| ())
        }
    }
    let h = Harness::new().await;
    h.stats.terminal_delta.store(true, Ordering::SeqCst);
    let store = Arc::new(VolatileKeyStore::default());
    let (handle, public) = store.create().unwrap();
    *locked(&h.stats.device_key) = Some(PublicKey::from_openssh(&public).unwrap());
    let calls = Arc::new(AtomicUsize::new(0));
    let signer = Arc::new(Signer { store, handle, calls: calls.clone() });
    let signer_lifetime = Arc::downgrade(&signer);
    let mut view = DirectView::launch(&h, Some((public, signer)));
    // Attach announces epoch before dashboard events. Fresh and SelectionReady
    // come from concurrent tasks; retain both regardless of arrival order.
    assert!(matches!(view.events.recv().await, Some(ObserveEvent::Observation { generation: 73, snapshot: ObservationSnapshot { epoch: 1, phase: ObservationPhase::Starting } })));
    let first = view.fresh().await;
    assert_eq!(view.ready().await, first.epoch);
    view.choose(&first, "term_abc").unwrap();
    let bound = view.next(|e| matches!(e, ObserveEvent::TargetBound { .. })).await;
    assert!(matches!(bound, ObserveEvent::TargetBound { generation: 73, epoch: 1, ref pane_id, ref terminal_id } if pane_id == "w1:p1" && terminal_id == "term_abc"));
    let full = view.next(|e| matches!(e, ObserveEvent::Frame { .. })).await;
    assert!(matches!(full, ObserveEvent::Frame { epoch: 1, frame: StreamFrame { seq: 1, full: true, .. }, .. }));
    assert_eq!(view.bridge.ack(72, 1, 1), Err("stale_ack"));
    assert_eq!(view.bridge.ack(73, 2, 1), Err("stale_ack"));
    assert_eq!(view.bridge.ack(73, 1, 2), Err("stale_ack"));
    // A dashboard status refresh completes while the full terminal frame is
    // still awaiting GUI ACK, proving the two channels run concurrently.
    set_panes(&h, serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc","agent_status":"blocked"},{"pane_id":"w1:p3","terminal_id":"term_123","agent_status":"working"}]));
    changed(&h);
    let refreshed = view.fresh().await;
    assert!(refreshed.revision > first.revision);
    assert!(refreshed.panes.as_ref().unwrap().iter().any(|p| p.pane_id == "w1:p3"));
    assert_eq!(view.seen_frames, vec![(1, true)]);
    while let Ok(event) = view.events.try_recv() { assert!(!matches!(event, ObserveEvent::Frame { .. })); }
    view.bridge.ack(73, 1, 1).unwrap();
    let delta = view.next(|e| matches!(e, ObserveEvent::Frame { .. })).await;
    assert!(matches!(delta, ObserveEvent::Frame { epoch: 1, frame: StreamFrame { seq: 2, full: false, .. }, .. }));
    assert_eq!(view.bridge.ack(73, 1, 1), Err("stale_ack"));
    view.bridge.ack(73, 1, 2).unwrap();
    assert_eq!(view.bridge.ack(73, 1, 2), Err("stale_ack"));
    assert!(calls.load(Ordering::SeqCst) > 0);
    assert!(signer_lifetime.upgrade().is_some());
    assert_eq!(h.stats.execs.load(Ordering::SeqCst), 1);
    view.stop(&h).await;
    assert!(signer_lifetime.upgrade().is_none());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn direct_paired_bridge_rejects_old_epoch_revision_replaced_row_and_duplicate_selection() {
    let h = Harness::new().await;
    let mut view = DirectView::launch(&h, None);
    let first = view.fresh().await;
    view.ready().await;
    h.stats.hold_snapshot.store(true, Ordering::SeqCst);
    set_panes(&h, serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_cde","agent_status":"working"}]));
    changed(&h);
    let stale = view.next(|e| matches!(e, ObserveEvent::DashboardWatch { update, .. } if update.phase == session_watch::SessionWatchPhase::Stale)).await;
    let ObserveEvent::DashboardWatch { update: stale, .. } = stale else { unreachable!() };
    assert_eq!(view.choose(&stale, "term_abc"), Err("dashboard_stale"));
    h.stats.hold_snapshot.store(false, Ordering::SeqCst);
    h.stats.snapshot_gate.notify_waiters();
    let current = view.fresh().await;
    assert_eq!(view.choose(&first, "term_abc"), Err("dashboard_stale"));
    assert_eq!(view.choose(&current, "term_abc"), Err("target_changed"));
    assert_eq!(view.bridge.select(72, current.epoch, current.revision, "w1:p1".into(), "term_cde".into()), Err("stale_selection"));
    assert_eq!(view.bridge.select(73, current.epoch + 1, current.revision, "w1:p1".into(), "term_cde".into()), Err("stale_selection"));
    view.choose(&current, "term_cde").unwrap();
    assert_eq!(view.choose(&current, "term_cde"), Err("stale_selection"));
    assert!(matches!(view.next(|e| matches!(e, ObserveEvent::TargetBound { .. })).await, ObserveEvent::TargetBound { ref terminal_id, .. } if terminal_id == "term_cde"));
    view.stop(&h).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn direct_paired_bridge_cancel_covers_selection_and_first_frame_ack() {
    for select in [false, true] {
        let h = Harness::new().await;
        let mut view = DirectView::launch(&h, None);
        let first = view.fresh().await;
        view.ready().await;
        if select {
            view.choose(&first, "term_abc").unwrap();
            view.next(|e| matches!(e, ObserveEvent::Frame { .. })).await;
        }
        let bridge = view.bridge.clone();
        view.stop(&h).await;
        assert_eq!(bridge.select(73, first.epoch, first.revision, "w1:p1".into(), "term_abc".into()), Err("stale_selection"));
        assert_eq!(bridge.ack(73, first.epoch, 1), Err("stale_ack"));
        assert!(bridge.input(73).is_err());
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn direct_paired_bridge_reports_unsupported_watch_without_claiming_freshness() {
    let h = Harness::new().await;
    h.stats.watch_unsupported.store(true, Ordering::SeqCst);
    let mut view = DirectView::launch(&h, None);
    let event = view.next(|e| matches!(e, ObserveEvent::DashboardWatch { update, .. } if update.phase == session_watch::SessionWatchPhase::Unavailable && update.panes.is_some())).await;
    let ObserveEvent::DashboardWatch { update, .. } = event else { unreachable!() };
    assert_eq!(update.reason, "watch_unsupported");
    view.ready().await;
    view.choose(&update, "term_abc").unwrap();
    view.next(|e| matches!(e, ObserveEvent::Frame { .. })).await;
    assert_eq!(h.stats.watch_subscribers.load(Ordering::SeqCst), 1);
    view.stop(&h).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_lifecycle_status_refreshes_authoritative_panes_without_input_or_resize() {
    let h = Harness::new().await;
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    view.fresh().await;
    view.full().await;
    set_panes(
        &h,
        serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc","agent_status":"blocked"},{"pane_id":"w1:p3","terminal_id":"term_123","agent_status":"working"}]),
    );
    event(
        &h,
        Some(
            serde_json::json!({"event":"pane_created","data":{"type":"pane_created","pane":{"pane_id":"w1:p3"}}}),
        ),
    );
    let added = view
        .update(|u| {
            u.phase == session_watch::SessionWatchPhase::Fresh
                && u.panes
                    .as_ref()
                    .is_some_and(|p| p.iter().any(|p| p.pane_id == "w1:p3"))
        })
        .await;
    assert_eq!(added.panes.unwrap()[0].agent_status, "blocked");
    assert!(
        locked(&h.stats.watch_ids)
            .last()
            .unwrap()
            .contains(&"w1:p3".into())
    );
    set_panes(
        &h,
        serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc","agent_status":"idle"}]),
    );
    event(
        &h,
        Some(
            serde_json::json!({"event":"pane_closed","data":{"type":"pane_closed","pane_id":"w1:p3","workspace_id":"w1"}}),
        ),
    );
    view.update(|u| {
        u.phase == session_watch::SessionWatchPhase::Fresh
            && u.panes.as_ref().is_some_and(|p| p.len() == 1)
    })
    .await;
    set_panes(
        &h,
        serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc","agent_status":"working"}]),
    );
    event(
        &h,
        Some(
            serde_json::json!({"event":"pane.agent_status_changed","data":{"pane_id":"w1:p1","workspace_id":"w1","agent_status":"blocked"}}),
        ),
    );
    let status = view.fresh().await;
    // Event says blocked; authoritative snapshot says working and must win.
    assert_eq!(status.panes.unwrap()[0].agent_status, "working");
    set_panes(
        &h,
        serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc","agent_status":"idle"},{"pane_id":"w1:p4","terminal_id":"term_456"}]),
    );
    event(
        &h,
        Some(
            serde_json::json!({"event":"pane_created","data":{"type":"pane_created","pane":{"pane_id":"w1:p4"}}}),
        ),
    );
    view.update(|u| {
        u.phase == session_watch::SessionWatchPhase::Fresh
            && u.panes.as_ref().is_some_and(|p| p.len() == 2)
    })
    .await;
    set_panes(
        &h,
        serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc","agent_status":"idle"}]),
    );
    event(
        &h,
        Some(
            serde_json::json!({"event":"pane_exited","data":{"type":"pane_exited","pane_id":"w1:p4","workspace_id":"w1"}}),
        ),
    );
    view.update(|u| {
        u.phase == session_watch::SessionWatchPhase::Fresh
            && u.panes.as_ref().is_some_and(|p| p.len() == 1)
    })
    .await;
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.execs.load(Ordering::SeqCst), 1);
    assert!(locked(&h.stats.writes).is_empty());
    assert!(
        locked(&h.stats.methods)
            .iter()
            .all(|m| matches!(m.as_str(), "session.snapshot" | "events.subscribe"))
    );
    assert_eq!(h.stats.watch_high.load(Ordering::SeqCst), 1);
    view.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_loss_marks_stale_before_inflight_snapshot_and_resubscribes_same_ssh() {
    let h = Harness::new().await;
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    view.fresh().await;
    view.full().await;
    let before = h.stats.snapshots.load(Ordering::SeqCst);
    h.stats.hold_snapshot.store(true, Ordering::SeqCst);
    changed(&h);
    until(|| h.stats.snapshots.load(Ordering::SeqCst) > before).await;
    event(
        &h,
        Some(
            serde_json::json!({"id":"ignored-fixture-id","error":{"code":"events_lost","message":"fixture overrun"}}),
        ),
    );
    let lost = view.update(|u| u.reason == "events_lost").await;
    assert_eq!(lost.phase, session_watch::SessionWatchPhase::Stale);
    assert!(lost.panes.is_none());
    assert!(h.stats.hold_snapshot.load(Ordering::SeqCst));
    h.stats.hold_snapshot.store(false, Ordering::SeqCst);
    h.stats.snapshot_gate.notify_waiters();
    let recovered = view.fresh().await;
    assert!(recovered.revision > lost.revision);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    let subscriptions = h.stats.watch_subscribers.load(Ordering::SeqCst);
    event(&h, None);
    view.update(|u| u.reason == "watch_disconnected").await;
    view.fresh().await;
    assert!(h.stats.watch_subscribers.load(Ordering::SeqCst) > subscriptions);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    view.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_storm_coalesces_while_reading_and_never_replays_payloads() {
    let h = Harness::new().await;
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    view.fresh().await;
    view.full().await;
    let before = h.stats.snapshots.load(Ordering::SeqCst);
    h.stats.hold_snapshot.store(true, Ordering::SeqCst);
    changed(&h);
    until(|| h.stats.snapshots.load(Ordering::SeqCst) > before).await;
    for _ in 0..500 {
        changed(&h);
    }
    set_panes(
        &h,
        serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc","agent_status":"idle"},{"pane_id":"w1:p2","terminal_id":"term_def"}]),
    );
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert!(
        view.updates.len() < 20,
        "event payloads became an unbounded callback backlog while read was pending"
    );
    assert_eq!(h.stats.snapshot_high.load(Ordering::SeqCst), 1);
    h.stats.hold_snapshot.store(false, Ordering::SeqCst);
    h.stats.snapshot_gate.notify_waiters();
    let fresh = view.fresh().await;
    assert_eq!(fresh.panes.unwrap()[0].agent_status, "idle");
    assert!(
        h.stats.snapshots.load(Ordering::SeqCst) - before <= 4,
        "storm created excess snapshot requests"
    );
    assert!(locked(&h.stats.writes).is_empty());
    view.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_target_replacement_ends_observer_without_silent_reselection() {
    let h = Harness::new().await;
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    view.fresh().await;
    view.full().await;
    *locked(&h.stats.terminal) = "term_123".into();
    changed(&h);
    assert_eq!(
        timeout(Duration::from_secs(7), view.task)
            .await
            .unwrap()
            .unwrap(),
        Err("resume_target_changed")
    );
    assert_eq!(h.stats.execs.load(Ordering::SeqCst), 1);
    assert!(locked(&h.stats.writes).is_empty());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_pause_retires_subscription_and_old_events_cannot_freshen_resumed_epoch() {
    let h = Harness::new().await;
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    let first = view.fresh().await;
    view.full().await;
    let old = locked(&h.stats.events).last().unwrap().clone();
    view.control.pause().unwrap().await.unwrap();
    until(|| h.stats.watch_active.load(Ordering::SeqCst) == 0).await;
    while view.updates.try_recv().is_ok() {}
    assert!(
        old.send(Some(serde_json::json!({"event":"pane_updated","data":{}})))
            .is_err()
    );
    assert!(view.updates.try_recv().is_err());
    let ack = view.control.resume().unwrap();
    let next = view.full().await;
    ack.await.unwrap();
    let fresh = view
        .update(|u| u.phase == session_watch::SessionWatchPhase::Fresh && u.epoch == next)
        .await;
    assert!(fresh.epoch > first.epoch);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    assert!(locked(&h.stats.writes).is_empty());
    view.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_typed_selection_accepts_new_row_and_rejects_reused_old_row() {
    let h = Harness::new().await;
    let mut view = Watching::launch(&h, target("w1:p3", "term_123"), true);
    view.fresh().await;
    set_panes(
        &h,
        serde_json::json!([{"pane_id":"w1:p1","terminal_id":"term_abc"},{"pane_id":"w1:p3","terminal_id":"term_123"}]),
    );
    changed(&h);
    view.update(|u| {
        u.phase == session_watch::SessionWatchPhase::Fresh
            && u.panes
                .as_ref()
                .is_some_and(|p| p.iter().any(|p| p.pane_id == "w1:p3"))
    })
    .await;
    view.choose.notify_one();
    view.full().await;
    view.stop().await;
    let h = Harness::new().await;
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), true);
    view.fresh().await;
    *locked(&h.stats.terminal) = "term_123".into();
    changed(&h);
    view.update(|u| {
        u.phase == session_watch::SessionWatchPhase::Fresh
            && u.panes
                .as_ref()
                .is_some_and(|p| p[0].terminal_id == "term_123")
    })
    .await;
    view.choose.notify_one();
    assert_eq!(
        timeout(Duration::from_secs(7), view.task)
            .await
            .unwrap()
            .unwrap(),
        Err("resume_target_changed")
    );
    assert_eq!(h.stats.execs.load(Ordering::SeqCst), 0);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_unsupported_is_separate_from_terminal_and_does_not_retry_ssh() {
    let h = Harness::new().await;
    h.stats.watch_unsupported.store(true, Ordering::SeqCst);
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    view.update(|u| u.phase == session_watch::SessionWatchPhase::Unavailable && u.panes.is_some())
        .await;
    view.full().await;
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.watch_subscribers.load(Ordering::SeqCst), 1);
    assert!(locked(&h.stats.writes).is_empty());
    view.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_fault_oversized_snapshots_retire_before_each_retry_on_same_ssh() {
    let h = Harness::new().await;
    h.stats.snapshot_fault_mode.store(1, Ordering::SeqCst);
    let cancel = Cancellation::default();
    let control = ObservationControl::new();
    let dialer = Counting {
        dials: AtomicUsize::new(0),
    };
    let (ssh, _) = authenticate_observer(
        &h.config,
        &cancel,
        Arc::new(Audit::default()),
        &|_| {},
        None,
        &dialer,
    )
    .await
    .unwrap();
    let epoch = control.snapshot().epoch;
    for _ in 0..3 {
        assert_eq!(
            timeout(
                Duration::from_secs(12),
                snapshot(&ssh, &h.config, &cancel, &control, epoch)
            )
            .await
            .unwrap(),
            Err("snapshot_limit")
        );
        assert!(!cancel.is_cancelled());
    }
    h.stats.snapshot_fault_mode.store(0, Ordering::SeqCst);
    let current = timeout(
        Duration::from_secs(5),
        snapshot(&ssh, &h.config, &cancel, &control, epoch),
    )
    .await
    .unwrap()
    .unwrap()
    .unwrap();
    assert_eq!(snapshot_terminal(&current, "w1:p1").unwrap(), "term_abc");
    until(|| h.stats.snapshot_fault_closed.load(Ordering::SeqCst) == 3).await;
    assert_eq!(h.stats.snapshot_overlap.load(Ordering::SeqCst), 0);
    assert!(locked(&h.stats.snapshot_fault_channels).is_empty());
    assert_eq!(dialer.dials.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.connections.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    assert!(locked(&h.stats.writes).is_empty());
    cancel.cancel();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_fault_snapshot_read_timeout_retires_before_same_ssh_recovers() {
    let h = Harness::new().await;
    h.stats.snapshot_fault_mode.store(2, Ordering::SeqCst);
    let cancel = Cancellation::default();
    let control = ObservationControl::new();
    let dialer = Counting {
        dials: AtomicUsize::new(0),
    };
    let (ssh, _) = authenticate_observer(
        &h.config,
        &cancel,
        Arc::new(Audit::default()),
        &|_| {},
        None,
        &dialer,
    )
    .await
    .unwrap();
    let epoch = control.snapshot().epoch;
    assert_eq!(
        timeout(
            Duration::from_secs(15),
            snapshot(&ssh, &h.config, &cancel, &control, epoch)
        )
        .await
        .unwrap(),
        Err("timeout")
    );
    assert!(!cancel.is_cancelled());
    h.stats.snapshot_fault_mode.store(0, Ordering::SeqCst);
    let current = timeout(
        Duration::from_secs(5),
        snapshot(&ssh, &h.config, &cancel, &control, epoch),
    )
    .await
    .unwrap()
    .unwrap()
    .unwrap();
    assert_eq!(snapshot_terminal(&current, "w1:p1").unwrap(), "term_abc");
    until(|| h.stats.snapshot_fault_closed.load(Ordering::SeqCst) == 1).await;
    assert_eq!(h.stats.snapshot_overlap.load(Ordering::SeqCst), 0);
    assert_eq!(dialer.dials.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.connections.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    assert!(locked(&h.stats.writes).is_empty());
    cancel.cancel();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_fault_unconfirmed_open_cancels_owner_without_redial() {
    let h = Harness::new().await;
    h.stats.hold_streamlocal_open.store(true, Ordering::SeqCst);
    let view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    until(|| h.stats.held_streamlocal_count.load(Ordering::SeqCst) == 1).await;
    let result = timeout(Duration::from_secs(15), view.task)
        .await
        .unwrap()
        .unwrap();
    assert!(result.is_err());
    assert!(view.cancel.is_cancelled());
    // The controlled owner joins actual I/O before reporting Closed.
    assert_eq!(view.control.snapshot().phase, ObservationPhase::Closed);
    assert_eq!(h.stats.held_streamlocal_count.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.connections.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.watch_subscribers.load(Ordering::SeqCst), 0);
    assert!(locked(&h.stats.methods).is_empty());
    assert!(locked(&h.stats.writes).is_empty());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watch_fault_oversized_watch_retries_do_not_accumulate_channels() {
    let h = Harness::new().await;
    h.stats.snapshot_fault_mode.store(1, Ordering::SeqCst);
    let mut view = Watching::launch(&h, target("w1:p1", "term_abc"), false);
    // Let the real watcher schedule retries itself. The peer checks each new
    // snapshot against fault-channel CLOSEs already processed on this SSH.
    until(|| h.stats.snapshots.load(Ordering::SeqCst) >= 3).await;
    h.stats.snapshot_fault_mode.store(0, Ordering::SeqCst);
    let fresh = view.fresh().await;
    assert!(
        fresh
            .panes
            .unwrap()
            .iter()
            .any(|pane| pane.pane_id == "w1:p1")
    );
    view.full().await;
    assert!(h.stats.snapshot_fault_closed.load(Ordering::SeqCst) >= 3);
    assert!(locked(&h.stats.snapshot_fault_channels).is_empty());
    assert_eq!(h.stats.snapshot_overlap.load(Ordering::SeqCst), 0);
    assert_eq!(h.stats.connections.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 1);
    assert!(locked(&h.stats.writes).is_empty());
    view.stop().await;
}

fn input_identity(h: &Harness, pane: &str, terminal: &str) -> input::InputIdentity {
    input::InputIdentity {
        route: None,
        host: h.config.host.clone(),
        port: h.config.port,
        user: h.config.username.clone(),
        host_key: h.config.expected_host_key.clone(),
        socket: h.config.socket_path.clone(),
        herdr: h.config.herdr_path.clone(),
        session: h.config.session.clone(),
        pane: pane.into(),
        terminal: terminal.into(),
    }
}
fn release_receipt(h: &Harness, id: &str) {
    locked(&h.stats.released_requests).insert(id.into());
    h.stats.receipt.notify_waiters();
}
fn request_for(h: &Harness, pane: &str, index: usize) -> String {
    locked(&h.stats.requests)
        .iter()
        .filter(|(_, p, _)| p == pane)
        .nth(index)
        .unwrap()
        .0
        .clone()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn target_recovery_real_ssh_unknown_a_does_not_block_b_and_old_ack_guard_review_cannot_clear_new_requests()
 {
    let h = Harness::new().await;
    let recovery = h.recovery("target-journal");
    *locked(&h.stats.input_journal) = Some(h.temp.0.join("target-journal"));
    let identity_a = input_identity(&h, "w1:p1", "term_abc");
    let identity_b = input_identity(&h, "w1:p2", "term_def");
    let mut a = View::launch_watched(h.config.clone(), Some(recovery.clone()));
    a.accept().await;
    let (_, input_a) = a.input().await;
    let mut config_b = h.config.clone();
    config_b.pane_id = "w1:p2".into();
    let mut b = View::launch(config_b, Some(recovery.clone()));
    b.accept().await;
    let (_, input_b) = b.input().await;
    locked(&h.stats.hold_panes).extend(["w1:p1".into(), "w1:p2".into()]);
    let mode_a = input_a.set_mode("direct", true).unwrap();
    let send_a =
        tokio::spawn(async move { input_a.send(mode_a, b"a-old-once".to_vec(), false).await });
    until(|| locked(&h.stats.requests).len() == 1).await;
    // A's active marker must not deny a different pane's actual SSH write.
    assert_eq!(input_b.recovery_status(), "ready");
    let mode_b = input_b.set_mode("direct", true).unwrap();
    let pending_b = input_b.clone();
    let send_b = tokio::spawn(async move {
        pending_b
            .send(mode_b, b"b-first-once".to_vec(), false)
            .await
    });
    until(|| locked(&h.stats.requests).len() == 2).await;
    let old_a = request_for(&h, "w1:p1", 0);
    let first_b = request_for(&h, "w1:p2", 0);
    assert_eq!(
        recovery.pending_id(&identity_a).unwrap().as_deref(),
        Some(old_a.as_str())
    );
    assert_eq!(
        recovery.pending_id(&identity_b).unwrap().as_deref(),
        Some(first_b.as_str())
    );
    a.control.pause().unwrap().await.unwrap();
    assert_eq!(send_a.await.unwrap().unwrap(), SendOutcome::Unknown);
    // The cancelled A guard has run. B's independent original operation is
    // still active and cannot be human-cleared by this or any other adapter.
    assert_eq!(
        recovery.clear_reviewed(&identity_b, &first_b),
        Err("input_write_pending")
    );
    release_receipt(&h, &first_b);
    let SendOutcome::Accepted(receipt) = send_b.await.unwrap().unwrap() else {
        panic!("B must receive its own matching receipt")
    };
    assert_eq!(receipt.request_id, first_b);
    assert_eq!(receipt.pane_id, "w1:p2");
    assert_eq!(receipt.terminal_id, "term_def");
    assert_eq!(receipt.accepted_bytes, b"b-first-once".len());
    assert_eq!(
        recovery.pending_id(&identity_a).unwrap(),
        Some(old_a.clone())
    );
    assert_eq!(input_b.recovery_status(), "ready");
    let resume = a.control.resume().unwrap();
    a.accept().await;
    resume.await.unwrap();
    let (_, fresh_a) = a.input().await;
    // An alias has the exact same remote identity, not a new journal key.
    // It freezes the old pending ID at a separately consumed fresh full.
    let mut reviewer = View::launch(h.config.clone(), Some(recovery.clone()));
    reviewer.accept().await;
    let (_, stale_review) = reviewer.input().await;
    let stale_epoch = stale_review.set_mode("observe", true).unwrap();
    assert!(stale_review.unknown());
    let reviewed = fresh_a.set_mode("observe", true).unwrap();
    fresh_a.acknowledge_unknown(reviewed).unwrap();
    let mode = fresh_a.set_mode("direct", true).unwrap();
    let sending_a = fresh_a.clone();
    let newer_a =
        tokio::spawn(async move { sending_a.send(mode, b"a-new-once".to_vec(), false).await });
    until(|| locked(&h.stats.requests).len() == 3).await;
    let sending_b = input_b.clone();
    let newer_b =
        tokio::spawn(async move { sending_b.send(mode_b, b"b-new-once".to_vec(), false).await });
    until(|| locked(&h.stats.requests).len() == 4).await;
    let new_a = request_for(&h, "w1:p1", 1);
    let new_b = request_for(&h, "w1:p2", 1);
    assert_ne!(old_a, new_a);
    // Release only the old A reply. Neither newer request has a result yet.
    release_receipt(&h, &old_a);
    until(|| locked(&h.stats.receipts).iter().any(|(id, _)| id == &old_a)).await;
    assert_eq!(
        recovery.pending_id(&identity_a).unwrap(),
        Some(new_a.clone())
    );
    assert_eq!(
        recovery.pending_id(&identity_b).unwrap(),
        Some(new_b.clone())
    );
    assert_eq!(
        recovery.clear_reviewed(&identity_a, &new_a),
        Err("input_write_pending")
    );
    assert_eq!(
        recovery.clear_reviewed(&identity_b, &new_b),
        Err("input_write_pending")
    );
    assert_eq!(
        stale_review.acknowledge_unknown(stale_epoch),
        Err("input_original_target_required")
    );
    a.control.pause().unwrap().await.unwrap();
    assert_eq!(newer_a.await.unwrap().unwrap(), SendOutcome::Unknown);
    b.control.pause().unwrap().await.unwrap();
    assert_eq!(newer_b.await.unwrap().unwrap(), SendOutcome::Unknown);
    // Even after active retirement, a late review from the old full cannot
    // clear the newer same-target request. Nor can another target clear it.
    assert_eq!(
        stale_review.acknowledge_unknown(stale_epoch),
        Err("input_original_target_required")
    );
    assert_eq!(
        recovery.pending_id(&identity_a).unwrap(),
        Some(new_a.clone())
    );
    assert_eq!(
        recovery.pending_id(&identity_b).unwrap(),
        Some(new_b.clone())
    );
    assert_eq!(
        locked(&h.stats.writes).as_slice(),
        [
            b"a-old-once".to_vec(),
            b"b-first-once".to_vec(),
            b"a-new-once".to_vec(),
            b"b-new-once".to_vec()
        ]
    );
    assert_eq!(h.stats.persisted_before_input.load(Ordering::SeqCst), 4);
    assert_eq!(a.dials.dials.load(Ordering::SeqCst), 1);
    assert_eq!(b.dials.dials.load(Ordering::SeqCst), 1);
    assert_eq!(h.stats.auths.load(Ordering::SeqCst), 3);
    release_receipt(&h, &new_a);
    release_receipt(&h, &new_b);
    for view in [a, b, reviewer] {
        view.cancel.cancel();
        assert!(view.task.await.unwrap().is_err());
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn target_recovery_real_ssh_same_identity_alias_cannot_write_or_resolve_active_other_view() {
    let h = Harness::new().await;
    let recovery = h.recovery("same-target-journal");
    *locked(&h.stats.input_journal) = Some(h.temp.0.join("same-target-journal"));
    let mut a = View::launch(h.config.clone(), Some(recovery.clone()));
    a.accept().await;
    let (_, input_a) = a.input().await;
    let mut alias = View::launch(h.config.clone(), Some(recovery.clone()));
    alias.accept().await;
    let (_, input_alias) = alias.input().await;
    locked(&h.stats.hold_panes).insert("w1:p1".into());
    let mode = input_a.set_mode("direct", true).unwrap();
    let sending =
        tokio::spawn(async move { input_a.send(mode, b"only-one".to_vec(), false).await });
    until(|| locked(&h.stats.requests).len() == 1).await;
    let alias_mode = input_alias.set_mode("direct", true).unwrap();
    assert_eq!(
        input_alias
            .send(alias_mode, b"must-not-send".to_vec(), false)
            .await,
        Err("input_stale")
    );
    assert_eq!(locked(&h.stats.requests).len(), 1);
    // A view obtaining a new full during the active request captures its ID,
    // but cannot turn that into permission to clear an operation still active.
    let mut reviewer = View::launch(h.config.clone(), Some(recovery.clone()));
    reviewer.accept().await;
    let (_, input_review) = reviewer.input().await;
    // Match the native mode-command mapping: ordinary observe/blur must not
    // gain review focus, even with a fresh full and the correct pending ID.
    let blurred = input_review.set_mode("observe", false).unwrap();
    assert_eq!(
        input_review.acknowledge_unknown(blurred),
        Err("input_stale")
    );
    let mode = input_review.set_mode("observe", true).unwrap();
    assert_eq!(
        input_review.acknowledge_unknown(mode),
        Err("input_write_pending")
    );
    a.control.pause().unwrap().await.unwrap();
    assert_eq!(sending.await.unwrap().unwrap(), SendOutcome::Unknown);
    let lost_focus = input_review.set_mode("observe", false).unwrap();
    assert_ne!(mode, lost_focus);
    assert_eq!(input_review.acknowledge_unknown(mode), Err("input_stale"));
    let reviewed_epoch = input_review.set_mode("observe", true).unwrap();
    input_review.acknowledge_unknown(reviewed_epoch).unwrap();
    assert_eq!(recovery.status(), "ready");
    assert_eq!(locked(&h.stats.writes).as_slice(), [b"only-one".to_vec()]);
    assert_eq!(h.stats.persisted_before_input.load(Ordering::SeqCst), 1);
    let old = request_for(&h, "w1:p1", 0);
    release_receipt(&h, &old);
    until(|| locked(&h.stats.receipts).iter().any(|(id, _)| id == &old)).await;
    for view in [a, alias, reviewer] {
        view.cancel.cancel();
        assert!(view.task.await.unwrap().is_err());
    }
}
