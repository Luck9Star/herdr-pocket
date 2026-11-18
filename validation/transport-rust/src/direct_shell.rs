//! Standard SSH session + PTY + shell. Credentials exist only for this attempt.
use crate::*;
use tokio::sync::{mpsc, oneshot};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShellConfig {
    pub host: String,
    pub port: u16,
    pub username: String,
    pub expected_host_key: String,
    pub review_confirmed: bool,
    pub cols: u16,
    pub rows: u16,
    pub password: Option<String>,
    pub private_key_pem: Option<String>,
    pub private_key_passphrase: Option<String>,
}
impl Drop for ShellConfig {
    fn drop(&mut self) {
        self.password.zeroize();
        self.private_key_pem.zeroize();
        self.private_key_passphrase.zeroize();
    }
}
fn validate_endpoint(host: &str, port: u16) -> Result<()> {
    let valid = host.parse::<std::net::IpAddr>().is_ok()
        || host.split('.').all(|p| {
            !p.is_empty()
                && p.len() <= 63
                && !p.starts_with('-')
                && !p.ends_with('-')
                && p.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
        });
    if host.is_empty() || host.len() > 253 || !valid || port == 0 {
        return Err("invalid_endpoint");
    }
    Ok(())
}
pub fn validate_size(cols: u16, rows: u16) -> Result<()> {
    ObserveCanvas { cols, rows }.validate().map(|_| ())
}
impl ShellConfig {
    pub fn validate(&self) -> Result<PublicKey> {
        validate_endpoint(&self.host, self.port)?;
        validate_size(self.cols, self.rows)?;
        if !self.review_confirmed
            || self.username.is_empty()
            || self.username.len() > 128
            || self
                .username
                .chars()
                .any(|c| c.is_control() || c.is_whitespace())
            || self.password.is_some() == self.private_key_pem.is_some()
            || self
                .password
                .as_ref()
                .is_some_and(|v| v.is_empty() || v.len() > 16384)
            || self
                .private_key_pem
                .as_ref()
                .is_some_and(|v| v.is_empty() || v.len() > 32768)
            || self
                .private_key_passphrase
                .as_ref()
                .is_some_and(|v| v.len() > 16384)
            || self.private_key_pem.is_none() && self.private_key_passphrase.is_some()
        {
            return Err("invalid_shell_config");
        }
        if self.expected_host_key.split(' ').count() != 2
            || self.expected_host_key.len() > 4096
            || self.expected_host_key.contains(['\n', '\r', '\t'])
        {
            return Err("invalid_host_key");
        }
        let key =
            PublicKey::from_openssh(&self.expected_host_key).map_err(|_| "invalid_host_key")?;
        if key.to_openssh().map_err(|_| "invalid_host_key")? != self.expected_host_key {
            return Err("invalid_host_key");
        }
        Ok(key)
    }
}

#[derive(Clone, Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct HostKey {
    pub host: String,
    pub port: u16,
    pub public_key: String,
    pub fingerprint: String,
}
struct Discover(Arc<Mutex<Option<PublicKey>>>);
impl client::Handler for Discover {
    type Error = russh::Error;
    async fn check_server_key(
        &mut self,
        key: &PublicKeyOrCertificate,
    ) -> std::result::Result<bool, Self::Error> {
        // A probe never authenticates, accepts a connection, or changes trust.
        if key.certificate().is_none() {
            *self.0.lock().unwrap() = Some(key.public_key().clone());
        }
        Ok(false)
    }
}
pub async fn probe_host_key(host: String, port: u16) -> Result<HostKey> {
    validate_endpoint(&host, port)?;
    let cancel = Cancellation::default();
    let _abort = CancelOnDrop(cancel.clone());
    let found = Arc::new(Mutex::new(None));
    let stream = bounded(
        &cancel,
        8,
        "connection_failed",
        tokio::net::TcpStream::connect((host.as_str(), port)),
    )
    .await?;
    let _ = bounded(
        &cancel,
        8,
        "handshake_failed",
        client::connect_stream(
            Arc::new(client::Config {
                preferred: crate::safe_ssh_preferences(),
                ..Default::default()
            }),
            AbortableStream {
                inner: Box::new(stream),
                cancel: cancel.clone(),
            },
            Discover(found.clone()),
        ),
    )
    .await;
    let key = found
        .lock()
        .map_err(|_| "state_unavailable")?
        .take()
        .ok_or("host_key_unavailable")?;
    Ok(HostKey {
        host,
        port,
        public_key: key.to_openssh().map_err(|_| "invalid_host_key")?,
        fingerprint: key.fingerprint(russh::keys::HashAlg::Sha256).to_string(),
    })
}

