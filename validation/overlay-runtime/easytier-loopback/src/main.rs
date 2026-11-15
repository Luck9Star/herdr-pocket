//! Opt-in fixture client. All network/SSH identities are supplied by the isolated
//! runner. This calls the product runtime and SSH path, with no synthetic backend.
use herdr_overlay_runtime_probe::{
    Evidence, Failure, OverlayRuntime, ProfileKey, Provider,
    nodes::{NodeSpec, SecretConfig, SecureConfigSource},
};
use herdr_readonly_transport::{
    Audit, AuditSnapshot, Cancellation, RemoteConfig, overlay::OverlayDialer,
    read_once_with_dialer, transport::Dialer,
};
use serde::{Deserialize, Serialize};
use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};
use zeroize::Zeroize;

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
enum Case {
    Positive,
    WrongPin,
    NoRoute,
    PeerGone,
}
impl Case {
    fn label(self) -> &'static str {
        match self {
            Self::Positive => "positive",
            Self::WrongPin => "wrong-pin",
            Self::NoRoute => "no-route",
            Self::PeerGone => "peer-gone",
        }
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Input {
    case: Case,
    network: String,
    native_config: String,
    overlay_host: String,
    overlay_port: u16,
    peer_control: std::path::PathBuf,
    remote: RemoteConfig,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Report {
    schema_version: u8,
    case: Case,
    passed: bool,
    error_code: Option<&'static str>,
    transport_error_code: Option<&'static str>,
    node_started: bool,
    candidate_abi: bool,
    ssh_banner_via_overlay: bool,
    banner_connections: usize,
    peer_stopped_before_attempt: bool,
    attempt_checkpoint_reached: bool,
    audit: AuditSnapshot,
    frame_marker_present: bool,
    frame_columns: u16,
    frame_rows: u16,
    native_stop_completed: bool,
    reserved_nodes_after_cleanup: usize,
    reserved_streams_after_cleanup: usize,
}

struct OnceSource(Mutex<Option<SecretConfig>>);
impl SecureConfigSource for OnceSource {
    fn load(&self, _: &NodeSpec) -> Result<SecretConfig, Failure> {
        self.0
            .lock()
            .map_err(|_| Failure::IdentityUnavailable)?
            .take()
            .ok_or(Failure::IdentityUnavailable)
    }
}

async fn drained(runtime: &OverlayRuntime) -> bool {
    let until = Instant::now() + Duration::from_secs(5);
    while runtime.reserved_streams() != 0 && Instant::now() < until {
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    runtime.reserved_streams() == 0
}

// Read-only readiness attempts carry no authentication or application input.
// A successful banner proves bytes crossed the real OverlayDialer before SSH.
async fn banner(dialer: &OverlayDialer, host: &str, port: u16, connections: &mut usize) -> bool {
    let until = Instant::now() + Duration::from_secs(25);
    while Instant::now() < until {
        if let Ok(stream) = dialer
            .dial(host.to_owned(), port, Cancellation::default())
            .await
        {
            *connections += 1;
            let mut line = Vec::new();
            let mut reader = BufReader::new(stream.take(256));
            if matches!(
                tokio::time::timeout(Duration::from_secs(2), reader.read_until(b'\n', &mut line))
                    .await,
                Ok(Ok(_))
            ) && line.starts_with(b"SSH-2.0-")
            {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    false
}

async fn run_case(
    input: Input,
    runtime: &OverlayRuntime,
    dialer: &OverlayDialer,
    report: &mut Report,
) -> Result<(), &'static str> {
    report.ssh_banner_via_overlay = banner(
        dialer,
        &input.overlay_host,
        input.overlay_port,
        &mut report.banner_connections,
    )
    .await;
    if !report.ssh_banner_via_overlay {
        return Err("overlay_banner_missing");
    }
    if !drained(runtime).await {
        return Err("banner_stream_cleanup_failed");
    }
    // The independent runner samples sshd after readiness, then permits exactly
    // this target attempt. Native successful opens are not server accept counts.
    std::fs::write(
        input.peer_control.join("client-ready.tmp"),
        input.case.label(),
    )
    .map_err(|_| "client_checkpoint_failed")?;
    std::fs::rename(
        input.peer_control.join("client-ready.tmp"),
        input.peer_control.join("client-ready"),
    )
    .map_err(|_| "client_checkpoint_failed")?;
    report.attempt_checkpoint_reached = true;
    let until = Instant::now() + Duration::from_secs(8);
    while std::fs::read_to_string(input.peer_control.join("continue-client"))
        .ok()
        .as_deref()
        != Some(input.case.label())
        && Instant::now() < until
    {
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    if std::fs::read_to_string(input.peer_control.join("continue-client"))
        .ok()
        .as_deref()
        != Some(input.case.label())
    {
        return Err("client_permission_missing");
    }
    if matches!(input.case, Case::PeerGone) {
        std::fs::write(input.peer_control.join("stop-peer"), b"stop")
            .map_err(|_| "peer_stop_request_failed")?;
        let until = Instant::now() + Duration::from_secs(8);
        while !input.peer_control.join("peer-stopped").is_file() && Instant::now() < until {
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        report.peer_stopped_before_attempt = input.peer_control.join("peer-stopped").is_file();
        if !report.peer_stopped_before_attempt {
            return Err("peer_stop_not_confirmed");
        }
    }
    let audit = Arc::new(Audit::default());
    let result = read_once_with_dialer(
        input.remote,
        Cancellation::default(),
        audit.clone(),
        |_| {},
        dialer,
    )
    .await;
    report.audit = audit.snapshot();
    report.transport_error_code = result.as_ref().err().copied();
    match (input.case, result) {
        (Case::Positive, Ok(frame)) => {
            report.frame_marker_present = frame
                .bytes
                .windows(b"herdr-pocket".len())
                .any(|bytes| bytes == b"herdr-pocket");
            report.frame_columns = frame.columns;
            report.frame_rows = frame.rows;
            if !report.frame_marker_present || !report.audit.full_frame_received {
                return Err("real_herdr_frame_missing");
            }
        }
        (Case::WrongPin, Err("host_key_mismatch"))
            if report.audit.host_key_checked
                && !report.audit.host_key_matched
                && !report.audit.auth_started => {}
        (Case::NoRoute | Case::PeerGone, Err(code))
            if matches!(
                code,
                "overlay_transport_failed" | "handshake_failed" | "timeout"
            ) && !report.audit.host_key_checked
                && !report.audit.auth_started => {}
        (_, Err(_)) => return Err("unexpected_transport_failure"),
        _ => return Err("negative_case_did_not_reject"),
    }
    if !drained(runtime).await {
        return Err("ssh_stream_cleanup_failed");
    }
    Ok(())
}

fn execute(mut input: Input, report: &mut Report) -> Result<(), &'static str> {
    if !cfg!(feature = "real-easytier") {
        return Err("real_candidate_feature_required");
    }
    let executor = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .map_err(|_| "test_executor_failed")?;
    let runtime = Arc::new(OverlayRuntime::new());
    let key = ProfileKey {
        provider: Provider::EasyTier,
        id: "isolated-easytier".into(),
    };
    let spec = NodeSpec {
        profile: key.clone(),
        revision: 1,
        profile_revision: 1,
        network: input.network.clone(),
        identity_ref: "temporary-in-memory-config".into(),
    };
    let source = Arc::new(OnceSource(Mutex::new(Some(
        SecretConfig::from_bytes(std::mem::take(&mut input.native_config).into_bytes())
            .map_err(|_| "invalid_native_config")?,
    ))));
    let node = match runtime
        .start_easytier_profile(spec, Some(source), Duration::from_secs(8))
        .and_then(|op| op.wait(Duration::from_secs(12)))
    {
        Ok(node) => node,
        Err(_) => {
            if let Ok(op) = runtime.retry_node_cleanup(&key, 1, Duration::from_secs(5)) {
                let _ = op.wait(Duration::from_secs(8));
            }
            report.reserved_nodes_after_cleanup = runtime.reserved_nodes();
            report.reserved_streams_after_cleanup = runtime.reserved_streams();
            return Err("native_node_start_failed");
        }
    };
    report.node_started = true;
    report.candidate_abi = node.evidence() == Evidence::CandidateAbiOnly;
    let result = match OverlayDialer::new(runtime.clone(), node.clone(), Duration::from_secs(3)) {
        Ok(dialer) => executor.block_on(run_case(input, &runtime, &dialer, report)),
        Err(_) => Err("product_dialer_create_failed"),
    };
    report.native_stop_completed = runtime
        .stop_node(&node, Duration::from_secs(5))
        .and_then(|op| op.wait(Duration::from_secs(8)))
        .is_ok();
    report.reserved_nodes_after_cleanup = runtime.reserved_nodes();
    report.reserved_streams_after_cleanup = runtime.reserved_streams();
    if !report.native_stop_completed
        || report.reserved_nodes_after_cleanup != 0
        || report.reserved_streams_after_cleanup != 0
    {
        return Err("native_cleanup_failed");
    }
    result
}

fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        std::process::exit(2);
    }
    let mut bytes = std::fs::read(Path::new(&args[1])).unwrap_or_default();
    let input = serde_json::from_slice::<Input>(&bytes);
    bytes.zeroize();
    let Ok(input) = input else {
        std::process::exit(2);
    };
    let mut report = Report {
        schema_version: 1,
        case: input.case,
        passed: false,
        error_code: None,
        transport_error_code: None,
        node_started: false,
        candidate_abi: false,
        ssh_banner_via_overlay: false,
        banner_connections: 0,
        peer_stopped_before_attempt: false,
        attempt_checkpoint_reached: false,
        audit: Audit::default().snapshot(),
        frame_marker_present: false,
        frame_columns: 0,
        frame_rows: 0,
        native_stop_completed: false,
        reserved_nodes_after_cleanup: 0,
        reserved_streams_after_cleanup: 0,
    };
    match execute(input, &mut report) {
        Ok(()) => report.passed = true,
        Err(code) => report.error_code = Some(code),
    }
    let encoded = serde_json::to_vec_pretty(&report).unwrap();
    if std::fs::write(Path::new(&args[2]), encoded).is_err() {
        std::process::exit(2);
    }
    if !report.passed {
        std::process::exit(1);
    }
}
