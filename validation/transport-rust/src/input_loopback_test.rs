//! Loopback-only SSH fixture: exercise production observe and LiveInput, never host credentials.
use super::*;
use crate::input::{LiveInput, SendOutcome};
use russh::{Channel, ChannelId, server};
use std::{
    path::PathBuf,
    process::Command,
    sync::atomic::{AtomicUsize, Ordering},
};
use tokio::sync::mpsc;

struct Temp(PathBuf);
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone)]
struct Fixture {
    writes: Arc<Mutex<Vec<(String, Vec<u8>)>>>,
    connections: Arc<AtomicUsize>,
    key: PublicKey,
    corrupt_marker: Option<PathBuf>,
}
impl server::Server for Fixture {
    type Handler = Self;
    fn new_client(&mut self, _: Option<std::net::SocketAddr>) -> Self {
        self.connections.fetch_add(1, Ordering::SeqCst);
        self.clone()
    }
}
impl server::Handler for Fixture {
    type Error = russh::Error;
    async fn auth_publickey(
        &mut self,
        user: &str,
        key: server::VerifiedPublicKey<'_>,
    ) -> std::result::Result<server::Auth, Self::Error> {
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
        session.channel_success(channel)?;
        session.data(channel, b"{\"type\":\"terminal.frame\",\"seq\":1,\"full\":true,\"encoding\":\"ansi\",\"width\":80,\"height\":24,\"bytes\":\"eA==\"}\n".to_vec())?;
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
        let writes = self.writes.clone();
        let corrupt_marker = self.corrupt_marker.clone();
        tokio::spawn(async move {
            let mut stream = channel.into_stream();
            let mut line = Vec::new();
            if BufReader::new(&mut stream)
                .read_until(b'\n', &mut line)
                .await
                .is_err()
            {
                return;
            }
            let Ok(req) = serde_json::from_slice::<Value>(&line) else {
                return;
            };
            let method = req["method"].as_str().unwrap_or("");
            let response = match method {
                "session.snapshot" => Some(
                    serde_json::json!({"id":"pocket-readonly","result":{"type":"session_snapshot","snapshot":{"version":"0.9.5","protocol":22,"panes":[{"pane_id":"w1:p1","terminal_id":"term_abc"},{"pane_id":"w1:p2","terminal_id":"term_def"}]}}}),
                ),
                "pocket.input.capabilities" => Some(
                    serde_json::json!({"id":req["id"],"result":{"type":"pocket_input_capabilities","version":1,"protocol":22,"atomic_terminal_guard":true,"raw_bytes":true,"max_input_bytes":4096}}),
                ),
                "pocket.input.send" => {
                    let bytes = Base64::decode_vec(req["params"]["bytes_base64"].as_str().unwrap())
                        .unwrap();
                    writes
                        .lock()
                        .unwrap()
                        .push((req["id"].as_str().unwrap().to_string(), bytes.clone()));
                    if let Some(path) = corrupt_marker {
                        assert!(path.is_file());
                        std::fs::write(path, b"{").unwrap();
                        Some(
                            serde_json::json!({"id":req["id"],"result":{"type":"pocket_input_accepted","pane_id":req["params"]["pane_id"],"terminal_id":req["params"]["expected_terminal_id"],"accepted_bytes":bytes.len()}}),
                        )
                    } else {
                        None // The server recorded the write, then dropped its reply.
                    }
                }
                _ => None,
            };
            if let Some(response) = response {
                let mut bytes = serde_json::to_vec(&response).unwrap();
                bytes.push(b'\n');
                let _ = stream.write_all(&bytes).await;
            }
            let _ = stream.shutdown().await;
        });
        Ok(())
    }
}