#[derive(Clone, Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct ShellEvent {
    pub seq: u64,
    pub kind: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Vec<u8>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exit_status: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub presented_fingerprint: Option<String>,
}
type Reply = oneshot::Sender<Result<()>>;
enum Command {
    Write(Vec<u8>, Reply),
    Resize(u16, u16, Reply),
}
type OutputAck = Arc<Mutex<Option<(u64, oneshot::Sender<()>)>>>;
pub struct ShellCommands {
    rx: mpsc::Receiver<Command>,
    cancel: Cancellation,
    ready: Arc<AtomicBool>,
    ack: OutputAck,
}
#[derive(Clone)]
pub struct ShellControl {
    tx: mpsc::Sender<Command>,
    cancel: Cancellation,
    ready: Arc<AtomicBool>,
    ack: OutputAck,
}
pub fn shell_commands() -> (ShellControl, ShellCommands) {
    let (tx, rx) = mpsc::channel(16);
    let cancel = Cancellation::default();
    let ready = Arc::new(AtomicBool::new(false));
    let ack = Arc::new(Mutex::new(None));
    (
        ShellControl {
            tx,
            cancel: cancel.clone(),
            ready: ready.clone(),
            ack: ack.clone(),
        },
        ShellCommands {
            rx,
            cancel,
            ready,
            ack,
        },
    )
}
impl ShellControl {
    pub fn close(&self) {
        self.ready.store(false, Ordering::SeqCst);
        self.cancel.cancel();
    }
    pub fn acknowledge(&self, seq: u64) -> Result<()> {
        if self.cancel.is_cancelled() {
            return Err("cancelled");
        }
        let mut ack = self.ack.lock().map_err(|_| "state_unavailable")?;
        if ack.as_ref().is_none_or(|(pending, _)| *pending != seq) {
            return Err("stale_ack");
        }
        ack.take().unwrap().1.send(()).map_err(|_| "stale_ack")
    }
    pub async fn write(&self, bytes: Vec<u8>) -> Result<()> {
        if bytes.is_empty() || bytes.len() > 4096 {
            return Err("invalid_input");
        }
        let (tx, rx) = oneshot::channel();
        self.send(Command::Write(bytes, tx), rx).await
    }
    pub async fn resize(&self, cols: u16, rows: u16) -> Result<()> {
        validate_size(cols, rows)?;
        let (tx, rx) = oneshot::channel();
        self.send(Command::Resize(cols, rows, tx), rx).await
    }
    async fn send(&self, command: Command, rx: oneshot::Receiver<Result<()>>) -> Result<()> {
        if self.cancel.is_cancelled() {
            return Err("cancelled");
        }
        if !self.ready.load(Ordering::SeqCst) {
            return Err("shell_not_ready");
        }
        self.tx.try_send(command).map_err(|_| "shell_busy")?;
        // Never retry an uncertain write: a dropped reply may follow accepted bytes.
        match bounded(&self.cancel, 8, "input_unknown", rx).await {
            Err("timeout") => {
                // Retire queued input too: it must not run after its caller timed out.
                self.close();
                Err("input_unknown")
            }
            result => result?,
        }
    }
}
async fn request_reply(
    channel: &mut russh::Channel<client::Msg>,
    cancel: &Cancellation,
    code: &'static str,
) -> Result<()> {
    match bounded(cancel, 8, code, async {
        Ok::<_, russh::Error>(channel.wait().await)
    })
    .await?
    {
        Some(ChannelMsg::Success) => Ok(()),
        _ => Err(code),
    }
}

