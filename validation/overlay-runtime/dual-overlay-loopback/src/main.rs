//! Opt-in same-process acceptance client. Inputs and authorization exchange are
//! private fixture files; the result contains only fixed booleans and categories.
use herdr_overlay_runtime_probe::{
    Failure, OverlayRuntime, ProfileKey, Provider,
    nodes::{NodeLease, NodeSpec, NodeStatus, SecretConfig, SecureConfigSource},
    tailscale::{
        LoginStatus, NativeNodeConfig, NativeStateSource, NativeStateStore, NativeVettedDirectory,
        StateStoreError, StateStoreResult,
    },
};
use herdr_readonly_transport::{
    Audit, AuditSnapshot, Cancellation, ControlledInputHooks, ObservationControl, RemoteConfig,
    input::{LiveInput, SendOutcome},
    observe_interactive_controlled_with_dialer,
    overlay::OverlayDialer,
    recovery::Recovery,
    transport::Dialer,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::sync::mpsc;
use zeroize::Zeroize;

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
enum StopFirst {
    Et,
    Ts,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Input {
    stop_first: StopFirst,
    network: String,
    native_config: String,
    control_url: String,
    node_dir: PathBuf,
    exchange: PathBuf,
    et_recovery: PathBuf,
    ts_recovery: PathBuf,
    et_remote: RemoteConfig,
    ts_remote: RemoteConfig,
    local_port: u16,
}
#[derive(Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct Report {
    passed: bool,
    error: Option<&'static str>,
    prelogin_url_absent: bool,
    prelogin_needs_login: bool,
    begin_login_submitted: bool,
    begin_login_succeeded: bool,
    last_ts_state: Option<&'static str>,
    prelogin_dial_rejected: bool,
    et_full: bool,
    ts_full: bool,
    et_first: bool,
    ts_first: bool,
    et_stopped: bool,
    et_stale_rejected: bool,
    ts_after_stop: bool,
    ts_stopped: bool,
    ts_stale_rejected: bool,
    et_after_stop: bool,
    et_observer_joined: bool,
    ts_observer_joined: bool,
    et_observer: ObserverReport,
    ts_observer: ObserverReport,
    local_fallback_rejected: bool,
    cross_route_rejected: bool,
    cleanup: bool,
    reserved_nodes: usize,
    reserved_streams: usize,
}
struct EtSource(Mutex<Option<SecretConfig>>);
impl SecureConfigSource for EtSource {
    fn load(&self, _: &NodeSpec) -> Result<SecretConfig, Failure> {
        self.0
            .lock()
            .map_err(|_| Failure::IdentityUnavailable)?
            .take()
            .ok_or(Failure::IdentityUnavailable)
    }
}
#[derive(Default)]
struct MemoryStore(Mutex<HashMap<Vec<u8>, Vec<u8>>>);
impl NativeStateStore for MemoryStore {
    fn read(&self, key: &[u8]) -> StateStoreResult<Vec<u8>> {
        self.0
            .lock()
            .map_err(|_| StateStoreError::Unavailable)?
            .get(key)
            .cloned()
            .ok_or(StateStoreError::Missing)
    }
    fn write(&self, key: &[u8], value: Option<&[u8]>) -> StateStoreResult<()> {
        let mut map = self.0.lock().map_err(|_| StateStoreError::Unavailable)?;
        match value {
            Some(value) => {
                map.insert(key.to_vec(), value.to_vec());
            }
            None => {
                map.remove(key);
            }
        }
        Ok(())
    }
}
struct TsSource {
    path: PathBuf,
    url: String,
    store: Arc<MemoryStore>,
}
impl NativeStateSource for TsSource {
    fn load(&self, spec: &NodeSpec) -> Result<NativeNodeConfig, Failure> {
        NativeNodeConfig::for_spec(
            spec,
            NativeVettedDirectory::from_native_vetted(self.path.clone())?,
            "herdr-dual-fixture".into(),
            self.url.clone(),
            self.store.clone(),
        )
    }
}
fn spec(provider: Provider, id: &str, network: String) -> NodeSpec {
    NodeSpec {
        profile: ProfileKey {
            provider,
            id: id.into(),
        },
        revision: 1,
        profile_revision: 1,
        network,
        identity_ref: "temporary-in-memory".into(),
    }
}
fn op<T>(
    result: Result<herdr_overlay_runtime_probe::nodes::NodeOperation<T>, Failure>,
) -> Result<T, &'static str> {
    result
        .and_then(|operation| operation.wait(Duration::from_secs(15)))
        .map_err(|_| "node_operation_failed")
}
fn status_label(state: NodeStatus) -> &'static str {
    match state {
        NodeStatus::Starting => "starting",
        NodeStatus::EngineStarted => "engine_started",
        NodeStatus::NeedsLogin => "needs_login",
        NodeStatus::NeedsMachineAuth => "needs_machine_auth",
        NodeStatus::Running => "running",
        NodeStatus::Closing => "closing",
        NodeStatus::Stopped => "stopped",
        NodeStatus::ZeroTier { .. } => "other",
    }
}
fn ready_for_explicit_login(status: &LoginStatus) -> bool {
    status.state == NodeStatus::NeedsLogin && status.auth_url.is_none()
}
fn stop(runtime: &OverlayRuntime, node: &NodeLease) -> bool {
    op(runtime.stop_node(node, Duration::from_secs(8))).is_ok()
}
#[derive(Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct ObserverReport {
    stage: Option<&'static str>,
    error: Option<&'static str>,
    audit: AuditSnapshot,
}
#[derive(Default)]
struct ObserverTrace {
    stage: Mutex<Option<&'static str>>,
    error: Mutex<Option<&'static str>>,
    audit: Arc<Audit>,
}
impl ObserverTrace {
    fn snapshot(&self) -> ObserverReport {
        ObserverReport {
            stage: self.stage.lock().ok().and_then(|v| *v),
            error: self.error.lock().ok().and_then(|v| *v),
            audit: self.audit.snapshot(),
        }
    }
}
fn observer_error(code: &'static str) -> &'static str {
    match code {
        "invalid_config"
        | "invalid_private_key"
        | "invalid_host_key"
        | "host_key_mismatch"
        | "overlay_provider_unavailable"
        | "overlay_stale_revision"
        | "overlay_wrong_owner"
        | "overlay_unknown_write"
        | "overlay_transport_failed"
        | "handshake_failed"
        | "authentication_failed"
        | "socket_unavailable"
        | "snapshot_failed"
        | "snapshot_rejected"
        | "invalid_snapshot"
        | "pane_missing"
        | "ambiguous_pane"
        | "invalid_terminal_id"
        | "observe_failed"
        | "invalid_full_frame"
        | "observe_ended"
        | "observe_close_failed"
        | "observe_limit"
        | "cancelled"
        | "timeout"
        | "input_unavailable"
        | "listener_failed"
        | "frame_failed"
        | "resume_target_changed" => code,
        _ => "other_observer_error",
    }
}
fn observer_stage(stage: &'static str) -> &'static str {
    match stage {
        "connecting"
        | "host-key-verified"
        | "authenticated"
        | "snapshot-received"
        | "full-frame-received"
        | "input-unavailable" => stage,
        _ => "other",
    }
}
struct Session {
    ready: mpsc::Receiver<Arc<LiveInput>>,
    frames: mpsc::Receiver<Vec<u8>>,
    cancel: Cancellation,
    task: tokio::task::JoinHandle<Result<(), &'static str>>,
    trace: Arc<ObserverTrace>,
}
fn launch(config: RemoteConfig, dialer: Arc<OverlayDialer>, directory: PathBuf) -> Session {
    let (ready_tx, ready) = mpsc::channel(4);
    let (frame_tx, frames) = mpsc::channel(64);
    let cancel = Cancellation::default();
    let task_cancel = cancel.clone();
    let trace = Arc::new(ObserverTrace::default());
    let task_trace = trace.clone();
    let task = tokio::spawn(async move {
        let result = async {
            let selected = config.pane_id.clone();
            let control = ObservationControl::new();
            control
                .set_dashboard_listener(Arc::new(|_| {}))
                .map_err(|_| "listener_failed")?;
            let hooks = ControlledInputHooks {
                recovery: Recovery::open(directory),
                ready: Arc::new(move |_, input| {
                    let _ = ready_tx.try_send(input);
                }),
                state: Arc::new(|_| {}),
            };
            let stage_trace = task_trace.clone();
            observe_interactive_controlled_with_dialer(
                config,
                None,
                task_cancel,
                task_trace.audit.clone(),
                move |stage| {
                    if let Ok(mut value) = stage_trace.stage.lock() {
                        *value = Some(observer_stage(stage));
                    }
                },
                move |_| {
                    let selected = selected.clone();
                    async move { Ok(selected) }
                },
                move |_, frame| {
                    let tx = frame_tx.clone();
                    async move { tx.send(frame.bytes).await.map_err(|_| "frame_failed") }
                },
                Some(hooks),
                control,
                dialer.as_ref(),
            )
            .await
        }
        .await;
        if let Err(code) = result {
            if let Ok(mut value) = task_trace.error.lock() {
                *value = Some(observer_error(code));
            }
        }
        result
    });
    Session {
        ready,
        frames,
        cancel,
        task,
        trace,
    }
}
async fn wait_input(session: &mut Session) -> Result<Arc<LiveInput>, &'static str> {
    tokio::time::timeout(Duration::from_secs(25), session.ready.recv())
        .await
        .map_err(|_| "input_ready_timeout")?
        .ok_or("input_not_ready")
}
async fn marker(session: &mut Session, needle: &[u8]) -> Result<(), &'static str> {
    let limit = Instant::now() + Duration::from_secs(12);
    let mut bytes = Vec::new();
    while Instant::now() < limit && bytes.len() < 1024 * 1024 {
        match tokio::time::timeout_at(tokio::time::Instant::from_std(limit), session.frames.recv())
            .await
        {
            Ok(Some(frame)) => {
                bytes.extend(frame);
                if bytes.windows(needle.len()).any(|v| v == needle) {
                    return Ok(());
                }
            }
            _ => break,
        }
    }
    Err("frame_marker_missing")
}
fn accepted(outcome: Result<SendOutcome, &'static str>, length: usize) -> bool {
    matches!(outcome, Ok(SendOutcome::Accepted(receipt)) if receipt.accepted_bytes == length)
}
async fn send(input: &LiveInput, data: &[u8]) -> Result<(), &'static str> {
    let epoch = input
        .set_mode("direct", true)
        .map_err(|_| "input_mode_failed")?;
    if accepted(input.send(epoch, data.to_vec(), false).await, data.len()) {
        Ok(())
    } else {
        Err("input_send_failed")
    }
}
fn explicit_dial_error<T, E>(outcome: Result<Result<T, E>, tokio::time::error::Elapsed>) -> bool {
    matches!(outcome, Ok(Err(_)))
}
async fn reject(dialer: &OverlayDialer, host: &str, port: u16) -> bool {
    explicit_dial_error(
        tokio::time::timeout(
            Duration::from_secs(5),
            dialer.dial(host.into(), port, Cancellation::default()),
        )
        .await,
    )
}

