//! Loopback-only peer for the Flutter M3-05 Widget test. No host shell runs.
use base64ct::{Base64, Encoding};
use russh::{
    Channel, ChannelId,
    keys::{PublicKey, load_secret_key},
    server::{self, Server},
};
use serde_json::{Value, json};
use std::{
    env,
    fs::{File, OpenOptions},
    io::Write,
    net::SocketAddr,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    time::Duration,
};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};

const SOCKET: &str = "/tmp/m305-sim/herdr/sessions/m305/herdr.sock";
const A: (&str, &str) = ("w1:p1", "term_a001");
const B: (&str, &str) = ("w1:p2", "term_b002");
const INPUT: &[u8] = b"M3-one";

struct Audit {
    events: Mutex<File>,
    connections: AtomicUsize,
    dropped_receipt: AtomicBool,
}
impl Audit {
    fn record(&self, event: Value) {
        self.events
            .lock()
            .unwrap()
            .write_all(format!("{event}\n").as_bytes())
            .unwrap();
    }
}

struct Connection {
    id: usize,
    audit: Arc<Audit>,
}
impl Drop for Connection {
    fn drop(&mut self) {
        self.audit
            .record(json!({"kind":"closed","connection":self.id}));
    }
}

struct Peer {
    client_key: PublicKey,
    audit: Arc<Audit>,
    connection: Option<Connection>,
}
impl Peer {
    fn connection(&self) -> usize {
        self.connection.as_ref().unwrap().id
    }
}
impl Server for Peer {
    type Handler = Self;
    fn new_client(&mut self, _: Option<SocketAddr>) -> Self {
        let id = self.audit.connections.fetch_add(1, Ordering::SeqCst) + 1;
        self.audit
            .record(json!({"kind":"connection","connection":id}));
        Self {
            client_key: self.client_key.clone(),
            audit: self.audit.clone(),
            connection: Some(Connection {
                id,
                audit: self.audit.clone(),
            }),
        }
    }
}
impl server::Handler for Peer {
    type Error = russh::Error;
    async fn auth_publickey(
        &mut self,
        user: &str,
        key: server::VerifiedPublicKey<'_>,
    ) -> Result<server::Auth, Self::Error> {
        if user != "fixture" || key.public_key.key_data() != self.client_key.key_data() {
            return Ok(server::Auth::reject());
        }
        self.audit
            .record(json!({"kind":"fixture_auth","connection":self.connection()}));
        Ok(server::Auth::Accept)
    }
    async fn channel_open_session(
        &mut self,
        _: Channel<server::Msg>,
        reply: server::ChannelOpenHandle,
        _: &mut server::Session,
    ) -> Result<(), Self::Error> {
        reply.accept().await;
        Ok(())
    }
    async fn exec_request(
        &mut self,
        channel: ChannelId,
        command: &[u8],
        session: &mut server::Session,
    ) -> Result<(), Self::Error> {
        // Serve only the fixed observe command on either fixture terminal.
        // The command is matched against local literals and is never executed.
        let terminal = [A.1, B.1].into_iter().find(|terminal| {
            command
                == format!(
                    "exec /usr/bin/env 'XDG_CONFIG_HOME=/tmp/m305-sim' '/tmp/m305-sim/herdr' \
                 --session 'm305' terminal session observe '{terminal}' --cols 80 --rows 24"
                )
                .as_bytes()
        });
        let Some(terminal) = terminal else {
            session.channel_failure(channel)?;
            return Ok(());
        };
        self.audit
            .record(json!({"kind":"observe","connection":self.connection(),"terminal":terminal}));
        session.channel_success(channel)?;
        let frame = |seq, full, text| {
            format!(
                "{}\n",
                json!({
                    "type":"terminal.frame","seq":seq,"full":full,"encoding":"ansi",
                    "width":80,"height":24,"bytes":Base64::encode_string(text)
                })
            )
        };
        session.data(channel, frame(1, true, terminal.as_bytes()).into_bytes())?;
        session.data(channel, frame(2, false, b"\r\nFIXTURE ONLINE").into_bytes())?;
        Ok(())
    }
    async fn channel_open_direct_streamlocal(
        &mut self,
        channel: Channel<server::Msg>,
        socket: &str,
        reply: server::ChannelOpenHandle,
        _: &mut server::Session,
    ) -> Result<(), Self::Error> {
        if socket != SOCKET {
            reply
                .reject(russh::ChannelOpenFailure::AdministrativelyProhibited)
                .await;
            return Ok(());
        }
        reply.accept().await;
        let audit = self.audit.clone();
        let connection = self.connection();
        tokio::spawn(async move {
            let mut stream = channel.into_stream();
            let mut line = Vec::new();
            let bounded = (&mut stream).take(8192);
            if BufReader::new(bounded)
                .read_until(b'\n', &mut line)
                .await
                .is_err()
            {
                return;
            }
            let Ok(request) = serde_json::from_slice::<Value>(&line) else {
                return;
            };
            let id = &request["id"];
            let method = request["method"].as_str().unwrap_or_default();
            let reply = match method {
                "session.snapshot" => {
                    json!({"id":id,"result":{"type":"session_snapshot","snapshot":{
                        "version":"0.9.5","protocol":22,"panes":[
                            {"pane_id":A.0,"terminal_id":A.1},{"pane_id":B.0,"terminal_id":B.1}
                        ]
                    }}})
                }
                "pocket.input.capabilities" => {
                    json!({"id":id,"result":{"type":"pocket_input_capabilities",
                        "version":1,"protocol":22,"atomic_terminal_guard":true,"raw_bytes":true,"max_input_bytes":4096
                    }})
                }
                "events.subscribe" => json!({"id":id,"result":{"type":"subscription_started"}}),
                "pocket.input.send" => {
                    let params = &request["params"];
                    let pane = params["pane_id"].as_str().unwrap_or_default();
                    let terminal = params["expected_terminal_id"].as_str().unwrap_or_default();
                    let bytes =
                        Base64::decode_vec(params["bytes_base64"].as_str().unwrap_or_default())
                            .ok();
                    let matched = (pane, terminal) == A && bytes.as_deref() == Some(INPUT);
                    // The private exchange records only a temporary request
                    // ID and the exact comparison result.
                    audit.record(json!({"kind":"input","connection":connection,"request":id,
                        "exactFixtureInput":matched,"size":bytes.as_ref().map(Vec::len)
                    }));
                    if !matched {
                        json!({"id":id,"error":{"code":"pocket_input_rejected","message":"fixture target mismatch"}})
                    } else if !audit.dropped_receipt.swap(true, Ordering::SeqCst) {
                        audit.record(
                            json!({"kind":"receipt_dropped","connection":connection,"request":id}),
                        );
                        let _ = stream.shutdown().await;
                        return;
                    } else {
                        // A replay would remain visible in the audit and is
                        // not masked by injecting a second lost receipt.
                        json!({"id":id,"result":{"type":"pocket_input_accepted","pane_id":pane,
                            "terminal_id":terminal,"accepted_bytes":INPUT.len()
                        }})
                    }
                }
                _ => {
                    json!({"id":id,"error":{"code":"unknown_method","message":"fixture method unavailable"}})
                }
            };
            if stream
                .write_all(format!("{reply}\n").as_bytes())
                .await
                .is_ok()
                && method == "events.subscribe"
            {
                // Keep the dashboard subscription open until the client closes it.
                let _ = stream.read(&mut [0u8; 1]).await;
            }
            let _ = stream.shutdown().await;
        });
        Ok(())
    }
}

#[tokio::main]
async fn main() {
    let args: Vec<_> = env::args_os().collect();
    assert_eq!(
        args.len(),
        4,
        "host key, client public key, new private audit file"
    );
    let key = load_secret_key(&args[1], None).unwrap();
    let client_key = russh::keys::load_public_key(&args[2]).unwrap();
    let events = OpenOptions::new()
        .append(true)
        .create_new(true)
        .open(&args[3])
        .unwrap();
    let audit = Arc::new(Audit {
        events: Mutex::new(events),
        connections: AtomicUsize::new(0),
        dropped_receipt: AtomicBool::new(false),
    });
    let mut peer = Peer {
        client_key,
        audit,
        connection: None,
    };
    let config = Arc::new(server::Config {
        keys: vec![key],
        auth_rejection_time: Duration::ZERO,
        auth_rejection_time_initial: Some(Duration::ZERO),
        ..Default::default()
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    println!("{}", listener.local_addr().unwrap().port());
    peer.run_on_socket(config, &listener).await.unwrap();
}
