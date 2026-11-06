//! Self-created loopback SSH peers only; no host authorization or user keys.
use super::*;
use crate::input::SendOutcome;
use russh::{Channel, ChannelId, server};
use std::{path::PathBuf, process::Command, sync::atomic::AtomicUsize};
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
    execs: AtomicUsize,
    snapshots: AtomicUsize,
    closes: AtomicUsize,
    terminal: Mutex<String>,
    writes: Mutex<Vec<Vec<u8>>>,
    hold_receipt: AtomicBool,
    receipt: Notify,
    block_after_exec: AtomicBool,
    block_reads: AtomicBool,
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
            if user == "fixture" && key.public_key.key_data() == self.key.key_data() {
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
        if self.stats.block_after_exec.load(Ordering::SeqCst) {
            self.stats.block_reads.store(true, Ordering::SeqCst);
        }
        Ok(())
    }
    async fn channel_close(
        &mut self,
        _: ChannelId,
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        self.stats.closes.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
    async fn channel_open_direct_streamlocal(
        &mut self,
        channel: Channel<server::Msg>,
        _: &str,
        reply: server::ChannelOpenHandle,
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
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
            let response = match request["method"].as_str().unwrap_or("") {
                "session.snapshot" => {
                    stats.snapshots.fetch_add(1, Ordering::SeqCst);
                    serde_json::json!({"id":"pocket-readonly","result":{"type":"session_snapshot","snapshot":{"version":"0.9.5","protocol":22,"panes":[{"pane_id":"w1:p1","terminal_id":locked(&stats.terminal).clone()},{"pane_id":"w1:p2","terminal_id":"term_def"}]}}})
                }
                "pocket.input.capabilities" => {
                    serde_json::json!({"id":request["id"],"result":{"type":"pocket_input_capabilities","version":1,"protocol":22,"atomic_terminal_guard":true,"raw_bytes":true,"max_input_bytes":4096}})
                }
                "pocket.input.send" => {
                    let bytes =
                        Base64::decode_vec(request["params"]["bytes_base64"].as_str().unwrap())
                            .unwrap();
                    locked(&stats.writes).push(bytes.clone());
                    while stats.hold_receipt.load(Ordering::SeqCst) {
                        let wake = stats.receipt.notified();
                        tokio::pin!(wake);
                        wake.as_mut().enable();
                        if !stats.hold_receipt.load(Ordering::SeqCst) {
                            break;
                        }
                        wake.await;
                    }
                    serde_json::json!({"id":request["id"],"result":{"type":"pocket_input_accepted","pane_id":"w1:p1","terminal_id":"term_abc","accepted_bytes":bytes.len()}})
                }
                _ => return,
            };
            let mut bytes = serde_json::to_vec(&response).unwrap();
            bytes.push(b'\n');
            let _ = stream.write_all(&bytes).await;
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
        let control = ObservationControl::new();
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
    let mut view = View::launch(harness.config.clone(), Some(recovery.clone()));
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