async fn run(
    input: &Input,
    runtime: Arc<OverlayRuntime>,
    et: NodeLease,
    ts: NodeLease,
    report: &mut Report,
) -> Result<(), &'static str> {
    let et_dial = Arc::new(
        OverlayDialer::new(runtime.clone(), et.clone(), Duration::from_secs(3))
            .map_err(|_| "dialer_failed")?,
    );
    let ts_dial = Arc::new(
        OverlayDialer::new(runtime.clone(), ts.clone(), Duration::from_secs(3))
            .map_err(|_| "dialer_failed")?,
    );
    let mut a = launch(
        input.et_remote.clone(),
        et_dial.clone(),
        input.et_recovery.clone(),
    );
    let mut b = launch(
        input.ts_remote.clone(),
        ts_dial.clone(),
        input.ts_recovery.clone(),
    );
    let mut a_awaited = false;
    let mut b_awaited = false;
    let result = async {
        let (ai, bi) = tokio::join!(wait_input(&mut a), wait_input(&mut b));
        report.et_full = ai.is_ok();
        report.ts_full = bi.is_ok();
        let ai = ai?;
        let bi = bi?;
        report.local_fallback_rejected = reject(&et_dial, "127.0.0.1", input.local_port).await
            && reject(&ts_dial, "127.0.0.1", input.local_port).await;
        if !report.local_fallback_rejected {
            return Err("local_fallback_not_rejected");
        }
        report.cross_route_rejected = reject(&et_dial, &input.ts_remote.host, input.ts_remote.port)
            .await
            && reject(&ts_dial, &input.et_remote.host, input.et_remote.port).await;
        if !report.cross_route_rejected {
            return Err("cross_route_not_rejected");
        }
        send(&ai, b"ET-ONE\n").await?;
        marker(&mut a, b"ACK-ET-ONE").await?;
        report.et_first = true;
        send(&bi, b"TS-ONE\n").await?;
        marker(&mut b, b"ACK-TS-ONE").await?;
        report.ts_first = true;
        let (retired, survivor, old_input, live_input, node, stale_bytes, next_bytes, ack) =
            match input.stop_first {
                StopFirst::Et => (
                    &mut a,
                    &mut b,
                    &ai,
                    &bi,
                    et.clone(),
                    b"ET-STALE\n".as_slice(),
                    b"TS-TWO\n".as_slice(),
                    b"ACK-TS-TWO".as_slice(),
                ),
                StopFirst::Ts => (
                    &mut b,
                    &mut a,
                    &bi,
                    &ai,
                    ts.clone(),
                    b"TS-STALE\n".as_slice(),
                    b"ET-TWO\n".as_slice(),
                    b"ACK-ET-TWO".as_slice(),
                ),
            };
        let stale = old_input
            .set_mode("direct", true)
            .map_err(|_| "input_mode_failed")?;
        let rt = runtime.clone();
        let stopped = tokio::task::spawn_blocking(move || stop(&rt, &node))
            .await
            .unwrap_or(false);
        match input.stop_first {
            StopFirst::Et => report.et_stopped = stopped,
            StopFirst::Ts => report.ts_stopped = stopped,
        }
        if !stopped {
            return Err("provider_stop_failed");
        }
        let joined = matches!(
            tokio::time::timeout(Duration::from_secs(8), &mut retired.task).await,
            Ok(Ok(_))
        );
        match input.stop_first {
            StopFirst::Et => {
                a_awaited = true;
                report.et_observer_joined = joined;
            }
            StopFirst::Ts => {
                b_awaited = true;
                report.ts_observer_joined = joined;
            }
        }
        if !joined {
            return Err("observer_join_failed");
        }
        let rejected = old_input
            .send(stale, stale_bytes.to_vec(), false)
            .await
            .is_err();
        match input.stop_first {
            StopFirst::Et => report.et_stale_rejected = rejected,
            StopFirst::Ts => report.ts_stale_rejected = rejected,
        }
        if !rejected {
            return Err("stale_input_not_rejected");
        }
        send(live_input, next_bytes).await?;
        marker(survivor, ack).await?;
        match input.stop_first {
            StopFirst::Et => report.ts_after_stop = true,
            StopFirst::Ts => report.et_after_stop = true,
        }
        Ok(())
    }
    .await;
    a.cancel.cancel();
    b.cancel.cancel();
    if !a_awaited {
        report.et_observer_joined = matches!(
            tokio::time::timeout(Duration::from_secs(8), &mut a.task).await,
            Ok(Ok(_))
        );
    }
    if !b_awaited {
        report.ts_observer_joined = matches!(
            tokio::time::timeout(Duration::from_secs(8), &mut b.task).await,
            Ok(Ok(_))
        );
    }
    if !report.et_observer_joined {
        a.task.abort();
    }
    if !report.ts_observer_joined {
        b.task.abort();
    }
    report.et_observer = a.trace.snapshot();
    report.ts_observer = b.trace.snapshot();
    if !report.et_observer_joined || !report.ts_observer_joined {
        return Err("observer_join_failed");
    }
    result
}
fn execute(mut input: Input, report: &mut Report) -> Result<(), &'static str> {
    if !cfg!(feature = "real") {
        return Err("real_candidates_required");
    }
    let runtime = Arc::new(OverlayRuntime::new());
    let et_source = Arc::new(EtSource(Mutex::new(Some(
        SecretConfig::from_bytes(std::mem::take(&mut input.native_config).into_bytes())
            .map_err(|_| "invalid_et_config")?,
    ))));
    let et = op(runtime.start_easytier_profile(
        spec(Provider::EasyTier, "et", input.network.clone()),
        Some(et_source),
        Duration::from_secs(8),
    ))?;
    let ts_source = Arc::new(TsSource {
        path: input.node_dir.clone(),
        url: input.control_url.clone(),
        store: Arc::new(MemoryStore::default()),
    });
    let ts = match op(runtime.start_tailscale_profile(
        spec(Provider::Tailscale, "ts", "isolated-ts".into()),
        Some(ts_source),
        Duration::from_secs(8),
    )) {
        Ok(ts) => ts,
        Err(e) => {
            stop(&runtime, &et);
            return Err(e);
        }
    };
    let result = (|| {
        // Start completion is not the same as the engine reaching NeedsLogin.
        // Calling interactive login while Starting can return before a URL is issued.
        let prelogin_deadline = Instant::now() + Duration::from_secs(25);
        loop {
            let before = op(runtime.node_login_status(&ts, Duration::from_secs(5)))?;
            report.last_ts_state = Some(status_label(before.state));
            if before.auth_url.is_some() {
                return Err("unexpected_prelogin_url");
            }
            report.prelogin_url_absent = true;
            if ready_for_explicit_login(&before) {
                report.prelogin_needs_login = true;
                break;
            }
            if Instant::now() >= prelogin_deadline {
                return Err("prelogin_state_timeout");
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let prelogin_dialer =
            OverlayDialer::new(runtime.clone(), ts.clone(), Duration::from_secs(3))
                .map_err(|_| "dialer_failed")?;
        let prelogin_executor = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|_| "executor_failed")?;
        report.prelogin_dial_rejected = prelogin_executor.block_on(reject(
            &prelogin_dialer,
            &input.ts_remote.host,
            input.ts_remote.port,
        ));
        if !report.prelogin_dial_rejected {
            return Err("prelogin_dial_not_rejected");
        }
        report.begin_login_submitted = true;
        let login = op(runtime.begin_node_login(&ts, Duration::from_secs(8)))?;
        report.begin_login_succeeded = true;
        report.last_ts_state = Some(status_label(login.state));
        let mut url = login.auth_url;
        let url_deadline = Instant::now() + Duration::from_secs(20);
        while url.is_none() && Instant::now() < url_deadline {
            std::thread::sleep(Duration::from_millis(100));
            let status = op(runtime.node_login_status(&ts, Duration::from_secs(5)))?;
            report.last_ts_state = Some(status_label(status.state));
            url = status.auth_url;
        }
        let url = url.ok_or("login_url_missing")?;
        std::fs::write(input.exchange.join("auth-url"), url.as_str())
            .map_err(|_| "auth_exchange_failed")?;
        let until = Instant::now() + Duration::from_secs(30);
        while !input.exchange.join("auth-complete").is_file() && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(50));
        }
        let _ = std::fs::remove_file(input.exchange.join("auth-url"));
        if !input.exchange.join("auth-complete").is_file() {
            return Err("auth_exchange_timeout");
        }
        while Instant::now() < until {
            let status = op(runtime.node_login_status(&ts, Duration::from_secs(5)))?;
            report.last_ts_state = Some(status_label(status.state));
            if status.state == NodeStatus::Running {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        if op(runtime.node_login_status(&ts, Duration::from_secs(5)))?.state != NodeStatus::Running
        {
            return Err("ts_not_running");
        }
        let exec = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .map_err(|_| "executor_failed")?;
        exec.block_on(run(&input, runtime.clone(), et.clone(), ts.clone(), report))
    })();
    let et_done = report.et_stopped || stop(&runtime, &et);
    let ts_done = report.ts_stopped || stop(&runtime, &ts);
    let drain_deadline = Instant::now() + Duration::from_secs(5);
    while runtime.reserved_streams() != 0 && Instant::now() < drain_deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    report.reserved_nodes = runtime.reserved_nodes();
    report.reserved_streams = runtime.reserved_streams();
    report.cleanup =
        et_done && ts_done && report.reserved_nodes == 0 && report.reserved_streams == 0;
    if !report.cleanup {
        return Err("cleanup_failed");
    }
    result
}
fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        std::process::exit(2);
    }
    let mut bytes = std::fs::read(&args[1]).unwrap_or_default();
    let parsed = serde_json::from_slice::<Input>(&bytes);
    bytes.zeroize();
    let Ok(input) = parsed else {
        std::process::exit(2);
    };
    let mut report = Report::default();
    match execute(input, &mut report) {
        Ok(()) => report.passed = true,
        Err(code) => report.error = Some(code),
    }
    if std::fs::write(&args[2], serde_json::to_vec_pretty(&report).unwrap()).is_err() {
        std::process::exit(2);
    }
    if !report.passed {
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn observer_diagnostics_keep_only_fixed_error_and_stage_labels() {
        assert_eq!(observer_error("socket_unavailable"), "socket_unavailable");
        assert_eq!(observer_error("sensitive input"), "other_observer_error");
        assert_eq!(observer_stage("snapshot-received"), "snapshot-received");
        assert_eq!(observer_stage("sensitive input"), "other");
    }

    #[test]
    fn explicit_login_waits_for_needs_login() {
        for state in [
            NodeStatus::Starting,
            NodeStatus::EngineStarted,
            NodeStatus::Running,
        ] {
            assert!(!ready_for_explicit_login(&LoginStatus {
                state,
                auth_url: None
            }));
        }
        assert!(ready_for_explicit_login(&LoginStatus {
            state: NodeStatus::NeedsLogin,
            auth_url: None
        }));
    }

    #[test]
    fn harness_timeout_is_not_a_product_rejection() {
        let exec = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        exec.block_on(async {
            let elapsed = tokio::time::timeout(
                Duration::from_millis(1),
                std::future::pending::<Result<(), ()>>(),
            )
            .await;
            assert!(!explicit_dial_error(elapsed));
            assert!(explicit_dial_error::<(), ()>(Ok(Err(()))));
            assert!(!explicit_dial_error::<(), ()>(Ok(Ok(()))));
        });
    }

    #[test]
    fn rejected_unknown_and_stale_are_never_counted_as_accepted() {
        assert!(!accepted(Ok(SendOutcome::Rejected), 3));
        assert!(!accepted(Ok(SendOutcome::Unknown), 3));
        assert!(!accepted(Err("input_stale"), 3));
    }
}
