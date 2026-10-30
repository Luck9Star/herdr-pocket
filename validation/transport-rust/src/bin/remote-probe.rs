//! CI-only entry point for self-created loopback fixtures, never user credential discovery.
use herdr_readonly_transport::{Audit, CONFIG_LIMIT, Cancellation, RemoteConfig, read_once};
use serde_json::json;
use std::{
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
};
use zeroize::Zeroize;

fn temporary_path(value: &str) -> Result<PathBuf, &'static str> {
    let path = Path::new(value);
    if !path.is_absolute() || path.file_name().is_none() {
        return Err("invalid_fixture_path");
    }
    let parent = path
        .parent()
        .ok_or("invalid_fixture_path")?
        .canonicalize()
        .map_err(|_| "invalid_fixture_path")?;
    let mut roots = vec![
        std::env::temp_dir()
            .canonicalize()
            .map_err(|_| "invalid_fixture_path")?,
    ];
    if let Some(root) = std::env::var_os("RUNNER_TEMP") {
        if let Ok(root) = PathBuf::from(root).canonicalize() {
            roots.push(root);
        }
    }
    if !roots.iter().any(|r| parent.starts_with(r))
        || fs::symlink_metadata(path).is_ok_and(|m| m.file_type().is_symlink())
    {
        return Err("invalid_fixture_path");
    }
    Ok(parent.join(path.file_name().unwrap()))
}
#[tokio::main]
async fn main() {
    if run().await.is_err() {
        eprintln!("remote-probe failed; inspect safe report if present");
        std::process::exit(1)
    }
}
async fn run() -> Result<(), &'static str> {
    if std::env::var("GITHUB_ACTIONS").as_deref() != Ok("true") {
        return Err("ci_only");
    }
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 6
        || args[0] != "--config"
        || args[2] != "--case"
        || args[4] != "--output"
        || !["positive", "wrong-pin", "missing-session", "cancel"].contains(&args[3].as_str())
    {
        return Err("invalid_arguments");
    }
    let input = temporary_path(&args[1])?;
    let output = temporary_path(&args[5])?;
    if input == output {
        return Err("invalid_fixture_path");
    }
    let audit = Arc::new(Audit::default());
    let cancel = Cancellation::default();
    let case = &args[3];
    let result = async {
        let mut bytes = Vec::new();
        File::open(input)
            .map_err(|_| "config_unavailable")?
            .take((CONFIG_LIMIT + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| "config_unavailable")?;
        let config = RemoteConfig::from_json(&bytes);
        bytes.zeroize();
        let config = config?;
        if config.host != "127.0.0.1" || config.port < 1024 {
            return Err("fixture_loopback_required");
        }
        let canceller = cancel.clone();
        read_once(config, cancel, audit.clone(), |stage| {
            if case == "cancel" && stage == "snapshot-received" {
                canceller.cancel();
            }
        })
        .await
    }
    .await;
    let a = audit.snapshot();
    let error = result.as_ref().err().copied();
    let passed = match case.as_str() {
        "positive" => {
            result.is_ok()
                && a.host_key_checked
                && a.host_key_matched
                && a.auth_started
                && a.snapshot_received
                && a.full_frame_received
        }
        "wrong-pin" => {
            error == Some("host_key_mismatch")
                && a.host_key_checked
                && !a.host_key_matched
                && !a.auth_started
                && !a.snapshot_received
                && !a.full_frame_received
        }
        "missing-session" => {
            matches!(
                error,
                Some("session_mismatch" | "socket_unavailable" | "pane_missing" | "observe_failed")
            ) && a.host_key_matched
                && a.auth_started
                && !a.full_frame_received
        }
        "cancel" => {
            error == Some("cancelled")
                && a.host_key_checked
                && a.host_key_matched
                && a.auth_started
                && a.snapshot_received
                && !a.full_frame_received
        }
        _ => false,
    };
    let report = json!({"status":if passed{"passed"}else{"failed"},"case":case,"hostKeyChecked":a.host_key_checked,"hostKeyMatched":a.host_key_matched,"authStarted":a.auth_started,"snapshotReceived":a.snapshot_received,"fullFrameReceived":a.full_frame_received,"generation":1,"lateEventsIgnored":0,"errorCode":error});
    fs::write(
        output,
        serde_json::to_vec_pretty(&report).map_err(|_| "report_failed")?,
    )
    .map_err(|_| "report_failed")?;
    // Never log config, terminal bytes, server errors or private material.
    if passed { Ok(()) } else { Err("case_failed") }
}