async fn open_view(
    config: RemoteConfig,
    recovery: recovery::SharedRecovery,
    pane: &'static str,
) -> (
    Arc<LiveInput>,
    Cancellation,
    tokio::task::JoinHandle<Result<()>>,
) {
    let (tx, mut rx) = mpsc::unbounded_channel();
    let cancel = Cancellation::default();
    let c = cancel.clone();
    let task = tokio::spawn(observe_interactive(
        config,
        None,
        c,
        Arc::new(Audit::default()),
        |_| {},
        move |_| async move { Ok(pane.to_string()) },
        |frame| async move {
            assert!(frame.full);
            Ok(())
        },
        InputHooks {
            recovery,
            ready: Arc::new(move |input| {
                tx.send(input).unwrap();
            }),
        },
    ));
    let input = match tokio::time::timeout(Duration::from_secs(5), rx.recv())
        .await
        .unwrap()
    {
        Some(input) => input,
        None => panic!("observe ended before input readiness: {:?}", task.await),
    };
    (input, cancel, task)
}

#[tokio::test]
async fn dropped_receipt_survives_reconnect_requires_original_full_and_explicit_confirmation() {
    run_case(false).await;
}

#[tokio::test]
async fn matched_receipt_survives_corrupt_marker_but_input_remains_locked() {
    run_case(true).await;
}

