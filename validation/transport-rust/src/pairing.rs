//! In-memory v2 pairing state. A binding response is untrusted until reviewed.
use crate::{DeviceSigner, RemoteConfig, Result};
use base64ct::{Base64, Encoding};
use russh::keys::{Algorithm, HashAlg, PublicKey};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

pub trait KeyStore: Send + Sync {
    fn create(&self) -> Result<(String, String)>;
    fn public(&self, handle: &str) -> Result<String>;
    fn sign(&self, handle: &str, data: &[u8]) -> Result<Vec<u8>>;
    fn delete(&self, handle: &str) -> Result<()>;
}

#[derive(Serialize, Clone)]
struct Request {
    version: u8,
    #[serde(rename = "type")]
    kind: &'static str,
    request_id: String,
    device: String,
    public_key: String,
    account: String,
    host_key: String,
    issued_at: u64,
    expires_at: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Response {
    version: u8,
    #[serde(rename = "type")]
    kind: String,
    request_id: String,
    account: String,
    host_key: String,
    fingerprint: String,
    issued_at: u64,
    expires_at: u64,
    status: String,
    authorization_added: bool,
}

pub fn fingerprint(public: &str) -> Result<String> {
    let key = PublicKey::from_openssh(public).map_err(|_| "invalid_public_key")?;
    if key.algorithm() != Algorithm::Ed25519
        || key.to_openssh().map_err(|_| "invalid_public_key")? != public
    {
        return Err("invalid_public_key");
    }
    Ok(key.fingerprint(HashAlg::Sha256).to_string())
}
fn account_valid(s: &str) -> bool {
    let b = s.as_bytes();
    !b.is_empty()
        && b.len() <= 32
        && (b[0].is_ascii_lowercase() || b[0] == b'_')
        && b[1..]
            .iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_' || *c == b'-')
}
fn device_valid(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 48
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b' ' || c == b'-')
}
fn random_id() -> Result<String> {
    use ring::rand::SecureRandom;
    let mut bytes = [0u8; 16];
    ring::rand::SystemRandom::new()
        .fill(&mut bytes)
        .map_err(|_| "random_unavailable")?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

#[derive(PartialEq, Eq)]
struct Target {
    host: String,
    port: u16,
    user: String,
    host_key: String,
    socket: String,
    herdr: String,
    session: String,
}
impl Target {
    fn from_config(c: &RemoteConfig) -> Self {
        Self {
            host: c.host.clone(),
            port: c.port,
            user: c.username.clone(),
            host_key: c.expected_host_key.clone(),
            socket: c.socket_path.clone(),
            herdr: c.herdr_path.clone(),
            session: c.session.clone(),
        }
    }
}
pub struct Pairing {
    store: Arc<dyn KeyStore>,
    handle: String,
    request: Request,
    target: Option<Target>,
    pub state: &'static str,
    pub authorization: &'static str,
    pub authorization_added: Option<bool>,
}
impl Pairing {
    pub fn create(
        store: Arc<dyn KeyStore>,
        account: &str,
        host_public: &str,
        device: &str,
        now: u64,
    ) -> Result<Self> {
        if !account_valid(account) || !device_valid(device) {
            return Err("invalid_public_field");
        }
        let host_key = fingerprint(host_public)?;
        let request_id = random_id()?;
        let expires_at = now.checked_add(600).ok_or("invalid_time")?;
        let (handle, public_key) = store.create()?;
        if store.public(&handle).ok().as_deref() != Some(public_key.as_str())
            || fingerprint(&public_key).is_err()
        {
            let _ = store.delete(&handle);
            return Err("invalid_device_key");
        }
        Ok(Self {
            store,
            handle,
            request: Request {
                version: 2,
                kind: "pairing-public-key-request",
                request_id,
                device: device.into(),
                public_key,
                account: account.into(),
                host_key,
                issued_at: now,
                expires_at,
            },
            target: None,
            state: "awaiting-host",
            authorization: "unknown",
            authorization_added: None,
        })
    }
    pub fn bind_target(&mut self, config: &RemoteConfig) -> Result<()> {
        config.validate_pair_target()?;
        if self.target.is_some()
            || self.state != "awaiting-host"
            || config.username != self.request.account
            || fingerprint(&config.expected_host_key)? != self.request.host_key
        {
            return Err("pairing_target_mismatch");
        }
        self.target = Some(Target::from_config(config));
        Ok(())
    }
    pub fn request_json(&self) -> Result<String> {
        serde_json::to_string(&self.request).map_err(|_| "invalid_request")
    }
    pub fn public_fingerprint(&self) -> Result<String> {
        fingerprint(&self.request.public_key)
    }
    pub fn accept(&mut self, raw: &str, now: u64, reviewed: bool) -> Result<()> {
        if raw.is_empty() || raw.len() > 2048 || !reviewed {
            return Err("invalid_response");
        }
        let r: Response = serde_json::from_str(raw).map_err(|_| "invalid_response")?;
        if r.version != 2
            || r.kind != "pairing-binding-response"
            || r.request_id != self.request.request_id
            || r.account != self.request.account
            || r.host_key != self.request.host_key
            || r.fingerprint != self.public_fingerprint()?
            || r.issued_at > now
            || now >= r.expires_at
            || r.expires_at
                .checked_sub(r.issued_at)
                .filter(|ttl| *ttl > 0 && *ttl <= 600)
                .is_none()
        {
            return Err("invalid_response");
        }
        match r.status.as_str() {
            "revoked" if self.authorization != "revoked" => {
                self.authorization = "revoked";
                self.state = "revoked";
            }
            "authorized"
                if self.state == "awaiting-host"
                    && now < self.request.expires_at
                    && r.expires_at <= self.request.expires_at =>
            {
                self.authorization = "authorized";
                self.authorization_added = Some(r.authorization_added);
                self.state = "authorized-unverified";
            }
            _ => return Err("invalid_response_state"),
        }
        Ok(())
    }
    pub fn cancel(&mut self) {
        self.state = "cancelled";
    }
    pub fn delete_local(&self) -> Result<()> {
        self.store.delete(&self.handle)
    }
    pub fn begin(&mut self, config: &RemoteConfig) -> Result<(String, Arc<dyn DeviceSigner>)> {
        if !matches!(
            self.state,
            "authorized-unverified" | "waiting-connectivity" | "paired"
        ) || self.target.as_ref() != Some(&Target::from_config(config))
            || config.validate_pair_target().is_err()
            || self.store.public(&self.handle)? != self.request.public_key
        {
            return Err("pairing_target_mismatch");
        }
        self.state = "connecting";
        Ok((
            self.request.public_key.clone(),
            Arc::new(HandleSigner {
                store: self.store.clone(),
                handle: self.handle.clone(),
            }),
        ))
    }
    pub fn finish(&mut self, authenticated: bool) {
        if self.state == "connecting" {
            self.state = if authenticated {
                "paired"
            } else {
                "waiting-connectivity"
            };
        }
    }
}
struct HandleSigner {
    store: Arc<dyn KeyStore>,
    handle: String,
}
impl DeviceSigner for HandleSigner {
    fn sign(&self, data: &[u8]) -> std::result::Result<Vec<u8>, ()> {
        if data.len() > 65536 {
            return Err(());
        }
        self.store.sign(&self.handle, data).map_err(|_| ())
    }
}

/// Explicitly volatile test identity, never persisted or exported. Not device security.
#[cfg(any(target_os = "linux", target_os = "macos"))]
#[derive(Default)]
pub struct VolatileKeyStore(
    std::sync::Mutex<std::collections::HashMap<String, ring::signature::Ed25519KeyPair>>,
);
#[cfg(any(target_os = "linux", target_os = "macos"))]
impl KeyStore for VolatileKeyStore {
    fn create(&self) -> Result<(String, String)> {
        use ring::signature::KeyPair;
        let pkcs8 =
            ring::signature::Ed25519KeyPair::generate_pkcs8(&ring::rand::SystemRandom::new())
                .map_err(|_| "key_unavailable")?;
        let key = ring::signature::Ed25519KeyPair::from_pkcs8(pkcs8.as_ref())
            .map_err(|_| "key_unavailable")?;
        let mut blob = Vec::new();
        blob.extend_from_slice(&11u32.to_be_bytes());
        blob.extend_from_slice(b"ssh-ed25519");
        blob.extend_from_slice(&32u32.to_be_bytes());
        blob.extend_from_slice(key.public_key().as_ref());
        let public = format!("ssh-ed25519 {}", Base64::encode_string(&blob));
        let handle = random_id()?;
        self.0
            .lock()
            .map_err(|_| "key_unavailable")?
            .insert(handle.clone(), key);
        Ok((handle, public))
    }
    fn public(&self, handle: &str) -> Result<String> {
        use ring::signature::KeyPair;
        let keys = self.0.lock().map_err(|_| "key_unavailable")?;
        let key = keys.get(handle).ok_or("key_missing")?;
        let mut blob = Vec::new();
        blob.extend_from_slice(&11u32.to_be_bytes());
        blob.extend_from_slice(b"ssh-ed25519");
        blob.extend_from_slice(&32u32.to_be_bytes());
        blob.extend_from_slice(key.public_key().as_ref());
        Ok(format!("ssh-ed25519 {}", Base64::encode_string(&blob)))
    }
    fn sign(&self, handle: &str, data: &[u8]) -> Result<Vec<u8>> {
        if data.len() > 65536 {
            return Err("payload_too_large");
        }
        let keys = self.0.lock().map_err(|_| "key_unavailable")?;
        Ok(keys
            .get(handle)
            .ok_or("key_missing")?
            .sign(data)
            .as_ref()
            .to_vec())
    }
    fn delete(&self, handle: &str) -> Result<()> {
        self.0
            .lock()
            .map_err(|_| "key_unavailable")?
            .remove(handle)
            .ok_or("key_missing")?;
        Ok(())
    }
}

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
mod tests {
    use super::*;
    fn new_host() -> String {
        VolatileKeyStore::default().create().unwrap().1
    }
    fn response(p: &Pairing, status: &str) -> String {
        serde_json::json!({"version":2,"type":"pairing-binding-response","request_id":p.request.request_id,"account":p.request.account,"host_key":p.request.host_key,"fingerprint":p.public_fingerprint().unwrap(),"issued_at":101,"expires_at":600,"status":status,"authorization_added":true}).to_string()
    }
    fn config(host: &str) -> RemoteConfig {
        RemoteConfig {
            schema_version: 1,
            host: "127.0.0.1".into(),
            port: 22,
            username: "fixture-user".into(),
            expected_host_key: host.into(),
            private_key_pem: String::new(),
            socket_path: "/x/herdr/sessions/test/herdr.sock".into(),
            herdr_path: "/bin/herdr".into(),
            session: "test".into(),
            pane_id: String::new(),
            review_confirmed: true,
        }
    }
    #[test]
    fn review_target_expiration_and_replay_fail_closed() {
        let store = Arc::new(VolatileKeyStore::default());
        let host = new_host();
        let mut p = Pairing::create(store, "fixture-user", &host, "Pocket test", 100).unwrap();
        p.bind_target(&config(&host)).unwrap();
        let good = response(&p, "authorized");
        assert!(p.accept(&good, 101, false).is_err());
        assert!(
            p.accept(&good.replace("fixture-user", "other"), 101, true)
                .is_err()
        );
        assert!(
            p.accept(
                &good.replace("\"version\":2", "\"version\":2,\"version\":2"),
                101,
                true
            )
            .is_err()
        );
        assert!(
            p.accept(
                &good.replace("\"expires_at\":600", "\"expires_at\":701"),
                101,
                true
            )
            .is_err()
        );
        assert_eq!(p.state, "awaiting-host");
        p.accept(&good, 101, true).unwrap();
        assert_eq!(p.state, "authorized-unverified");
        assert!(p.accept(&good, 101, true).is_err());
        let mut wrong = config(&host);
        wrong.username = "other".into();
        assert!(p.begin(&wrong).is_err());
        assert!(p.begin(&config(&new_host())).is_err());
        let mut wrong_route = config(&host);
        wrong_route.host = "localhost".into();
        assert!(p.begin(&wrong_route).is_err());
        let (public, signer) = p.begin(&config(&host)).unwrap();
        assert_eq!(public, p.request.public_key);
        assert_eq!(signer.sign(b"abc").unwrap().len(), 64);
        p.finish(true);
        assert_eq!(p.state, "paired");
        assert!(p.begin(&config(&host)).is_ok());
        p.cancel();
        p.finish(true);
        assert_eq!(p.state, "cancelled");
    }
    #[test]
    fn cancelled_unknown_can_accept_only_matching_revocation() {
        let store = Arc::new(VolatileKeyStore::default());
        let host = new_host();
        let mut p = Pairing::create(store, "fixture-user", &host, "Pocket test", 100).unwrap();
        let authorized = response(&p, "authorized");
        let revoked = response(&p, "revoked");
        p.cancel();
        assert!(p.accept(&authorized, 101, true).is_err());
        p.accept(&revoked, 101, true).unwrap();
        assert_eq!(p.authorization, "revoked");
        assert!(p.accept(&revoked, 101, true).is_err());
        assert!(p.begin(&config(&host)).is_err());
    }
    #[test]
    fn deleted_handle_never_recreates_key() {
        let store = VolatileKeyStore::default();
        let (handle, _) = store.create().unwrap();
        store.delete(&handle).unwrap();
        assert!(store.public(&handle).is_err());
        assert!(store.sign(&handle, b"x").is_err());
    }
}
