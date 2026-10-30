//! Experimental in-memory, one-shot SSH reader. No credential discovery or terminal write API.
use base64ct::{Base64, Encoding};
use russh::{
    ChannelMsg, Disconnect, client,
    keys::{
        Algorithm, PrivateKeyWithHashAlg, PublicKey, PublicKeyOrCertificate, decode_secret_key,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    future::Future,
    io,
    pin::Pin,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    task::{Context, Poll, Waker},
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, BufReader, ReadBuf},
    net::TcpStream,
    sync::Notify,
    time::timeout,
};
use zeroize::Zeroize;

pub const CONFIG_LIMIT: usize = 32768;
const LINE_LIMIT: usize = 1_048_576;
const TOTAL_LIMIT: usize = 2_097_152;
pub type Result<T> = std::result::Result<T, &'static str>;

// Deliberately no Debug/Serialize: a config contains experimental credentials.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RemoteConfig {
    pub schema_version: u8,
    pub host: String,
    pub port: u16,
    pub username: String,
    pub expected_host_key: String,
    pub private_key_pem: String,
    pub socket_path: String,
    pub herdr_path: String,
    pub session: String,
    pub pane_id: String,
    pub review_confirmed: bool,
}
impl Drop for RemoteConfig {
    fn drop(&mut self) {
        self.private_key_pem.zeroize();
    }
}
impl RemoteConfig {
    pub fn from_json(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > CONFIG_LIMIT {
            return Err("config_too_large");
        }
        serde_json::from_slice(bytes).map_err(|_| "invalid_config")
    }
    fn validate(&self) -> Result<PublicKey> {
        fn bounded(s: &str, max: usize) -> bool {
            !s.is_empty() && s.len() <= max && !s.chars().any(char::is_control)
        }
        let host = self.host.parse::<std::net::IpAddr>().is_ok()
            || self.host.split('.').all(|part| {
                !part.is_empty()
                    && part.len() <= 63
                    && !part.starts_with('-')
                    && !part.ends_with('-')
                    && part.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
            });
        if self.schema_version != 1
            || !self.review_confirmed
            || !bounded(&self.host, 253)
            || !host
            || self.port == 0
            || !bounded(&self.username, 128)
            || self.username.chars().any(char::is_whitespace)
            || !valid_name(&self.session, 64, false)
            || self.session == "default"
            || !valid_name(&self.pane_id, 128, true)
            || !unix_path(&self.socket_path)
            || !unix_path(&self.herdr_path)
            || self.private_key_pem.len() > 16384
            || !self
                .private_key_pem
                .starts_with("-----BEGIN OPENSSH PRIVATE KEY-----\n")
        {
            return Err("invalid_config");
        }
        if self.expected_host_key.len() > 4096
            || self.expected_host_key.contains(['\n', '\r', '\t'])
        {
            return Err("invalid_host_key");
        }
        let parts: Vec<_> = self.expected_host_key.split(' ').collect();
        if parts.len() != 2 || parts[0] != "ssh-ed25519" || parts[1].is_empty() {
            return Err("invalid_host_key");
        }
        let key =
            PublicKey::from_openssh(&self.expected_host_key).map_err(|_| "invalid_host_key")?;
        if key.algorithm() != Algorithm::Ed25519
            || key.to_openssh().map_err(|_| "invalid_host_key")? != self.expected_host_key
        {
            return Err("invalid_host_key");
        }
        Ok(key)
    }
}
fn valid_name(s: &str, max: usize, colon: bool) -> bool {
    !s.is_empty()
        && s.len() <= max
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-') || (colon && c == b':'))
}
fn unix_path(s: &str) -> bool {
    s.starts_with('/')
        && s.len() <= 1024
        && !s.chars().any(char::is_control)
        && s[1..]
            .split('/')
            .all(|p| !p.is_empty() && p != "." && p != "..")
}
fn quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}
/// Restricts this milestone to release herdr named-session layout, with no path or env fallback.
pub fn config_root(socket: &str, session: &str) -> Result<String> {
    if session == "default" || !valid_name(session, 64, false) || !unix_path(socket) {
        return Err("session_mismatch");
    }
    let suffix = format!("/herdr/sessions/{session}/herdr.sock");
    let root = socket
        .strip_suffix(&suffix)
        .filter(|root| unix_path(root))
        .ok_or("session_mismatch")?;
    Ok(root.to_string())
}
fn observe_command(config: &RemoteConfig, terminal_id: &str) -> Result<String> {
    if !terminal_id.starts_with("term_")
        || terminal_id.len() <= 5
        || terminal_id.len() > 128
        || !terminal_id[5..]
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err("invalid_terminal_id");
    }
    let root = config_root(&config.socket_path, &config.session)?;
    Ok(format!(
        "/usr/bin/env {} {} --session {} terminal session observe {} --cols 80 --rows 24",
        quote(&format!("XDG_CONFIG_HOME={root}")),
        quote(&config.herdr_path),
        quote(&config.session),
        quote(terminal_id)
    ))
}