pub async fn run_shell(
    config: ShellConfig,
    commands: ShellCommands,
    emit: impl FnMut(ShellEvent) -> Result<()> + Send,
) -> Result<()> {
    let cancel = commands.cancel.clone();
    let _abort = CancelOnDrop(cancel.clone());
    let result = shell_connection(config, commands, emit).await;
    // Cancellation can make the underlying I/O fail during the same poll.
    if cancel.is_cancelled() {
        Err("cancelled")
    } else {
        result
    }
}
async fn shell_connection(
    config: ShellConfig,
    mut commands: ShellCommands,
    mut emit: impl FnMut(ShellEvent) -> Result<()> + Send,
) -> Result<()> {
    let cancel = commands.cancel.clone();
    let expected = config.validate()?;
    let audit = Arc::new(Audit::default());
    let observed = audit.clone();
    let (mut ssh, _) = match connect_pinned_endpoint(
        &config.host,
        config.port,
        &cancel,
        audit,
        expected,
        None,
        &transport::SystemDialer,
    )
    .await
    {
        Ok(connected) => connected,
        Err(code) => {
            // The rejected handshake still knows which key the server presented.
            if code == "host_key_mismatch" {
                if let Some(fingerprint) = observed.presented_host_key_fingerprint() {
                    emit(ShellEvent {
                        seq: 1,
                        kind: "host_key_change",
                        data: None,
                        exit_status: None,
                        presented_fingerprint: Some(fingerprint),
                    })?;
                }
            }
            return Err(code);
        }
    };
    let authenticated = if let Some(password) = &config.password {
        bounded(
            &cancel,
            8,
            "authentication_failed",
            ssh.authenticate_password(&config.username, password),
        )
        .await?
        .success()
    } else {
        let key = decode_secret_key(
            config
                .private_key_pem
                .as_deref()
                .ok_or("invalid_private_key")?,
            config.private_key_passphrase.as_deref(),
        )
        .map_err(|_| "invalid_private_key")?;
        let hash = if key.algorithm().is_rsa() {
            match bounded(
                &cancel,
                8,
                "authentication_failed",
                ssh.best_supported_rsa_hash(),
            )
            .await?
            {
                Some(Some(
                    hash @ (russh::keys::HashAlg::Sha256 | russh::keys::HashAlg::Sha512),
                )) => Some(hash),
                _ => return Err("rsa_sha2_required"),
            }
        } else {
            None
        };
        bounded(
            &cancel,
            8,
            "authentication_failed",
            ssh.authenticate_publickey(
                &config.username,
                PrivateKeyWithHashAlg::new(Arc::new(key), hash),
            ),
        )
        .await?
        .success()
    };
    if !authenticated {
        return Err("authentication_failed");
    }
    let mut channel = bounded(&cancel, 8, "channel_failed", ssh.channel_open_session()).await?;
    bounded(
        &cancel,
        8,
        "pty_failed",
        channel.request_pty(
            true,
            "xterm-256color",
            config.cols.into(),
            config.rows.into(),
            0,
            0,
            &[],
        ),
    )
    .await?;
    request_reply(&mut channel, &cancel, "pty_failed").await?;
    bounded(&cancel, 8, "shell_failed", channel.request_shell(true)).await?;
    request_reply(&mut channel, &cancel, "shell_failed").await?;
    drop(config); // Erase caller credentials once authentication/setup finishes.
    commands.ready.store(true, Ordering::SeqCst);
    let mut seq = 1;
    emit(ShellEvent {
        seq,
        kind: "ready",
        data: None,
        exit_status: None,
        presented_fingerprint: None,
    })?;
    let mut exit_status = None;
    loop {
        tokio::select! { biased;
            _ = cancel.wait() => return Err("cancelled"),
            command = commands.rx.recv() => match command {
                Some(Command::Write(bytes, reply)) => {
                    let result = bounded(&cancel, 8, "input_unknown", channel.data_bytes(bytes)).await
                        .map_err(|code| if code == "timeout" { "input_unknown" } else { code });
                    let _ = reply.send(result);
                    result?;
                }
                Some(Command::Resize(cols, rows, reply)) => {
                    let result = bounded(&cancel, 8, "resize_failed", channel.window_change(cols.into(), rows.into(), 0, 0)).await;
                    let _ = reply.send(result);
                    result?;
                }
                None => return Err("cancelled"),
            },
            message = channel.wait() => match message {
                Some(ChannelMsg::Data { data }) | Some(ChannelMsg::ExtendedData { data, .. }) => {
                    seq += 1;
                    let (tx, rx) = oneshot::channel();
                    *commands.ack.lock().map_err(|_| "state_unavailable")? = Some((seq, tx));
                    emit(ShellEvent { seq, kind: "data", data: Some(data.to_vec()), exit_status: None, presented_fingerprint: None })?;
                    // One packet at a time reaches the UI. SSH's bounded window
                    // then provides backpressure all the way to the remote PTY.
                    bounded(&cancel, 30, "output_ack_failed", rx).await
                        .map_err(|code| if code == "timeout" { "output_ack_failed" } else { code })?;
                }
                Some(ChannelMsg::ExitStatus { exit_status: status }) => exit_status = Some(status),
                Some(ChannelMsg::Close) | None => break,
                _ => {},
            }
        }
    }
    commands.ready.store(false, Ordering::SeqCst);
    let _ = bounded(
        &cancel,
        2,
        "close_failed",
        ssh.disconnect(Disconnect::ByApplication, "", "en"),
    )
    .await;
    emit(ShellEvent {
        seq: seq + 1,
        kind: "exit",
        data: None,
        exit_status,
        presented_fingerprint: None,
    })
}

#[cfg(all(test, unix))]
mod tests;
