//! CI-only entry point for self-created loopback fixtures, never user credential discovery.
use herdr_readonly_transport::{Audit, CONFIG_LIMIT, Cancellation, RemoteConfig, read_once};
use serde_json::json;
use std::{
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
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
// Observe succeeds only after every requested round returned cancelled. Expose that
// cancellation evidence without reporting an unsuccessful round as a success.
fn reported_error(case: &str, result: &Result<(), &'static str>) -> Option<&'static str> {
    if case.starts_with("observe-") && result.is_ok() {
        Some("cancelled")
    } else {
        result.as_ref().err().copied()
    }
}
#[cfg(test)]
mod report_tests {
    use super::reported_error;
    #[test]
    fn reports_active_cancel_only_for_successful_observe_rounds() {
        assert_eq!(
            reported_error("observe-positive", &Ok(())),
            Some("cancelled")
        );
        assert_eq!(
            reported_error("observe-reconnect", &Ok(())),
            Some("cancelled")
        );
        assert_eq!(
            reported_error("observe-reconnect", &Err("observe_failed")),
            Some("observe_failed")
        );
        assert_eq!(reported_error("positive", &Ok(())), None);
    }
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
        || ![
            "positive",
            "wrong-pin",
            "missing-session",
            "cancel",
            "observe-positive",
            "observe-cancel",
            "observe-reconnect",
        ]
        .contains(&args[3].as_str())
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
    #[derive(Default)]
    struct Metrics {
        pane_count: usize,
        frame_count: usize,
        delta_frames: usize,
        last_seq: Option<u64>,
        connection_count: usize,
        buffer_high_water_bytes: usize,
    }
    let metrics = Arc::new(Mutex::new(Metrics::default()));
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
        if case.starts_with("observe-") {
            let rounds = if case == "observe-reconnect" { 2 } else { 1 };
            for _ in 0..rounds {
                let round_cancel = Cancellation::default();
                let stopper = round_cancel.clone();
                let selected = config.pane_id.clone();
                let select_metrics = metrics.clone();
                let frame_metrics = metrics.clone();
                let count = Arc::new(Mutex::new((0usize, 0usize)));
                let round_count = count.clone();
                metrics.lock().unwrap().connection_count += 1;
                let case_name = case.as_str();
                let outcome = tokio::time::timeout(
                    std::time::Duration::from_secs(30),
                    herdr_readonly_transport::observe(
                        config.clone(),
                        round_cancel,
                        audit.clone(),
                        |_| {},
                        move |panes| {
                            let selected = selected.clone();
                            let m = select_metrics.clone();
                            async move {
                                m.lock().unwrap().pane_count = panes.len();
                                if panes.iter().any(|p| p.pane_id == selected) {
                                    Ok(selected)
                                } else {
                                    Err("pane_missing")
                                }
                            }
                        },
                        move |frame| {
                            let mut m = frame_metrics.lock().unwrap();
                            let mut round = round_count.lock().unwrap();
                            m.frame_count += 1;
                            round.0 += 1;
                            if !frame.full {
                                m.delta_frames += 1;
                                round.1 += 1;
                            }
                            m.last_seq = Some(frame.seq);
                            m.buffer_high_water_bytes =
                                m.buffer_high_water_bytes.max(frame.buffer_high_water_bytes);
                            if (case_name == "observe-cancel" && round.0 >= 1)
                                || (case_name == "observe-positive" && round.0 >= 3 && round.1 >= 1)
                                || (case_name == "observe-reconnect"
                                    && round.0 >= 2
                                    && round.1 >= 1)
                            {
                                stopper.cancel();
                            }
                            async { Ok(()) }
                        },
                    ),
                )
                .await;
                if outcome != Ok(Err("cancelled")) {
                    return Err("observe_failed");
                }
            }
            return Ok(());
        }
        let canceller = cancel.clone();
        read_once(config, cancel, audit.clone(), |stage| {
            if case == "cancel" && stage == "snapshot-received" {
                canceller.cancel();
            }
        })
        .await
        .map(|_| ())
    }
    .await;
    let a = audit.snapshot();
    let error = result.as_ref().err().copied();
    let passed = match case.as_str() {
        "observe-positive" | "observe-cancel" | "observe-reconnect" => {
            result.is_ok()
                && a.host_key_matched
                && a.auth_started
                && a.snapshot_received
                && a.full_frame_received
        }
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
    let m = metrics.lock().unwrap();
    let report_error = reported_error(case, &result);
    let report = json!({"paneCount":m.pane_count,"frameCount":m.frame_count,"deltaFrames":m.delta_frames,"lastSeq":m.last_seq,"connectionCount":m.connection_count,"bufferHighWaterBytes":m.buffer_high_water_bytes,"status":if passed{"passed"}else{"failed"},"case":case,"hostKeyChecked":a.host_key_checked,"hostKeyMatched":a.host_key_matched,"authStarted":a.auth_started,"snapshotReceived":a.snapshot_received,"fullFrameReceived":a.full_frame_received,"generation":1,"lateEventsIgnored":0,"errorCode":report_error});
    fs::write(
        output,
        serde_json::to_vec_pretty(&report).map_err(|_| "report_failed")?,
    )
    .map_err(|_| "report_failed")?;
    // Never log config, terminal bytes, server errors or private material.
    if passed { Ok(()) } else { Err("case_failed") }
}