async fn run_case(corrupt: bool) {
    use ring::rand::SecureRandom;
    use russh::server::Server as _;
    let mut nonce = [0u8; 16];
    ring::rand::SystemRandom::new().fill(&mut nonce).unwrap();
    let temp = Temp(std::env::temp_dir().join(format!(
        "herdr-loopback-{}",
        nonce.iter().map(|v| format!("{v:02x}")).collect::<String>()
    )));
    std::fs::create_dir(&temp.0).unwrap();
    let key_path = temp.0.join("fixture-key");
    assert!(
        Command::new("ssh-keygen")
            .arg("-q")
            .arg("-t")
            .arg("ed25519")
            .arg("-N")
            .arg("")
            .arg("-f")
            .arg(&key_path)
            .status()
            .unwrap()
            .success()
    );
    let pem = std::fs::read_to_string(&key_path).unwrap();
    let key = decode_secret_key(&pem, None).unwrap();
    let host_key = key
        .public_key()
        .to_openssh()
        .unwrap()
        .split_whitespace()
        .take(2)
        .collect::<Vec<_>>()
        .join(" ");
    let fixture_public = key.public_key().clone();
    let server_config = Arc::new(server::Config {
        keys: vec![key],
        auth_rejection_time: Duration::ZERO,
        auth_rejection_time_initial: Some(Duration::ZERO),
        ..Default::default()
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let writes = Arc::new(Mutex::new(Vec::new()));
    let connections = Arc::new(AtomicUsize::new(0));
    let mut fixture = Fixture {
        writes: writes.clone(),
        connections: connections.clone(),
        key: fixture_public,
        corrupt_marker: corrupt.then(|| temp.0.join("journal/pending.json")),
    };
    let server = tokio::spawn(async move {
        fixture
            .run_on_socket(server_config, &listener)
            .await
            .unwrap();
    });
    let config = RemoteConfig {
        schema_version: 1,
        host: "127.0.0.1".into(),
        port,
        username: "fixture".into(),
        expected_host_key: host_key,
        private_key_pem: pem,
        socket_path: "/tmp/herdr/sessions/fixture/herdr.sock".into(),
        herdr_path: "/fixture/herdr".into(),
        session: "fixture".into(),
        pane_id: "w1:p1".into(),
        review_confirmed: true,
        observe_canvas: Default::default(),
    };
    let dir = temp.0.join("journal");
    let recovery = recovery::Recovery::open(dir.clone());
    let (first, _, first_task) = open_view(config.clone(), recovery.clone(), "w1:p1").await;
    let epoch = first.set_mode("direct", true).unwrap();
    let result = first
        .send(epoch, b"fixture-secret-body".to_vec(), false)
        .await
        .unwrap();
    assert_eq!(writes.lock().unwrap().len(), 1);
    assert_eq!(writes.lock().unwrap()[0].1, b"fixture-secret-body");
    if corrupt {
        let SendOutcome::RecoveryLocked {
            receipt: Some(receipt),
        } = result
        else {
            panic!("missing matched receipt")
        };
        assert_eq!(receipt.request_id, writes.lock().unwrap()[0].0);
        assert_eq!(
            (
                receipt.pane_id.as_str(),
                receipt.terminal_id.as_str(),
                receipt.accepted_bytes
            ),
            ("w1:p1", "term_abc", b"fixture-secret-body".len())
        );
        assert_eq!(std::fs::read(dir.join("pending.json")).unwrap(), b"{");
        assert_eq!(recovery.status(), "unavailable");
        assert!(first.set_mode("observe", true).is_err());
        drop(first);
        drop(recovery);
        let _ = first_task.await;
        let reopened = recovery::Recovery::open(dir.clone());
        assert_eq!(reopened.status(), "unavailable");
        let (new, cancel, task) = open_view(config, reopened.clone(), "w1:p1").await;
        let observe = new.set_mode("observe", true).unwrap();
        assert!(new.acknowledge_unknown(observe).is_err());
        let direct = new.set_mode("direct", true).unwrap();
        assert_eq!(
            new.send(direct, b"must-not-send".to_vec(), false).await,
            Err("input_stale")
        );
        tokio::time::sleep(Duration::from_millis(150)).await;
        assert_eq!(writes.lock().unwrap().len(), 1);
        assert_eq!(std::fs::read(dir.join("pending.json")).unwrap(), b"{");
        cancel.cancel();
        drop(new);
        let _ = task.await;
        server.abort();
        return;
    }
    assert_eq!(result, SendOutcome::Unknown);
    let marker = std::fs::read_to_string(dir.join("pending.json")).unwrap();
    let marker_json: Value = serde_json::from_str(&marker).unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(marker_json["records"][0].as_str().unwrap()).unwrap()["request_id"],
        writes.lock().unwrap()[0].0
    );
    assert!(!marker.contains("fixture-secret-body"));
    assert!(!marker.contains(&Base64::encode_string(b"fixture-secret-body")));
    assert!(first.set_mode("observe", true).is_err());
    drop(first);
    drop(recovery);
    let _ = first_task.await;
    let reopened = recovery::Recovery::open(dir.clone());
    assert_eq!(reopened.status(), "pending");
    let (wrong, cancel, wrong_task) = open_view(config.clone(), reopened.clone(), "w1:p2").await;
    let wrong_epoch = wrong.set_mode("observe", true).unwrap();
    assert_eq!(
        wrong.acknowledge_unknown(wrong_epoch),
        Err("input_original_target_required")
    );
    assert_eq!(
        std::fs::read_to_string(dir.join("pending.json")).unwrap(),
        marker
    );
    cancel.cancel();
    drop(wrong);
    let _ = wrong_task.await;
    let (original, cancel, original_task) = open_view(config, reopened.clone(), "w1:p1").await;
    let direct = original.set_mode("direct", true).unwrap();
    assert_eq!(
        original
            .send(direct, b"must-not-send".to_vec(), false)
            .await,
        Err("input_stale")
    );
    let observe = original.set_mode("observe", true).unwrap();
    assert_eq!(reopened.status(), "pending");
    original.acknowledge_unknown(observe).unwrap();
    assert_eq!(reopened.status(), "ready");
    assert_eq!(original.acknowledge_unknown(observe), Err("input_stale"));
    let cleared: Value =
        serde_json::from_slice(&std::fs::read(dir.join("pending.json")).unwrap()).unwrap();
    assert_eq!(cleared["version"], 2);
    assert_eq!(cleared["records"], serde_json::json!([]));
    tokio::time::sleep(Duration::from_millis(150)).await;
    assert_eq!(writes.lock().unwrap().len(), 1);
    assert!(connections.load(Ordering::SeqCst) >= 3);
    cancel.cancel();
    drop(original);
    let _ = original_task.await;
    server.abort();
}
