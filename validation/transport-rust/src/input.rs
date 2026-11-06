//! Candidate extension only. A send is never retried and a lost reply is unknown.
use crate::{Cancellation, Pinned, bounded, client};
use base64ct::{Base64, Encoding};
use serde::Deserialize;
use serde_json::json;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};

const LIMIT: usize = 4096;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope<T> {
    id: String,
    result: T,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Capability {
    #[serde(rename = "type")]
    kind: String,
    version: u32,
    protocol: u32,
    atomic_terminal_guard: bool,
    raw_bytes: bool,
    max_input_bytes: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Accepted {
    #[serde(rename = "type")]
    kind: String,
    pane_id: String,
    terminal_id: String,
    accepted_bytes: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ErrorEnvelope {
    id: String,
    error: ErrorBody,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ErrorBody {
    code: String,
    message: String,
}
fn random_id() -> Option<String> {
    use ring::rand::SecureRandom;
    let mut b = [0u8; 16];
    ring::rand::SystemRandom::new().fill(&mut b).ok()?;
    Some(b.iter().map(|v| format!("{v:02x}")).collect())
}
fn capability_reply(raw: &[u8], id: &str) -> bool {
    let Ok(e) = serde_json::from_slice::<Envelope<Capability>>(raw) else {
        return false;
    };
    e.id == id
        && e.result.kind == "pocket_input_capabilities"
        && e.result.version == 1
        && e.result.protocol == 22
        && e.result.atomic_terminal_guard
        && e.result.raw_bytes
        && e.result.max_input_bytes == LIMIT
}
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InputReceipt {
    pub request_id: String,
    pub pane_id: String,
    pub terminal_id: String,
    pub accepted_bytes: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SendOutcome {
    Accepted(InputReceipt),
    Rejected,
    /// The host returned a correlated decision but the local marker could not be cleared.
    RecoveryLocked { receipt: Option<InputReceipt> },
    Unknown,
}
fn outcome(raw: &[u8], id: &str, pane: &str, terminal: &str, len: usize) -> SendOutcome {
    if let Ok(e) = serde_json::from_slice::<Envelope<Accepted>>(raw) {
        if e.id == id
            && e.result.kind == "pocket_input_accepted"
            && e.result.pane_id == pane
            && e.result.terminal_id == terminal
            && e.result.accepted_bytes == len
        {
            return SendOutcome::Accepted(InputReceipt {
                request_id: e.id,
                pane_id: e.result.pane_id,
                terminal_id: e.result.terminal_id,
                accepted_bytes: e.result.accepted_bytes,
            });
        }
    }
    if let Ok(e) = serde_json::from_slice::<ErrorEnvelope>(raw) {
        if e.id == id && e.error.code == "pocket_input_rejected" && !e.error.message.is_empty() {
            return SendOutcome::Rejected;
        }
    }
    SendOutcome::Unknown
}
async fn rpc(
    ssh: &client::Handle<Pinned>,
    socket: &str,
    cancel: &Cancellation,
    request: serde_json::Value,
) -> std::result::Result<Vec<u8>, ()> {
    let channel = bounded(
        cancel,
        5,
        "rpc_failed",
        ssh.channel_open_direct_streamlocal(socket),
    )
    .await
    .map_err(|_| ())?;
    let mut stream = channel.into_stream();
    let mut wire = serde_json::to_vec(&request).map_err(|_| ())?;
    wire.push(b'\n');
    bounded(cancel, 5, "rpc_failed", stream.write_all(&wire))
        .await
        .map_err(|_| ())?;
    let mut data = Vec::new();
    bounded(
        cancel,
        5,
        "rpc_failed",
        BufReader::new(stream.take(8193)).read_until(b'\n', &mut data),
    )
    .await
    .map_err(|_| ())?;
    if data.len() > 8192 || !data.ends_with(b"\n") {
        return Err(());
    }
    Ok(data)
}
pub(crate) async fn discover(
    ssh: &client::Handle<Pinned>,
    socket: &str,
    cancel: &Cancellation,
) -> bool {
    let Some(id) = random_id() else {
        return false;
    };
    let request = json!({"id":id,"method":"pocket.input.capabilities","params":{}});
    match rpc(ssh, socket, cancel, request).await {
        Ok(v) => capability_reply(&v, &id),
        Err(_) => false,
    }
}
#[derive(Default)]
struct State {
    valid: bool,
    focused: bool,
    mode: Mode,
    inflight: bool,
    epoch: u64,
}
impl State {
    fn permits(&self, epoch: u64, draft: bool, unknown: bool, cancelled: bool) -> bool {
        self.valid
            && !cancelled
            && self.focused
            && self.epoch == epoch
            && !self.inflight
            && !unknown
            && (if draft {
                self.mode == Mode::Draft
            } else {
                self.mode == Mode::Direct
            })
    }
}
#[derive(Default, PartialEq, Eq)]
enum Mode {
    #[default]
    Observe,
    Direct,
    Draft,
}
#[derive(Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InputIdentity {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub route: Option<crate::transport::OverlayRouteIdentity>,
    pub host: String,
    pub port: u16,
    pub user: String,
    pub host_key: String,
    pub socket: String,
    pub herdr: String,
    pub session: String,
    pub pane: String,
    pub terminal: String,
}
pub type Recovery = crate::recovery::SharedRecovery;
pub struct LiveInput {
    ssh: Arc<client::Handle<Pinned>>,
    socket: String,
    pane: String,
    terminal: String,
    cancel: Cancellation,
    state: Mutex<State>,
    recovery: Recovery,
    identity: InputIdentity,
}
impl LiveInput {
    pub(crate) fn new(
        ssh: Arc<client::Handle<Pinned>>,
        identity: InputIdentity,
        cancel: Cancellation,
        recovery: Recovery,
    ) -> Self {
        Self {
            ssh,
            socket: identity.socket.clone(),
            pane: identity.pane.clone(),
            terminal: identity.terminal.clone(),
            cancel,
            state: Mutex::new(State {
                valid: true,
                ..Default::default()
            }),
            recovery,
            identity,
        }
    }
    pub fn unknown(&self) -> bool {
        self.recovery.unknown()
    }
    pub fn recovery_status(&self) -> &'static str {
        self.recovery.status()
    }
    fn mark_unknown(&self) { /* the durable marker was written before network I/O */
    }
    pub fn set_mode(&self, mode: &str, focused: bool) -> crate::Result<u64> {
        let mut s = self.state.lock().map_err(|_| "input_unavailable")?;
        if !s.valid || self.cancel.is_cancelled() {
            return Err("input_stale");
        }
        let next = match mode {
            "observe" => Mode::Observe,
            "direct" => Mode::Direct,
            "draft" => Mode::Draft,
            _ => return Err("input_invalid_mode"),
        };
        if s.inflight && (!focused || next != s.mode) {
            self.mark_unknown();
            s.valid = false;
            self.cancel.cancel();
            return Err("input_result_unknown");
        }
        s.mode = next;
        s.focused = focused;
        s.epoch = s.epoch.checked_add(1).ok_or("input_stale")?;
        Ok(s.epoch)
    }
    pub fn acknowledge_unknown(&self, epoch: u64) -> crate::Result<()> {
        let mut s = self.state.lock().map_err(|_| "input_unavailable")?;
        if !s.valid
            || self.cancel.is_cancelled()
            || !s.focused
            || s.mode != Mode::Observe
            || s.inflight
            || s.epoch != epoch
        {
            return Err("input_stale");
        }
        self.recovery.clear_confirmed(&self.identity, None)?;
        s.epoch += 1;
        Ok(())
    }
    pub fn invalidate(&self) {
        if let Ok(mut s) = self.state.lock() {
            if s.inflight {
                self.mark_unknown();
            }
            s.valid = false;
            s.focused = false;
            s.epoch = s.epoch.saturating_add(1);
        }
    }
    pub async fn send(&self, epoch: u64, data: Vec<u8>, draft: bool) -> crate::Result<SendOutcome> {
        if data.is_empty() || data.len() > LIMIT {
            return Err("input_invalid_size");
        }
        let id = random_id().ok_or("input_storage_unavailable")?;
        {
            let mut s = self.state.lock().map_err(|_| "input_unavailable")?;
            if !s.permits(epoch, draft, self.unknown(), self.cancel.is_cancelled()) {
                return Err("input_stale");
            }
            self.recovery.prepare(&self.identity, &id)?;
            s.inflight = true;
        }
        struct Pending<'a>(&'a LiveInput, bool);
        impl Drop for Pending<'_> {
            fn drop(&mut self) {
                if !self.1 {
                    self.0.mark_unknown();
                    self.0.invalidate();
                    self.0.cancel.cancel();
                }
                self.0.recovery.end_attempt();
                if let Ok(mut s) = self.0.state.lock() {
                    s.inflight = false;
                }
            }
        }
        let mut pending = Pending(self, false);
        let request = json!({"id":id,"method":"pocket.input.send","params":{"pane_id":self.pane,"expected_terminal_id":self.terminal,"bytes_base64":Base64::encode_string(&data)}});
        let result = match rpc(&self.ssh, &self.socket, &self.cancel, request).await {
            Ok(raw) => outcome(&raw, &id, &self.pane, &self.terminal, data.len()),
            Err(_) => SendOutcome::Unknown,
        };
        if let Ok(state) = self.state.lock() {
            if result != SendOutcome::Unknown && state.valid && !self.cancel.is_cancelled() {
                if self.recovery.clear_confirmed(&self.identity, Some(&id)).is_ok() {
                    pending.1 = true;
                    return Ok(result);
                }
                return Ok(match result {
                    SendOutcome::Accepted(receipt) => SendOutcome::RecoveryLocked { receipt: Some(receipt) },
                    SendOutcome::Rejected => SendOutcome::RecoveryLocked { receipt: None },
                    other => other,
                });
            }
        }
        // The pending guard invalidates the lease and ends the connection on
        // unresolved writes, including failure to clear a known decision.
        Ok(SendOutcome::Unknown)
    }
}
impl Drop for LiveInput {
    fn drop(&mut self) {
        self.invalidate();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn input_requires_full_lease_focus_explicit_mode_and_known_result() {
        let mut s = State::default();
        s.epoch = 4;
        assert!(!s.permits(4, false, false, false));
        s.valid = true;
        s.focused = true;
        assert!(!s.permits(4, false, false, false)); // observe is read-only
        s.mode = Mode::Direct;
        assert!(s.permits(4, false, false, false));
        assert!(!s.permits(3, false, false, false));
        assert!(!s.permits(4, true, false, false));
        assert!(!s.permits(4, false, true, false));
        assert!(!s.permits(4, false, false, true));
        s.inflight = true;
        assert!(!s.permits(4, false, false, false));
        s.inflight = false;
        s.focused = false;
        assert!(!s.permits(4, false, false, false));
    }
    #[test]
    fn strict_capability_and_ack_correlation() {
        let cap=br#"{"id":"i","result":{"type":"pocket_input_capabilities","version":1,"protocol":22,"atomic_terminal_guard":true,"raw_bytes":true,"max_input_bytes":4096}}"#;
        assert!(capability_reply(cap, "i"));
        assert!(!capability_reply(cap, "j"));
        let ack=br#"{"id":"i","result":{"type":"pocket_input_accepted","pane_id":"p","terminal_id":"t","accepted_bytes":3}}"#;
        let SendOutcome::Accepted(receipt) = outcome(ack, "i", "p", "t", 3) else {
            panic!("expected the correlated queue receipt");
        };
        assert_eq!(serde_json::to_value(receipt).unwrap(), json!({
            "requestId":"i", "paneId":"p", "terminalId":"t", "acceptedBytes":3
        }));
        assert_eq!(outcome(ack, "other", "p", "t", 3), SendOutcome::Unknown);
        assert_eq!(outcome(ack, "i", "other", "t", 3), SendOutcome::Unknown);
        assert_eq!(outcome(ack, "i", "p", "t", 4), SendOutcome::Unknown);
        assert_eq!(outcome(ack, "i", "p", "other", 3), SendOutcome::Unknown);
        let error = br#"{"id":"i","error":{"code":"pocket_input_rejected","message":"rejected"}}"#;
        assert_eq!(outcome(error, "i", "p", "t", 3), SendOutcome::Rejected);
        assert_eq!(outcome(error, "j", "p", "t", 3), SendOutcome::Unknown);
        let duplicate=br#"{"id":"i","id":"i","result":{"type":"pocket_input_accepted","pane_id":"p","terminal_id":"t","accepted_bytes":3}}"#;
        assert_eq!(outcome(duplicate, "i", "p", "t", 3), SendOutcome::Unknown);
    }
}