#[derive(Default)]
pub struct Audit {
    host_key_checked: AtomicBool,
    host_key_matched: AtomicBool,
    auth_started: AtomicBool,
    snapshot_received: AtomicBool,
    full_frame_received: AtomicBool,
}
#[derive(Default, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct AuditSnapshot {
    pub host_key_checked: bool,
    pub host_key_matched: bool,
    pub auth_started: bool,
    pub snapshot_received: bool,
    pub full_frame_received: bool,
}
impl Audit {
    pub fn snapshot(&self) -> AuditSnapshot {
        AuditSnapshot {
            host_key_checked: self.host_key_checked.load(Ordering::SeqCst),
            host_key_matched: self.host_key_matched.load(Ordering::SeqCst),
            auth_started: self.auth_started.load(Ordering::SeqCst),
            snapshot_received: self.snapshot_received.load(Ordering::SeqCst),
            full_frame_received: self.full_frame_received.load(Ordering::SeqCst),
        }
    }
}

#[derive(Default)]
struct CancelState {
    cancelled: AtomicBool,
    wake: Notify,
    io_wakers: Mutex<(Option<Waker>, Option<Waker>)>,
}
#[derive(Default, Clone)]
pub struct Cancellation(Arc<CancelState>);
impl Cancellation {
    pub fn cancel(&self) {
        self.0.cancelled.store(true, Ordering::SeqCst);
        self.0.wake.notify_waiters();
        if let Ok(mut w) = self.0.io_wakers.lock() {
            if let Some(w) = w.0.take() {
                w.wake();
            }
            if let Some(w) = w.1.take() {
                w.wake();
            }
        }
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.cancelled.load(Ordering::SeqCst)
    }
    async fn wait(&self) {
        loop {
            let wake = self.0.wake.notified();
            tokio::pin!(wake);
            wake.as_mut().enable();
            if self.is_cancelled() {
                return;
            }
            wake.await;
        }
    }
    fn io_ready(&self, cx: &Context<'_>, write: bool) -> io::Result<()> {
        let mut w = self
            .0
            .io_wakers
            .lock()
            .map_err(|_| io::Error::other("cancel state"))?;
        if self.is_cancelled() {
            return Err(io::Error::new(
                io::ErrorKind::ConnectionAborted,
                "cancelled",
            ));
        }
        if write {
            w.1 = Some(cx.waker().clone())
        } else {
            w.0 = Some(cx.waker().clone())
        }
        Ok(())
    }
}
struct CancelOnDrop(Cancellation);
impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.cancel();
    }
}
// russh owns a background task. Abort its actual TCP I/O, not just the caller's future.
struct AbortableStream {
    inner: TcpStream,
    cancel: Cancellation,
}
impl AsyncRead for AbortableStream {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        if let Err(e) = self.cancel.io_ready(cx, false) {
            return Poll::Ready(Err(e));
        }
        Pin::new(&mut self.inner).poll_read(cx, buf)
    }
}
impl AsyncWrite for AbortableStream {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        if let Err(e) = self.cancel.io_ready(cx, true) {
            return Poll::Ready(Err(e));
        }
        Pin::new(&mut self.inner).poll_write(cx, buf)
    }
    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        if let Err(e) = self.cancel.io_ready(cx, true) {
            return Poll::Ready(Err(e));
        }
        Pin::new(&mut self.inner).poll_flush(cx)
    }
    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_shutdown(cx)
    }
}
async fn bounded<T, E>(
    cancel: &Cancellation,
    seconds: u64,
    code: &'static str,
    future: impl Future<Output = std::result::Result<T, E>>,
) -> Result<T> {
    tokio::select! { biased; _=cancel.wait()=>Err("cancelled"), value=timeout(Duration::from_secs(seconds),future)=>value.map_err(|_|"timeout")?.map_err(|_|code) }
}
struct Pinned {
    expected: PublicKey,
    audit: Arc<Audit>,
}
impl client::Handler for Pinned {
    type Error = russh::Error;
    async fn check_server_key(
        &mut self,
        key: &PublicKeyOrCertificate,
    ) -> std::result::Result<bool, Self::Error> {
        self.audit.host_key_checked.store(true, Ordering::SeqCst);
        // A pinned raw public key is not authorization for a certificate signed by it.
        let matches = key.certificate().is_none() && key.public_key() == self.expected;
        self.audit.host_key_matched.store(matches, Ordering::SeqCst);
        Ok(matches)
    }
    async fn server_channel_open_session(
        &mut self,
        _: russh::Channel<client::Msg>,
        reply: client::ChannelOpenHandle,
        _: &mut client::Session,
    ) -> std::result::Result<(), Self::Error> {
        drop(reply);
        Ok(())
    }
    async fn server_channel_open_agent_forward(
        &mut self,
        _: russh::Channel<client::Msg>,
        reply: client::ChannelOpenHandle,
        _: &mut client::Session,
    ) -> std::result::Result<(), Self::Error> {
        drop(reply);
        Ok(())
    }
    async fn server_channel_open_forwarded_streamlocal(
        &mut self,
        _: russh::Channel<client::Msg>,
        _: &str,
        reply: client::ChannelOpenHandle,
        _: &mut client::Session,
    ) -> std::result::Result<(), Self::Error> {
        drop(reply);
        Ok(())
    }
    async fn server_channel_open_direct_streamlocal(
        &mut self,
        _: russh::Channel<client::Msg>,
        _: &str,
        reply: client::ChannelOpenHandle,
        _: &mut client::Session,
    ) -> std::result::Result<(), Self::Error> {
        drop(reply);
        Ok(())
    }
    async fn server_channel_open_x11(
        &mut self,
        _: russh::Channel<client::Msg>,
        _: &str,
        _: u32,
        reply: client::ChannelOpenHandle,
        _: &mut client::Session,
    ) -> std::result::Result<(), Self::Error> {
        drop(reply);
        Ok(())
    }
    async fn server_channel_open_forwarded_tcpip(
        &mut self,
        _: russh::Channel<client::Msg>,
        _: &str,
        _: u32,
        _: &str,
        _: u32,
        reply: client::ChannelOpenHandle,
        _: &mut client::Session,
    ) -> std::result::Result<(), Self::Error> {
        drop(reply);
        Ok(())
    }
    async fn server_channel_open_direct_tcpip(
        &mut self,
        _: russh::Channel<client::Msg>,
        _: &str,
        _: u32,
        _: &str,
        _: u32,
        reply: client::ChannelOpenHandle,
        _: &mut client::Session,
    ) -> std::result::Result<(), Self::Error> {
        drop(reply);
        Ok(())
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FullSnapshot {
    pub bytes: Vec<u8>,
    pub terminal_id: String,
    pub columns: u16,
    pub rows: u16,
}
fn snapshot_terminal(value: &Value, pane: &str) -> Result<String> {
    if value["id"] != "pocket-readonly"
        || value["ok"] == false
        || value.get("error").is_some_and(|v| !v.is_null())
    {
        return Err("snapshot_rejected");
    }
    let envelope = value.get("result").ok_or("invalid_snapshot")?;
    if envelope["type"] != "session_snapshot" {
        return Err("invalid_snapshot");
    }
    let result = envelope
        .get("snapshot")
        .filter(|v| v.is_object())
        .ok_or("invalid_snapshot")?;
    if result["version"] != "0.9.5" || result["protocol"] != 22 {
        return Err("unsupported_protocol");
    }
    let panes = result["panes"].as_array().ok_or("invalid_snapshot")?;
    let mut matching = panes.iter().filter(|p| p["pane_id"] == pane);
    let selected = matching.next().ok_or("pane_missing")?;
    if matching.next().is_some() {
        return Err("ambiguous_pane");
    }
    selected["terminal_id"]
        .as_str()
        .map(str::to_string)
        .ok_or("invalid_terminal_id")
}
fn parse_frame(value: Value) -> Result<Vec<u8>> {
    if value["type"] != "terminal.frame"
        || value["full"] != true
        || value["encoding"] != "ansi"
        || value["width"] != 80
        || value["height"] != 24
        || !value["seq"].is_u64()
    {
        return Err("invalid_full_frame");
    }
    let text = value["bytes"].as_str().ok_or("invalid_full_frame")?;
    Base64::decode_vec(text).map_err(|_| "invalid_full_frame")
}
pub async fn read_once(
    config: RemoteConfig,
    cancel: Cancellation,
    audit: Arc<Audit>,
    progress: impl Fn(&'static str) + Send + Sync,
) -> Result<FullSnapshot> {
    let _cancel_on_drop = CancelOnDrop(cancel.clone());
    let expected = config.validate()?;
    let private =
        decode_secret_key(&config.private_key_pem, None).map_err(|_| "invalid_private_key")?;
    if private.algorithm() != Algorithm::Ed25519 {
        return Err("invalid_private_key");
    }
    progress("connecting");
    let tcp = bounded(
        &cancel,
        8,
        "connection_failed",
        TcpStream::connect((config.host.as_str(), config.port)),
    )
    .await?;
    let settings = client::Config {
        window_size: 65536,
        maximum_packet_size: 32768,
        channel_buffer_size: 2,
        inactivity_timeout: Some(Duration::from_secs(12)),
        ..Default::default()
    };
    let connect = bounded(
        &cancel,
        8,
        "handshake_failed",
        client::connect_stream(
            Arc::new(settings),
            AbortableStream {
                inner: tcp,
                cancel: cancel.clone(),
            },
            Pinned {
                expected,
                audit: audit.clone(),
            },
        ),
    )
    .await;
    let mut ssh = match connect {
        Ok(ssh) => ssh,
        Err(code) => {
            return Err(
                if audit.snapshot().host_key_checked && !audit.snapshot().host_key_matched {
                    "host_key_mismatch"
                } else {
                    code
                },
            );
        }
    };
    if !audit.snapshot().host_key_matched {
        return Err("host_key_mismatch");
    }
    progress("host-key-verified");
    audit.auth_started.store(true, Ordering::SeqCst);
    if !bounded(
        &cancel,
        8,
        "authentication_failed",
        ssh.authenticate_publickey(
            &config.username,
            PrivateKeyWithHashAlg::new(Arc::new(private), None),
        ),
    )
    .await?
    .success()
    {
        return Err("authentication_failed");
    }
    progress("authenticated");
    let channel = bounded(
        &cancel,
        8,
        "socket_unavailable",
        ssh.channel_open_direct_streamlocal(&config.socket_path),
    )
    .await?;
    let mut stream = channel.into_stream();
    bounded(
        &cancel,
        8,
        "snapshot_failed",
        stream.write_all(
            b"{\"id\":\"pocket-readonly\",\"method\":\"session.snapshot\",\"params\":{}}\n",
        ),
    )
    .await?;
    let mut bytes = Vec::new();
    bounded(
        &cancel,
        8,
        "snapshot_failed",
        BufReader::new(stream.take((LINE_LIMIT + 1) as u64)).read_until(b'\n', &mut bytes),
    )
    .await?;
    if bytes.len() > LINE_LIMIT || !bytes.ends_with(b"\n") {
        return Err("snapshot_limit");
    }
    let value: Value = serde_json::from_slice(&bytes).map_err(|_| "invalid_snapshot")?;
    audit.snapshot_received.store(true, Ordering::SeqCst);
    let terminal_id = snapshot_terminal(&value, &config.pane_id)?;
    let command = observe_command(&config, &terminal_id)?;
    progress("snapshot-received");
    if cancel.is_cancelled() {
        return Err("cancelled");
    }
    let mut channel = bounded(&cancel, 8, "observe_failed", ssh.channel_open_session()).await?;
    bounded(&cancel, 8, "observe_failed", channel.exec(true, command)).await?;
    let full = bounded(&cancel, 10, "observe_failed", async {
        let mut pending = Vec::new();
        let mut total = 0usize;
        while let Some(msg) = channel.wait().await {
            match msg {
                ChannelMsg::Data { data } => {
                    total += data.len();
                    if total > TOTAL_LIMIT {
                        return Err("observe_limit");
                    }
                    for b in data.iter() {
                        pending.push(*b);
                        if pending.len() > LINE_LIMIT {
                            return Err("observe_limit");
                        }
                        if *b == b'\n' {
                            let frame: Value = serde_json::from_slice(&pending)
                                .map_err(|_| "invalid_full_frame")?;
                            pending.clear();
                            // No deltas or arbitrary preamble are accepted as an initial full snapshot.
                            return parse_frame(frame);
                        }
                    }
                }
                ChannelMsg::ExtendedData { data, .. } => {
                    total += data.len();
                    if total > TOTAL_LIMIT {
                        return Err("observe_limit");
                    }
                }
                ChannelMsg::Failure
                | ChannelMsg::ExitStatus { .. }
                | ChannelMsg::Close
                | ChannelMsg::Eof => return Err("observe_ended"),
                _ => {}
            }
        }
        Err("observe_ended")
    })
    .await?;
    if cancel.is_cancelled() {
        return Err("cancelled");
    }
    audit.full_frame_received.store(true, Ordering::SeqCst);
    progress("full-frame-received");
    let _ = timeout(Duration::from_secs(1), channel.close()).await;
    let _ = timeout(
        Duration::from_secs(1),
        ssh.disconnect(Disconnect::ByApplication, "one-shot complete", ""),
    )
    .await;
    if cancel.is_cancelled() {
        return Err("cancelled");
    }
    Ok(FullSnapshot {
        bytes: full,
        terminal_id,
        columns: 80,
        rows: 24,
    })
}

/// Frontends also guard their callbacks; this protects native command ownership across cancellation.
#[derive(Default)]
pub struct AttemptGate {
    generation: u64,
    pending: Option<(u64, Cancellation)>,
    valid: bool,
}
impl AttemptGate {
    pub fn begin(&mut self) -> Result<(u64, Cancellation)> {
        if self.pending.is_some() {
            return Err("busy");
        }
        self.generation += 1;
        self.valid = true;
        let cancel = Cancellation::default();
        self.pending = Some((self.generation, cancel.clone()));
        Ok((self.generation, cancel))
    }
    pub fn cancel(&mut self) {
        self.valid = false;
        self.generation += 1;
        if let Some((_, cancel)) = &self.pending {
            cancel.cancel();
        }
    }
    pub fn finish(&mut self, generation: u64) -> bool {
        let same = self.pending.as_ref().is_some_and(|(g, _)| *g == generation);
        let accepted = same && self.valid && self.generation == generation;
        if same {
            self.pending = None;
        }
        accepted
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn example_config() -> RemoteConfig {
        // Synthetic public key bytes, not an authorized identity; no private key is generated/read.
        let mut wire = Vec::from(&b"\0\0\0\x0bssh-ed25519\0\0\0\x20"[..]);
        wire.extend([0u8; 32]);
        RemoteConfig::from_json(
            serde_json::to_string(&json!({
                "schemaVersion":1,"host":"127.0.0.1","port":2222,"username":"fixture",
                "expectedHostKey":format!("ssh-ed25519 {}",Base64::encode_string(&wire)),
                "privateKeyPem":"-----BEGIN OPENSSH PRIVATE KEY-----\nNOT-A-KEY",
                "socketPath":"/tmp/fixture/herdr/sessions/work/herdr.sock","herdrPath":"/tmp/herdr",
                "session":"work","paneId":"pane:1","reviewConfirmed":true
            }))
            .unwrap()
            .as_bytes(),
        )
        .unwrap()
    }
    #[test]
    fn config_requires_review_and_one_canonical_ed25519_host_key() {
        let good = example_config();
        assert!(good.validate().is_ok());
        for pin in [
            format!("{} comment", good.expected_host_key),
            format!("{}\n", good.expected_host_key),
            good.expected_host_key
                .replace("ssh-ed25519 ", "ssh-ed25519  "),
            "ssh-ed25519 AAAA".into(),
        ] {
            let mut bad = example_config();
            bad.expected_host_key = pin;
            assert!(bad.validate().is_err());
        }
        let mut bad = example_config();
        bad.review_confirmed = false;
        assert!(bad.validate().is_err());
        bad = example_config();
        bad.host = "https://127.0.0.1".into();
        assert!(bad.validate().is_err());
        assert!(RemoteConfig::from_json(&vec![b' '; CONFIG_LIMIT + 1]).is_err());
    }
    #[test]
    fn fixed_command_uses_derived_root_and_resolved_id_not_pane_name() {
        let mut config = example_config();
        config.socket_path = "/tmp/a'b;$(x)/herdr/sessions/work/herdr.sock".into();
        let cmd = observe_command(&config, "term_abc123").unwrap();
        assert_eq!(
            cmd,
            "/usr/bin/env 'XDG_CONFIG_HOME=/tmp/a'\"'\"'b;$(x)' '/tmp/herdr' --session 'work' terminal session observe 'term_abc123' --cols 80 --rows 24"
        );
        assert!(observe_command(&config, "pane:1").is_err());
        assert!(observe_command(&config, "term_a;exit").is_err());
    }
    #[test]
    fn root_binding_rejects_session_alias_and_noncanonical_paths() {
        assert_eq!(
            config_root("/tmp/a/herdr/sessions/work/herdr.sock", "work").unwrap(),
            "/tmp/a"
        );
        for socket in [
            "/tmp/a/herdr/sessions/other/herdr.sock",
            "/tmp/a/../b/herdr/sessions/work/herdr.sock",
            "/tmp//a/herdr/sessions/work/herdr.sock",
            "/tmp/a/herdr.sock",
        ] {
            assert!(config_root(socket, "work").is_err());
        }
        assert!(config_root("/tmp/a/herdr/sessions/default/herdr.sock", "default").is_err());
    }
    #[test]
    fn quotes_shell_metacharacters_as_one_argument() {
        assert_eq!(quote("/tmp/a'b;$(x)"), "'/tmp/a'\"'\"'b;$(x)'");
    }
    #[test]
    fn snapshot_needs_id_version_and_unique_target() {
        // Fixed upstream ResponseResult is an internally tagged enum, not a flat snapshot.
        let v = json!({"id":"pocket-readonly","result":{"type":"session_snapshot","snapshot":{"version":"0.9.5","protocol":22,"panes":[{"pane_id":"pane:1","terminal_id":"term_123"}]}}});
        assert_eq!(snapshot_terminal(&v, "pane:1").unwrap(), "term_123");
        assert_eq!(snapshot_terminal(&v, "pane:2"), Err("pane_missing"));
        let mut wrong = v.clone();
        wrong["id"] = json!("other");
        assert!(snapshot_terminal(&wrong, "pane:1").is_err());
        wrong = v.clone();
        wrong["ok"] = json!(false);
        assert_eq!(
            snapshot_terminal(&wrong, "pane:1"),
            Err("snapshot_rejected")
        );
        wrong = v.clone();
        wrong["result"] = v["result"]["snapshot"].clone();
        assert_eq!(snapshot_terminal(&wrong, "pane:1"), Err("invalid_snapshot"));
        wrong = v.clone();
        wrong["result"]["type"] = json!("pong");
        assert_eq!(snapshot_terminal(&wrong, "pane:1"), Err("invalid_snapshot"));
        for (field, invalid) in [("version", json!("0.9.6")), ("protocol", json!(21))] {
            wrong = v.clone();
            wrong["result"]["snapshot"][field] = invalid;
            assert_eq!(
                snapshot_terminal(&wrong, "pane:1"),
                Err("unsupported_protocol")
            );
        }
        wrong = v;
        wrong["result"]["snapshot"]["panes"]
            .as_array_mut()
            .unwrap()
            .push(json!({"pane_id":"pane:1","terminal_id":"term_456"}));
        assert_eq!(snapshot_terminal(&wrong, "pane:1"), Err("ambiguous_pane"));
    }
    #[test]
    fn first_frame_is_full_ansi_at_fixed_grid() {
        let full = json!({"type":"terminal.frame","seq":1,"full":true,"encoding":"ansi","width":80,"height":24,"bytes":"YWJj"});
        assert_eq!(parse_frame(full.clone()).unwrap(), b"abc");
        for (field, value) in [
            ("full", json!(false)),
            ("width", json!(81)),
            ("encoding", json!("plain")),
            ("bytes", json!("?")),
        ] {
            let mut v = full.clone();
            v[field] = value;
            assert!(parse_frame(v).is_err());
        }
    }
    #[test]
    fn cancellation_invalidates_before_old_completion_and_preserves_new_attempt() {
        let mut g = AttemptGate::default();
        let (old, c) = g.begin().unwrap();
        g.cancel();
        assert!(c.is_cancelled());
        assert!(!g.finish(old));
        let (new, _) = g.begin().unwrap();
        assert!(!g.finish(old));
        assert!(g.finish(new));
    }
    #[tokio::test]
    async fn cancellation_interrupts_pending_operation() {
        let c = Cancellation::default();
        let other = c.clone();
        tokio::spawn(async move {
            tokio::task::yield_now().await;
            other.cancel();
        });
        assert_eq!(
            bounded(
                &c,
                2,
                "wrong",
                std::future::pending::<std::result::Result<(), ()>>()
            )
            .await,
            Err("cancelled")
        );
    }
    #[tokio::test]
    async fn cancelling_stream_wakes_pending_tcp_read_and_closes_owned_socket() {
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let client = TcpStream::connect(listener.local_addr().unwrap())
            .await
            .unwrap();
        let (mut peer, _) = listener.accept().await.unwrap();
        let cancel = Cancellation::default();
        let mut stream = AbortableStream {
            inner: client,
            cancel: cancel.clone(),
        };
        let read = tokio::spawn(async move {
            let mut b = [0];
            stream.read(&mut b).await.unwrap_err().kind()
        });
        tokio::task::yield_now().await;
        cancel.cancel();
        assert_eq!(
            timeout(Duration::from_secs(1), read)
                .await
                .unwrap()
                .unwrap(),
            io::ErrorKind::ConnectionAborted
        );
        let mut b = [0];
        assert_eq!(
            timeout(Duration::from_secs(1), peer.read(&mut b))
                .await
                .unwrap()
                .unwrap(),
            0
        );
    }
}
