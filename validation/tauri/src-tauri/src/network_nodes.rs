//! Explicit managed-node lifecycle. Public bindings never authorize another attempt.
use crate::networks::{NetworkProfile, Provider, Settings};
use herdr_readonly_transport::mobile_nodes::{Binding, BindingProvider, State};
#[cfg(any(test, target_os = "android"))]
use herdr_readonly_transport::{
    Cancellation,
    mobile_nodes::{MobileNodeService, NodeAttempt},
};
use serde::Serialize;
#[cfg(any(test, target_os = "android"))]
use std::collections::HashMap;
#[cfg(any(test, target_os = "android"))]
use std::sync::Mutex;
#[cfg(any(test, target_os = "android"))]
use std::{sync::Arc, time::Duration};

#[derive(Default)]
pub struct Nodes {
    #[cfg(any(test, target_os = "android"))]
    service: MobileNodeService,
    #[cfg(any(test, target_os = "android"))]
    reviews: Mutex<Reviews<NodeAttempt>>,
    #[cfg(any(test, target_os = "android"))]
    starts: Mutex<HashMap<String, Cancellation>>,
}
// Cancelled admission retains its host slot until the original future drops.
// The shared runtime independently retains native resources until real close.
#[cfg(any(test, target_os = "android"))]
struct StartSlot<'a> {
    slots: &'a Mutex<HashMap<String, Cancellation>>,
    id: String,
}
#[cfg(any(test, target_os = "android"))]
impl<'a> StartSlot<'a> {
    fn reserve(
        slots: &'a Mutex<HashMap<String, Cancellation>>,
        id: &str,
        cancel: Cancellation,
    ) -> Result<Self, String> {
        let mut entries = slots.lock().map_err(|_| "state_unavailable")?;
        if entries.contains_key(id) {
            return Err("mobile_node_busy".into());
        }
        if entries.len() >= 32 {
            return Err("mobile_node_history_capacity".into());
        }
        entries.insert(id.into(), cancel);
        Ok(Self {
            slots,
            id: id.into(),
        })
    }
}
#[cfg(any(test, target_os = "android"))]
impl Drop for StartSlot<'_> {
    fn drop(&mut self) {
        if let Ok(mut entries) = self.slots.lock() {
            if let Some(cancel) = entries.remove(&self.id) {
                cancel.cancel();
            }
        }
    }
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct View {
    state: &'static str,
    binding: Option<Binding>,
    auth_url: Option<String>,
    review_token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    device_online: Option<bool>,
}
fn wire_state(state: State) -> &'static str {
    match state {
        State::Starting => "starting",
        State::EngineStarted => "engine-started",
        State::NeedsLogin => "needs-login",
        State::NeedsMachineAuth => "needs-machine-auth",
        State::Running => "running",
        State::ZeroTierRequesting => "zero-tier-requesting",
        State::ZeroTierConfigured => "zero-tier-configured",
        State::ZeroTierDenied => "zero-tier-denied",
        State::ZeroTierNotFound => "zero-tier-not-found",
        State::ZeroTierPortError => "zero-tier-port-error",
        State::ZeroTierClientOld => "zero-tier-client-old",
        State::ZeroTierAuthRequired => "zero-tier-auth-required",
        State::ZeroTierUnknown => "zero-tier-unknown",
        State::Closing => "closing",
        State::Stopped => "stopped",
    }
}
fn view(s: herdr_readonly_transport::mobile_nodes::Snapshot) -> View {
    View {
        state: wire_state(s.state),
        binding: Some(s.binding),
        auth_url: None,
        review_token: None,
        device_online: s.device_online,
    }
}
fn ready_view(
    current: Option<herdr_readonly_transport::mobile_nodes::Snapshot>,
    initialized: bool,
) -> View {
    if current.as_ref().is_some_and(|s| s.state != State::Stopped) {
        return view(current.unwrap());
    }
    if !initialized {
        return View {
            state: "unavailable",
            binding: None,
            auth_url: None,
            review_token: None,
            device_online: None,
        };
    }
    current.map(view).unwrap_or(View {
        state: "stopped",
        binding: None,
        auth_url: None,
        review_token: None,
        device_online: None,
    })
}
/// This book owns private attempt capabilities. Tokens are process-local review IDs,
/// never native attempt numbers. A stale async result cannot recreate a retired review.
#[cfg(any(test, target_os = "android"))]
#[derive(Clone)]
struct Review<T> {
    binding: Binding,
    attempt: T,
    token: String,
    url: Option<String>,
}
#[cfg(any(test, target_os = "android"))]
struct Reviews<T> {
    next: u64,
    items: HashMap<String, Review<T>>,
}
#[cfg(any(test, target_os = "android"))]
impl<T> Default for Reviews<T> {
    fn default() -> Self {
        Self {
            next: 0,
            items: HashMap::new(),
        }
    }
}
#[cfg(any(test, target_os = "android"))]
impl<T: Clone> Reviews<T> {
    fn retire(&mut self, id: &str) {
        self.items.remove(id);
    }
    fn reserve(&mut self, binding: Binding, attempt: T) -> Result<String, String> {
        if self.items.len() >= 32 && !self.items.contains_key(binding.profile_id()) {
            return Err("network_login_review_limit".into());
        }
        self.next = self
            .next
            .checked_add(1)
            .ok_or("network_login_review_limit")?;
        let token = format!("review-{:016x}", self.next);
        self.items.insert(
            binding.profile_id().into(),
            Review {
                binding,
                attempt,
                token: token.clone(),
                url: None,
            },
        );
        Ok(token)
    }
    fn get(&self, binding: &Binding) -> Result<Review<T>, String> {
        self.items
            .get(binding.profile_id())
            .filter(|r| r.binding == *binding)
            .cloned()
            .ok_or("network_login_review_stale".into())
    }
    fn publish(
        &mut self,
        binding: &Binding,
        token: &str,
        url: Option<String>,
    ) -> Result<(), String> {
        let review = self
            .items
            .get_mut(binding.profile_id())
            .filter(|r| r.binding == *binding && r.token == token)
            .ok_or("network_login_review_stale")?;
        if url.as_deref().is_some_and(|s| !reviewed_auth_url(s)) {
            return Err("network_auth_url_invalid".into());
        }
        review.url = url;
        Ok(())
    }
    fn checked(&self, binding: &Binding, token: &str, url: &str) -> Result<Review<T>, String> {
        let r = self.get(binding)?;
        if r.token != token || r.url.as_deref() != Some(url) || !reviewed_auth_url(url) {
            return Err("network_login_review_stale".into());
        }
        Ok(r)
    }
}
#[cfg(any(test, target_os = "android"))]
pub fn reviewed_auth_url(value: &str) -> bool {
    if value.is_empty()
        || value.len() > 4096
        || !value.is_ascii()
        || value.bytes().any(|b| b <= 32 || b == 127 || b == b'\\')
    {
        return false;
    }
    url::Url::parse(value).is_ok_and(|u| {
        u.scheme() == "https"
            && u.has_host()
            && u.username().is_empty()
            && u.password().is_none()
            && u.fragment().is_none()
    })
}
pub fn provider_name(provider: Provider) -> Result<&'static str, String> {
    match provider {
        Provider::Easytier => Ok("easytier"),
        Provider::Tailscale => Ok("tailscale"),
        _ => Err("overlay_provider_unavailable".into()),
    }
}
pub fn provider_available(provider: Provider) -> bool {
    match provider {
        Provider::Easytier => cfg!(all(target_os = "android", feature = "network-easytier")),
        Provider::Tailscale => cfg!(all(target_os = "android", feature = "network-tailscale")),
        _ => false,
    }
}
#[cfg(any(test, target_os = "android"))]
fn initialized(provider: Provider) -> bool {
    provider_available(provider)
        && match provider {
            Provider::Easytier => herdr_android_network_source::is_initialized(),
            Provider::Tailscale => herdr_android_network_source::is_tailscale_initialized(),
            _ => false,
        }
}
pub fn binding_for(profile: &NetworkProfile, handle: String) -> Result<Binding, String> {
    if !crate::network_identity::valid_handle(&handle) {
        return Err("invalid_network_identity".into());
    }
    match (&profile.provider, &profile.settings) {
        (Provider::Easytier, Settings::Easytier { network_name, .. }) => Binding::new(
            profile.id.clone(),
            profile.revision,
            network_name.clone(),
            handle,
        ),
        (
            Provider::Tailscale,
            Settings::Tailscale {
                control_url,
                hostname,
            },
        ) => {
            let settings = herdr_readonly_transport::tailscale_settings::TailscaleSettings::new(
                control_url,
                hostname,
            )
            .map_err(str::to_string)?;
            Binding::with_provider(
                BindingProvider::Tailscale,
                profile.id.clone(),
                profile.revision,
                settings.network_name().into(),
                handle,
            )
        }
        _ => return Err("overlay_provider_unavailable".into()),
    }
    .map_err(str::to_string)
}
pub async fn commit_after_stop<T>(
    stop: impl std::future::Future<Output = Result<(), String>>,
    commit: impl FnOnce() -> Result<T, String>,
) -> Result<T, String> {
    stop.await?;
    commit()
}
#[derive(Debug, PartialEq, Eq)]
pub enum RouteKind {
    System,
    Overlay,
}
pub fn select_route(profile: Option<&NetworkProfile>) -> Result<RouteKind, String> {
    match profile {
        None => Ok(RouteKind::System),
        Some(p) if provider_available(p.provider) => Ok(RouteKind::Overlay),
        _ => Err("overlay_provider_unavailable".into()),
    }
}
impl Nodes {
    pub async fn status(
        &self,
        _app: &tauri::AppHandle,
        profile: &NetworkProfile,
    ) -> Result<View, String> {
        #[cfg(any(test, target_os = "android"))]
        {
            let current = self
                .service
                .status_profile(&profile.id)
                .await
                .map_err(str::to_string)?;
            Ok(ready_view(current, initialized(profile.provider)))
        }
        #[cfg(not(any(test, target_os = "android")))]
        {
            let _ = profile;
            Ok(ready_view(None, false))
        }
    }
    pub async fn stop_profile(&self, id: &str) -> Result<(), String> {
        #[cfg(any(test, target_os = "android"))]
        {
            self.retire(id)?;
            if let Some(s) = self
                .service
                .status_profile(id)
                .await
                .map_err(str::to_string)?
            {
                let stopped = self
                    .service
                    .stop(&s.binding, Duration::from_secs(10))
                    .await
                    .map_err(str::to_string)?;
                if stopped.state != State::Stopped {
                    return Err("mobile_node_cleanup_pending".into());
                }
            }
        }
        let _ = id;
        Ok(())
    }
    #[cfg(any(test, target_os = "android"))]
    fn retire(&self, id: &str) -> Result<(), String> {
        self.reviews
            .lock()
            .map_err(|_| "state_unavailable")?
            .retire(id);
        if let Some(cancel) = self.starts.lock().map_err(|_| "state_unavailable")?.get(id) {
            cancel.cancel();
        }
        Ok(())
    }
    pub async fn stop_exact(&self, id: &str, binding: Binding) -> Result<(), String> {
        if binding.profile_id() != id {
            return Err("mobile_node_binding_mismatch".into());
        }
        #[cfg(any(test, target_os = "android"))]
        {
            // Reject a foreign active binding before revoking its start/review.
            self.service
                .capture_attempt(&binding)
                .map_err(str::to_string)?;
            self.retire(id)?;
            let stopped = self
                .service
                .stop(&binding, Duration::from_secs(10))
                .await
                .map_err(str::to_string)?;
            if stopped.state != State::Stopped {
                return Err("mobile_node_cleanup_pending".into());
            }
            Ok(())
        }
        #[cfg(not(any(test, target_os = "android")))]
        {
            Err("overlay_provider_unavailable".into())
        }
    }
    #[cfg(any(test, target_os = "android"))]
    pub async fn start(&self, profile: &NetworkProfile, handle: String) -> Result<(), String> {
        if !initialized(profile.provider) {
            return Err("overlay_provider_unavailable".into());
        }
        self.retire(&profile.id)?;
        let binding = binding_for(profile, handle.clone())?;
        let cancel = Cancellation::default();
        let _slot = StartSlot::reserve(&self.starts, &profile.id, cancel.clone())?;
        let result = async {
            match (&profile.provider, &profile.settings) {
                (
                    Provider::Easytier,
                    Settings::Easytier {
                        network_name,
                        peers,
                    },
                ) => {
                    let source = herdr_android_network_source::AndroidSecureConfigSource::new(
                        profile.id.clone(),
                        profile.revision,
                        network_name.clone(),
                        handle,
                        peers.clone(),
                    )
                    .map_err(|_| "network_identity_unavailable")?;
                    self.service
                        .start(binding, Arc::new(source), Duration::from_secs(10), cancel)
                        .await
                }
                (
                    Provider::Tailscale,
                    Settings::Tailscale {
                        control_url,
                        hostname,
                    },
                ) => {
                    let s = herdr_readonly_transport::tailscale_settings::TailscaleSettings::new(
                        control_url,
                        hostname,
                    )
                    .map_err(|_| "invalid_network_binding")?;
                    let source = herdr_android_network_source::AndroidTailscaleSource::new(
                        profile.id.clone(),
                        profile.revision,
                        s.network_name().into(),
                        handle,
                        s.hostname().into(),
                        s.control_url().into(),
                    )
                    .map_err(|_| "network_identity_unavailable")?;
                    self.service
                        .start_tailscale(binding, Arc::new(source), Duration::from_secs(10), cancel)
                        .await
                }
                _ => return Err("overlay_provider_unavailable"),
            }
        }
        .await;
        result.map(|_| ()).map_err(str::to_string)
    }
    pub async fn route(
        &self,
        app: &tauri::AppHandle,
        profile: &NetworkProfile,
    ) -> Result<
        (
            Box<dyn herdr_readonly_transport::transport::Dialer>,
            Binding,
        ),
        String,
    > {
        if !provider_available(profile.provider) {
            return Err("overlay_provider_unavailable".into());
        }
        #[cfg(any(test, target_os = "android"))]
        {
            let app = app.clone();
            let id = profile.id.clone();
            let provider = provider_name(profile.provider)?;
            let identity = tauri::async_runtime::spawn_blocking(move || {
                crate::android_keys::network_identity(
                    &app,
                    "networkIdentityStatus",
                    &id,
                    provider,
                    "",
                    "",
                )
            })
            .await
            .map_err(|_| "network_identity_unavailable")??
            .ok_or("network_identity_missing")?;
            crate::network_identity::validate_runtime_mode(profile.provider, &identity.mode)?;
            let binding = binding_for(profile, identity.handle)?;
            let dialer = self
                .service
                .dialer(&binding, Duration::from_secs(10))
                .map_err(str::to_string)?;
            Ok((Box::new(dialer), binding))
        }
        #[cfg(not(any(test, target_os = "android")))]
        {
            let _ = app;
            Err("overlay_provider_unavailable".into())
        }
    }
    #[cfg(any(test, target_os = "android"))]
    pub async fn login(&self, binding: Binding) -> Result<View, String> {
        if binding.provider() != &BindingProvider::Tailscale {
            return Err("overlay_provider_unavailable".into());
        }
        let attempt = self
            .service
            .capture_attempt(&binding)
            .map_err(str::to_string)?
            .ok_or("network_login_review_stale")?;
        let token = self
            .reviews
            .lock()
            .map_err(|_| "state_unavailable")?
            .reserve(binding.clone(), attempt.clone())?;
        let result = self
            .service
            .begin_login_attempt(&attempt, Duration::from_secs(10), Cancellation::default())
            .await
            .map_err(str::to_string)?;
        self.publish_login(result, &token)
    }
    #[cfg(any(test, target_os = "android"))]
    fn publish_login(
        &self,
        result: herdr_readonly_transport::mobile_nodes::LoginSnapshot,
        token: &str,
    ) -> Result<View, String> {
        let mut reviews = self.reviews.lock().map_err(|_| "state_unavailable")?;
        let url = if matches!(result.state, State::NeedsLogin | State::NeedsMachineAuth) {
            result.auth_url
        } else {
            None
        };
        reviews.publish(&result.binding, token, url.clone())?;
        Ok(View {
            state: wire_state(result.state),
            binding: Some(result.binding),
            review_token: url.as_ref().map(|_| token.into()),
            device_online: None,
            auth_url: url,
        })
    }
    pub async fn login_status(
        &self,
        profile: &NetworkProfile,
        binding: &Binding,
    ) -> Result<View, String> {
        #[cfg(any(test, target_os = "android"))]
        {
            let review = self
                .reviews
                .lock()
                .map_err(|_| "state_unavailable")?
                .get(binding)
                .ok();
            if let Some(review) = review {
                let result = self
                    .service
                    .login_status_attempt(
                        &review.attempt,
                        Duration::from_secs(10),
                        Cancellation::default(),
                    )
                    .await
                    .map_err(str::to_string)?;
                return self.publish_login(result, &review.token);
            }
            let _ = profile;
            let snapshot = self.service.status(binding).await.map_err(str::to_string)?;
            Ok(view(snapshot))
        }
        #[cfg(not(any(test, target_os = "android")))]
        {
            let _ = (profile, binding);
            Err("overlay_provider_unavailable".into())
        }
    }
    pub async fn open_auth(
        &self,
        app: &tauri::AppHandle,
        binding: &Binding,
        token: &str,
        url: &str,
    ) -> Result<(), String> {
        #[cfg(any(test, target_os = "android"))]
        {
            let reviewed = self
                .reviews
                .lock()
                .map_err(|_| "state_unavailable")?
                .checked(binding, token, url)?;
            let current = self
                .service
                .login_status_attempt(
                    &reviewed.attempt,
                    Duration::from_secs(10),
                    Cancellation::default(),
                )
                .await
                .map_err(str::to_string)?;
            if current.binding != *binding
                || !matches!(current.state, State::NeedsLogin | State::NeedsMachineAuth)
                || current.auth_url.as_deref() != Some(url)
            {
                return Err("network_login_review_stale".into());
            }
            // No await between final review check and dispatch to the native opener.
            let reviews = self.reviews.lock().map_err(|_| "state_unavailable")?;
            reviews.checked(binding, token, url)?;
            crate::android_keys::open_network_auth(app, url)
        }
        #[cfg(not(any(test, target_os = "android")))]
        {
            let _ = (app, binding, token, url);
            Err("overlay_provider_unavailable".into())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn ts_profile() -> NetworkProfile {
        NetworkProfile {
            id: "a".repeat(32),
            label: "TS".into(),
            provider: Provider::Tailscale,
            enabled: true,
            revision: 1,
            settings: Settings::Tailscale {
                control_url: "".into(),
                hostname: "".into(),
            },
        }
    }
    fn ts_binding() -> Binding {
        binding_for(&ts_profile(), "11111111-1111-4111-8111-111111111111".into()).unwrap()
    }
    #[test]
    fn tailscale_binding_uses_shared_config_hash_and_exact_identity() {
        let p = ts_profile();
        let a = ts_binding();
        let mut explicit = p.clone();
        explicit.settings = Settings::Tailscale {
            control_url: "https://controlplane.tailscale.com".into(),
            hostname: "herdr-pocket".into(),
        };
        assert_eq!(binding_for(&explicit, a.identity_ref().into()).unwrap(), a);
        assert_eq!(a.provider(), &BindingProvider::Tailscale);
        assert!(a.network_name().starts_with("ts1:"));
        explicit.settings = Settings::Tailscale {
            control_url: "https://control.example.test".into(),
            hostname: "herdr-pocket".into(),
        };
        assert_ne!(binding_for(&explicit, a.identity_ref().into()).unwrap(), a);
        assert_ne!(
            binding_for(&p, "22222222-2222-4222-8222-222222222222".into()).unwrap(),
            a
        );
        explicit.provider = Provider::Easytier;
        assert!(binding_for(&explicit, a.identity_ref().into()).is_err());
    }
    #[test]
    fn retired_login_result_cannot_publish_or_open_same_binding_restart() {
        let b = ts_binding();
        let url = "https://login.example.test/a?token=opaque";
        let mut book = Reviews::default();
        let old = book.reserve(b.clone(), 7u64).unwrap();
        book.publish(&b, &old, Some(url.into())).unwrap();
        book.retire(b.profile_id());
        let new = book.reserve(b.clone(), 8).unwrap();
        assert_ne!(old, new);
        assert!(book.publish(&b, &old, Some(url.into())).is_err());
        assert!(book.checked(&b, &old, url).is_err());
        assert!(book.checked(&b, &new, url).is_err());
        book.publish(&b, &new, Some(url.into())).unwrap();
        assert_eq!(book.checked(&b, &new, url).unwrap().attempt, 8);
        assert!(
            book.checked(&b, &new, "https://login.example.test/replaced")
                .is_err()
        );
        let mut other = b.clone();
        other = Binding::with_provider(
            BindingProvider::Tailscale,
            other.profile_id().into(),
            2,
            other.network_name().into(),
            other.identity_ref().into(),
        )
        .unwrap();
        assert!(book.get(&other).is_err());
    }
    #[test]
    fn review_url_is_https_bounded_and_cleared_without_reusing_token() {
        let b = ts_binding();
        let mut book = Reviews::default();
        let t = book.reserve(b.clone(), 1).unwrap();
        for url in [
            "http://login.test",
            "https://u:p@login.test",
            "https://login.test#fragment",
            "https://login.test/\\x",
            "https://login.test/\n",
        ] {
            assert!(!reviewed_auth_url(url));
            assert!(book.publish(&b, &t, Some(url.into())).is_err());
        }
        assert!(!reviewed_auth_url(&format!(
            "https://login.test/{}",
            "a".repeat(4096)
        )));
        book.publish(&b, &t, Some("https://login.test/".into()))
            .unwrap();
        book.publish(&b, &t, None).unwrap();
        assert!(book.checked(&b, &t, "https://login.test/").is_err());
        let serialized =
            serde_json::to_value(view(herdr_readonly_transport::mobile_nodes::Snapshot {
                binding: b,
                state: State::Running,
                device_online: None,
            }))
            .unwrap();
        assert!(serialized["authUrl"].is_null());
        assert!(serialized["reviewToken"].is_null());
    }
    #[test]
    fn review_capacity_retains_existing_owner_and_never_reuses_tokens() {
        let mut book = Reviews::default();
        for i in 0..32 {
            let mut p = ts_profile();
            p.id = format!("{i:032x}");
            book.reserve(
                binding_for(&p, "11111111-1111-4111-8111-111111111111".into()).unwrap(),
                i,
            )
            .unwrap();
        }
        let mut p = ts_profile();
        p.id = "f".repeat(32);
        assert!(
            book.reserve(
                binding_for(&p, "11111111-1111-4111-8111-111111111111".into()).unwrap(),
                33
            )
            .is_err()
        );
    }
    #[cfg(not(target_os = "android"))]
    #[tokio::test]
    async fn host_cannot_start_or_login_without_native_provider_context() {
        let nodes = Nodes::default();
        assert_eq!(
            nodes
                .start(&ts_profile(), ts_binding().identity_ref().into())
                .await,
            Err("overlay_provider_unavailable".into())
        );
        assert!(nodes.login(ts_binding()).await.is_err());
        assert!(nodes.reviews.lock().unwrap().items.is_empty());
        assert!(nodes.starts.lock().unwrap().is_empty());
    }
    #[test]
    fn tailscale_binding_retirement_preserves_other_provider_identity_and_tabs() {
        let ts = ts_binding();
        let et = Binding::new(
            ts.profile_id().into(),
            ts.profile_revision(),
            ts.network_name().into(),
            ts.identity_ref().into(),
        )
        .unwrap();
        let other =
            binding_for(&ts_profile(), "22222222-2222-4222-8222-222222222222".into()).unwrap();
        let mut sessions = crate::remote_sessions::Sessions::default();
        let (g, a) = sessions
            .begin("ts-pane-a", 1, Some("host".into()), Some(ts.clone()))
            .unwrap();
        sessions.claim("ts-pane-a", 1, g).unwrap();
        let (_, b) = sessions
            .begin("ts-pane-b", 1, Some("host".into()), Some(ts.clone()))
            .unwrap();
        let (_, c) = sessions
            .begin("other-provider", 1, Some("host-et".into()), Some(et))
            .unwrap();
        let (_, d) = sessions
            .begin(
                "other-device-state",
                1,
                Some("host-other".into()),
                Some(other),
            )
            .unwrap();
        sessions.cancel_binding(&ts);
        assert!(a.is_cancelled() && b.is_cancelled());
        assert!(!c.is_cancelled() && !d.is_cancelled());
        assert!(!sessions.finish("ts-pane-a", 2, g));
        assert!(sessions.get("ts-pane-a").is_some());
    }
    #[test]
    fn cancelled_start_slot_stays_owned_until_its_future_drops() {
        let slots = Mutex::default();
        let a = Cancellation::default();
        let first = StartSlot::reserve(&slots, "a", a.clone()).unwrap();
        a.cancel();
        assert!(StartSlot::reserve(&slots, "a", Cancellation::default()).is_err());
        let b = Cancellation::default();
        let other = StartSlot::reserve(&slots, "b", b.clone()).unwrap();
        assert!(!b.is_cancelled());
        drop(first);
        let replacement = StartSlot::reserve(&slots, "a", Cancellation::default()).unwrap();
        assert!(!b.is_cancelled());
        drop(replacement);
        drop(other);
        assert!(b.is_cancelled());
    }
    #[test]
    fn tailscale_login_review_rechecks_catalog_revision_and_derived_binding() {
        struct Temp(std::path::PathBuf);
        impl Drop for Temp {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        let temp = Temp(std::env::temp_dir().join(format!(
            "herdr-tauri-ts-review-{}",
            herdr_readonly_transport::pairing::random_public_id().unwrap()
        )));
        let hosts = crate::hosts::Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        let old = hosts.networks().unwrap();
        let mut p = ts_profile();
        p.id = "0".repeat(32);
        hosts.save_network(p, &old.revision, None, &[]).unwrap();
        let catalog = hosts.networks().unwrap();
        let mut p = catalog.profiles[0].clone();
        let b = binding_for(&p, ts_binding().identity_ref().into()).unwrap();
        assert!(
            crate::reviewed_login_binding(&hosts, &p.id, 1, &catalog.revision, &[], &b).is_ok()
        );
        assert!(crate::reviewed_login_binding(&hosts, &p.id, 1, "stale-catalog", &[], &b).is_err());
        assert!(
            crate::reviewed_login_binding(
                &hosts,
                &p.id,
                1,
                &catalog.revision,
                &["foreign-host".into()],
                &b
            )
            .is_err()
        );
        p.settings = Settings::Tailscale {
            control_url: "https://control.example.test".into(),
            hostname: "new-phone".into(),
        };
        hosts
            .save_network(p.clone(), &catalog.revision, Some(1), &[])
            .unwrap();
        let latest = hosts.networks().unwrap();
        assert!(
            crate::reviewed_login_binding(&hosts, &p.id, 2, &latest.revision, &[], &b).is_err()
        );
        let current = binding_for(&latest.profiles[0], b.identity_ref().into()).unwrap();
        assert!(
            crate::reviewed_login_binding(&hosts, &p.id, 2, &latest.revision, &[], &current)
                .is_ok()
        );
    }
    #[test]
    fn default_route_never_falls_back_for_bound_profiles() {
        use crate::networks::{NetworkProfile, Provider, Settings};
        assert_eq!(select_route(None), Ok(RouteKind::System));
        let mut p = NetworkProfile {
            id: "a".repeat(32),
            label: "team".into(),
            provider: Provider::Easytier,
            enabled: true,
            revision: 1,
            settings: Settings::Easytier {
                network_name: "team".into(),
                peers: vec!["tcp://x:1".into()],
            },
        };
        if !cfg!(all(target_os = "android", feature = "network-easytier")) {
            assert_eq!(
                select_route(Some(&p)),
                Err("overlay_provider_unavailable".into())
            );
        }
        p.provider = Provider::Tailscale;
        assert_eq!(
            select_route(Some(&p)),
            Err("overlay_provider_unavailable".into())
        );
    }
    #[test]
    fn managed_state_wire_preserves_login_and_running_states() {
        use herdr_readonly_transport::mobile_nodes::{BindingProvider, Snapshot};
        let binding = Binding::with_provider(
            BindingProvider::Tailscale,
            "a".repeat(32),
            1,
            "team".into(),
            "native-store-ref".into(),
        )
        .unwrap();
        for (state, expected) in [
            (State::Starting, "starting"),
            (State::EngineStarted, "engine-started"),
            (State::NeedsLogin, "needs-login"),
            (State::NeedsMachineAuth, "needs-machine-auth"),
            (State::Running, "running"),
            (State::ZeroTierRequesting, "zero-tier-requesting"),
            (State::ZeroTierConfigured, "zero-tier-configured"),
            (State::ZeroTierDenied, "zero-tier-denied"),
            (State::ZeroTierNotFound, "zero-tier-not-found"),
            (State::ZeroTierPortError, "zero-tier-port-error"),
            (State::ZeroTierClientOld, "zero-tier-client-old"),
            (State::ZeroTierAuthRequired, "zero-tier-auth-required"),
            (State::ZeroTierUnknown, "zero-tier-unknown"),
            (State::Closing, "closing"),
            (State::Stopped, "stopped"),
        ] {
            let wire = serde_json::to_value(view(Snapshot {
                binding: binding.clone(),
                state,
                device_online: None,
            }))
            .unwrap();
            assert_eq!(wire["state"], expected);
            assert_eq!(wire["binding"]["provider"], "tailscale");
            assert_ne!(wire["state"], "ready");
        }
    }
    #[test]
    fn zerotier_status_preserves_device_online_separately() {
        let binding = Binding::with_provider(
            BindingProvider::ZeroTier, "a".repeat(32), 1,
            "0123456789abcdef".into(), "11111111-1111-4111-8111-111111111111".into(),
        ).unwrap();
        let wire = serde_json::to_value(view(herdr_readonly_transport::mobile_nodes::Snapshot {
            binding, state: State::ZeroTierConfigured, device_online: Some(false),
        })).unwrap();
        assert_eq!(wire["state"], "zero-tier-configured");
        assert_eq!(wire["deviceOnline"], false);
    }
    #[test]
    fn unavailable_source_does_not_hide_active_old_binding() {
        let b = Binding::new(
            "a".repeat(32),
            1,
            "team".into(),
            "11111111-1111-4111-8111-111111111111".into(),
        )
        .unwrap();
        let active = herdr_readonly_transport::mobile_nodes::Snapshot {
            binding: b.clone(),
            state: State::EngineStarted,
            device_online: None,
        };
        let visible = ready_view(Some(active), false);
        assert_eq!(visible.state, "engine-started");
        assert_eq!(visible.binding.unwrap(), b);
        assert_eq!(ready_view(None, false).state, "unavailable");
        assert_eq!(ready_view(None, true).state, "stopped");
    }
    #[tokio::test]
    async fn failed_or_unknown_stop_never_commits_profile() {
        let mut committed = false;
        let result = commit_after_stop(async { Err("mobile_node_cleanup_pending".into()) }, || {
            committed = true;
            Ok(())
        })
        .await;
        assert!(result.is_err());
        assert!(!committed);
        commit_after_stop(async { Ok(()) }, || {
            committed = true;
            Ok(())
        })
        .await
        .unwrap();
        assert!(committed);
    }
}
