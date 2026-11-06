//! Public status only. Secret bytes are never returned to the webview.
use serde::Serialize;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
#[derive(Default)]
pub struct Operations(Arc<AtomicBool>);
pub struct Lease(Arc<AtomicBool>);
impl Drop for Lease {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}
impl Operations {
    pub fn enter(&self) -> Result<Lease, String> {
        self.0
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| "network_identity_busy")?;
        Ok(Lease(self.0.clone()))
    }
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    pub supported: bool,
    pub available: bool,
    pub present: bool,
    pub mode: Option<String>,
    pub handle: Option<String>,
}
impl Status {
    #[cfg(target_os = "android")]
    pub fn from_metadata(metadata: Option<Metadata>) -> Self {
        Self {
            supported: true,
            available: true,
            present: metadata.is_some(),
            mode: metadata.as_ref().map(|m| m.mode.clone()),
            handle: metadata.map(|m| m.handle),
        }
    }
}
impl Status {
    pub fn unsupported() -> Self {
        Self {
            supported: false,
            available: false,
            present: false,
            mode: None,
            handle: None,
        }
    }
}
#[cfg(any(test, target_os = "android"))]
#[derive(Clone)]
pub struct Metadata {
    pub mode: String,
    pub handle: String,
}
#[cfg(any(test, target_os = "android"))]
#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IdentityReply {
    pub present: bool,
    pub mode: Option<String>,
    pub supported: Option<bool>,
    pub handle: Option<String>,
    pub instance_id: Option<String>,
    pub profile_id: Option<String>,
    pub provider: Option<String>,
}
#[cfg(any(test, target_os = "android"))]
pub fn checked_metadata(
    reply: IdentityReply,
    provider: &str,
    profile_id: &str,
) -> Result<Option<Metadata>, String> {
    if !matches!(provider, "easytier" | "tailscale") {
        return Err("network_identity_provider_unavailable".into());
    }
    if reply.supported == Some(false) {
        return Err("network_identity_unsupported".into());
    }
    if !reply.present {
        return Ok(None);
    }
    let (Some(mode), Some(handle), Some(instance)) = (reply.mode, reply.handle, reply.instance_id)
    else {
        return Err("network_identity_unavailable".into());
    };
    let valid_mode = match provider {
        "tailscale" => mode == "DEVICE_STATE",
        _ => matches!(mode.as_str(), "PRIVATE" | "PUBLIC_NO_SECRET"),
    };
    if reply.provider.as_deref() != Some(provider)
        || reply.profile_id.as_deref() != Some(profile_id)
        || !valid_mode
        || !valid_handle(&handle)
        || !valid_handle(&instance)
    {
        return Err("network_identity_unavailable".into());
    }
    Ok(Some(Metadata { mode, handle }))
}
pub fn valid_handle(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 36
        && b.iter().enumerate().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => *c == b'-',
            14 => *c == b'4',
            19 => matches!(*c, b'8' | b'9' | b'a' | b'b'),
            _ => c.is_ascii_digit() || (b'a'..=b'f').contains(c),
        })
}
pub fn validate_expected_handle(action: &str, handle: Option<&str>) -> Result<(), String> {
    match (action, handle) {
        ("create", None) => Ok(()),
        ("delete", Some(h)) if valid_handle(h) => Ok(()),
        _ => Err("invalid_network_identity".into()),
    }
}
pub fn validate_input(mode: &str, secret: &str) -> Result<(), String> {
    if secret.len() > 1024
        || secret.contains('\0')
        || !matches!(
            (mode, secret.is_empty()),
            ("PRIVATE", false) | ("PUBLIC_NO_SECRET", true)
        )
    {
        return Err("invalid_network_identity".into());
    }
    Ok(())
}
pub fn validate_provider_input(
    provider: crate::networks::Provider,
    mode: &str,
    secret: &str,
) -> Result<(), String> {
    match provider {
        crate::networks::Provider::Easytier => validate_input(mode, secret),
        crate::networks::Provider::Tailscale if mode == "DEVICE_STATE" && secret.is_empty() => {
            Ok(())
        }
        _ => Err("invalid_network_identity".into()),
    }
}
#[cfg(any(test, target_os = "android"))]
pub fn validate_runtime_mode(
    provider: crate::networks::Provider,
    mode: &str,
) -> Result<(), String> {
    match (provider, mode) {
        (crate::networks::Provider::Easytier, "PRIVATE")
        | (crate::networks::Provider::Tailscale, "DEVICE_STATE") => Ok(()),
        _ => Err("network_identity_mode_unsupported".into()),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identity_ipc_reply_must_match_provider_profile_and_device_state_mode() {
        let raw = serde_json::json!({"present":true,"provider":"tailscale","profileId":"a".repeat(32),"mode":"DEVICE_STATE","handle":"11111111-1111-4111-8111-111111111111","instanceId":"22222222-2222-4222-8222-222222222222"});
        assert!(
            checked_metadata(
                serde_json::from_value(raw.clone()).unwrap(),
                "tailscale",
                &"a".repeat(32)
            )
            .unwrap()
            .is_some()
        );
        assert!(
            checked_metadata(
                serde_json::from_value(raw.clone()).unwrap(),
                "easytier",
                &"a".repeat(32)
            )
            .is_err()
        );
        assert!(
            checked_metadata(
                serde_json::from_value(raw.clone()).unwrap(),
                "tailscale",
                &"b".repeat(32)
            )
            .is_err()
        );
        for (field, value) in [
            ("mode", "PRIVATE"),
            ("handle", "invalid"),
            ("instanceId", "invalid"),
        ] {
            let mut changed = raw.clone();
            changed[field] = value.into();
            assert!(
                checked_metadata(
                    serde_json::from_value(changed).unwrap(),
                    "tailscale",
                    &"a".repeat(32)
                )
                .is_err()
            );
        }
        let mut secret = raw;
        secret["fullStateStore"] = "must never cross IPC".into();
        assert!(serde_json::from_value::<IdentityReply>(secret).is_err());
    }
    #[test]
    fn tailscale_has_no_authkey_secret_or_easytier_mode() {
        use crate::networks::Provider;
        assert!(validate_provider_input(Provider::Tailscale, "DEVICE_STATE", "").is_ok());
        for (mode, secret) in [
            ("DEVICE_STATE", "key"),
            ("PRIVATE", "key"),
            ("PUBLIC_NO_SECRET", ""),
            ("AUTH_KEY", ""),
        ] {
            assert!(validate_provider_input(Provider::Tailscale, mode, secret).is_err());
        }
        assert!(validate_provider_input(Provider::Easytier, "DEVICE_STATE", "").is_err());
        assert!(validate_runtime_mode(Provider::Tailscale, "DEVICE_STATE").is_ok());
        assert!(validate_runtime_mode(Provider::Tailscale, "PRIVATE").is_err());
        assert!(validate_runtime_mode(Provider::Easytier, "DEVICE_STATE").is_err());
    }
    #[test]
    fn modes_and_secret_limits_are_explicit() {
        assert!(validate_input("PRIVATE", "secret").is_ok());
        assert!(validate_input("PUBLIC_NO_SECRET", "").is_ok());
        for (mode, secret) in [
            ("PRIVATE", ""),
            ("PUBLIC_NO_SECRET", "secret"),
            ("UNKNOWN", ""),
        ] {
            assert!(validate_input(mode, secret).is_err());
        }
        assert!(validate_input("PRIVATE", &"x".repeat(1025)).is_err());
        assert!(validate_input("PRIVATE", "a\0b").is_err());
        assert!(validate_input("PRIVATE", &"中".repeat(341)).is_ok());
        assert!(validate_input("PRIVATE", &"中".repeat(342)).is_err());
    }
    #[test]
    fn delete_requires_frozen_valid_uuid() {
        let a = "11111111-1111-4111-8111-111111111111";
        assert!(validate_expected_handle("delete", Some(a)).is_ok());
        assert!(validate_expected_handle("delete", None).is_err());
        assert!(validate_expected_handle("delete", Some("not-a-handle")).is_err());
        assert!(validate_expected_handle("create", Some(a)).is_err());
    }
    #[test]
    fn operations_are_serial_and_release_after_unknown_result() {
        let a = Operations::default();
        let lease = a.enter().unwrap();
        assert!(a.enter().is_err());
        drop(lease);
        assert!(a.enter().is_ok());
    }
}
