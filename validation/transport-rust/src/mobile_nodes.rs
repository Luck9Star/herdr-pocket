//! Reusable foreground managed-node lifecycle. Public bindings describe saved
//! configuration; attempt numbers are private and never enter recovery markers.
//! No default identity source, engine retry, transport fallback or joined claim.
pub use crate::transport::OverlayProvider as BindingProvider;
use crate::{Cancellation, Result, overlay::OverlayDialer};
use overlay_runtime::nodes::{NodeLease, NodeStatus};
pub use overlay_runtime::nodes::{NodeSpec, SecretConfig, SecureConfigSource};
pub use overlay_runtime::tailscale::{
    NativeNodeConfig, NativeStateSource, NativeStateStore, NativeVettedDirectory, StateStoreError,
    StateStoreResult,
};
use overlay_runtime::{Failure, MAX_DEADLINE, OverlayRuntime, ProfileKey, Provider};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex, MutexGuard, Weak},
    time::Duration,
};

/// Retain stopped profile history rather than silently evicting revision and
/// network guards. Recreate the app runtime to clear history, after cleanup.
pub const MAX_PROFILE_HISTORY: usize = 32;

/// Public metadata only. Revision increases when persisted network settings
/// change; a restart keeps the same binding. A recreated vault identity has a
/// new identity_ref and may retain catalog revision after the old node drains.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Binding {
    #[serde(
        default = "default_provider",
        skip_serializing_if = "is_default_provider"
    )]
    provider: BindingProvider,
    profile_id: String,
    profile_revision: u32,
    network_name: String,
    identity_ref: String,
}
fn default_provider() -> BindingProvider {
    BindingProvider::EasyTier
}
fn is_default_provider(provider: &BindingProvider) -> bool {
    *provider == BindingProvider::EasyTier
}
impl Binding {
    pub fn new(
        profile_id: String,
        profile_revision: u32,
        network_name: String,
        identity_ref: String,
    ) -> Result<Self> {
        Self::with_provider(
            BindingProvider::EasyTier,
            profile_id,
            profile_revision,
            network_name,
            identity_ref,
        )
    }
    pub fn with_provider(
        provider: BindingProvider,
        profile_id: String,
        profile_revision: u32,
        network_name: String,
        identity_ref: String,
    ) -> Result<Self> {
        let binding = Self {
            provider,
            profile_id,
            profile_revision,
            network_name,
            identity_ref,
        };
        binding.validate()?;
        Ok(binding)
    }
    fn validate(&self) -> Result<()> {
        let bounded = |value: &str| {
            !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
        };
        if self.profile_id.is_empty()
            || self.profile_id.len() > 128
            || !self
                .profile_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
            || self.profile_revision == 0
            || !bounded(&self.network_name)
            || !bounded(&self.identity_ref)
        {
            return Err("mobile_node_invalid_binding");
        }
        Ok(())
    }
    pub fn provider(&self) -> &BindingProvider {
        &self.provider
    }
    pub fn profile_id(&self) -> &str {
        &self.profile_id
    }
    pub fn profile_revision(&self) -> u32 {
        self.profile_revision
    }
    pub fn network_name(&self) -> &str {
        &self.network_name
    }
    pub fn identity_ref(&self) -> &str {
        &self.identity_ref
    }
    fn profile(&self) -> ProfileKey {
        ProfileKey {
            provider: match self.provider {
                BindingProvider::EasyTier => Provider::EasyTier,
                BindingProvider::Tailscale => Provider::Tailscale,
                BindingProvider::ZeroTier => Provider::ZeroTier,
            },
            id: self.profile_id.clone(),
        }
    }
    fn spec(&self, attempt: u64) -> NodeSpec {
        NodeSpec {
            profile: self.profile(),
            revision: attempt,
            profile_revision: self.profile_revision,
            network: self.network_name.clone(),
            identity_ref: self.identity_ref.clone(),
        }
    }
}

/// EngineStarted means only that the fixed native engine accepted its start.
/// It says nothing about joining a network, peer reachability or SSH readiness.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum State {
    Starting,
    EngineStarted,
    NeedsLogin,
    NeedsMachineAuth,
    Running,
    Closing,
    Stopped,
}

impl State {
    fn from_native(state: NodeStatus) -> Self {
        match state {
            NodeStatus::Starting => Self::Starting,
            NodeStatus::EngineStarted => Self::EngineStarted,
            NodeStatus::NeedsLogin => Self::NeedsLogin,
            NodeStatus::NeedsMachineAuth => Self::NeedsMachineAuth,
            NodeStatus::Running => Self::Running,
            NodeStatus::Closing => Self::Closing,
            NodeStatus::Stopped => Self::Stopped,
        }
    }
    fn live(self) -> bool {
        !matches!(self, Self::Closing | Self::Stopped)
    }
}
#[derive(Clone, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoginSnapshot {
    pub binding: Binding,
    pub state: State,
    pub auth_url: Option<String>,
}
impl std::fmt::Debug for LoginSnapshot {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LoginSnapshot")
            .field("binding", &self.binding)
            .field("state", &self.state)
            .field("has_auth_url", &self.auth_url.is_some())
            .finish()
    }
}
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    pub binding: Binding,
    pub state: State,
}
/// Process-local capability for one admitted attempt. Never serialize it or
/// substitute its attempt number for the durable route profile revision.
#[derive(Clone)]
pub struct NodeAttempt {
    service: Weak<Inner>,
    binding: Binding,
    attempt: u64,
}
struct Entry {
    binding: Binding,
    attempt: u64,
    state: State,
    node: Option<NodeLease>,
}
struct Registry {
    next_attempt: u64,
    entries: HashMap<String, Entry>,
}
struct Inner {
    runtime: Arc<OverlayRuntime>,
    registry: Mutex<Registry>,
}
fn lock<T>(value: &Mutex<T>) -> MutexGuard<'_, T> {
    value.lock().unwrap_or_else(|poison| poison.into_inner())
}
fn deadline(value: Duration) -> Result<()> {
    if value.is_zero() || value > MAX_DEADLINE {
        Err("overlay_invalid_deadline")
    } else {
        Ok(())
    }
}
fn code(failure: Failure) -> &'static str {
    match failure {
        Failure::ProviderUnavailable => "overlay_provider_unavailable",
        Failure::IdentityUnavailable => "overlay_identity_unavailable",
        Failure::StaleRevision => "overlay_stale_revision",
        Failure::Cancelled => "cancelled",
        Failure::Busy => "mobile_node_busy",
        Failure::Capacity => "mobile_node_capacity",
        Failure::ClosePending | Failure::WaitTimeout => "mobile_node_cleanup_pending",
        Failure::InvalidDeadline => "overlay_invalid_deadline",
        _ => "mobile_node_failed",
    }
}

/// Own one instance for the app lifetime. Sources are injected per start so
/// peer settings and secure references belong to that exact immutable binding.
/// All locks are brief admission/metadata locks; no lock is held across await.
#[derive(Clone)]
pub struct MobileNodeService {
    inner: Arc<Inner>,
}
impl Default for MobileNodeService {
    fn default() -> Self {
        Self::new()
    }
}
impl MobileNodeService {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Inner {
                runtime: Arc::new(OverlayRuntime::new()),
                registry: Mutex::new(Registry {
                    next_attempt: 1,
                    entries: HashMap::new(),
                }),
            }),
        }
    }
    /// Includes pending starts, late completions, drains and failed cleanup.
    /// The runtime's eight-node limit is enforced before loading any source.
    pub fn reserved_nodes(&self) -> usize {
        self.inner.runtime.reserved_nodes()
    }
    /// Includes pending opens and native handles whose cleanup is unfinished.
    pub fn reserved_streams(&self) -> usize {
        self.inner.runtime.reserved_streams()
    }

    /// Capture under the host's ownership lock before dispatching delayed
    /// cleanup. None means no attempt for this binding was admitted yet
    /// (different-binding Stopped history is not an admitted current attempt).
    /// A host cancelling a
    /// pending start must cancel its token before capture, so admission either
    /// precedes this capture or observes cancellation under the same registry.
    pub fn capture_attempt(&self, binding: &Binding) -> Result<Option<NodeAttempt>> {
        binding.validate()?;
        let registry = lock(&self.inner.registry);
        let Some(entry) = registry.entries.get(binding.profile_id()) else {
            return Ok(None);
        };
        if entry.binding != *binding {
            if entry.state == State::Stopped {
                return Ok(None);
            }
            return Err("mobile_node_binding_mismatch");
        }
        Ok(Some(NodeAttempt {
            service: Arc::downgrade(&self.inner),
            binding: binding.clone(),
            attempt: entry.attempt,
        }))
    }

    fn owns_attempt(&self, attempt: &NodeAttempt) -> Result<()> {
        if attempt
            .service
            .upgrade()
            .is_some_and(|service| Arc::ptr_eq(&service, &self.inner))
        {
            Ok(())
        } else {
            Err("overlay_wrong_owner")
        }
    }

    pub async fn start(
        &self,
        binding: Binding,
        source: Arc<dyn SecureConfigSource>,
        timeout: Duration,
        cancel: Cancellation,
    ) -> Result<Snapshot> {
        if binding.provider != BindingProvider::EasyTier {
            return Err("overlay_provider_unavailable");
        }
        self.start_with(binding, StartSource::EasyTier(source), timeout, cancel)
            .await
    }
    pub async fn start_tailscale(
        &self,
        binding: Binding,
        source: Arc<dyn NativeStateSource>,
        timeout: Duration,
        cancel: Cancellation,
    ) -> Result<Snapshot> {
        if binding.provider != BindingProvider::Tailscale {
            return Err("overlay_provider_unavailable");
        }
        self.start_with(binding, StartSource::Tailscale(source), timeout, cancel)
            .await
    }
    async fn start_with(
        &self,
        binding: Binding,
        source: StartSource,
        timeout: Duration,
        cancel: Cancellation,
    ) -> Result<Snapshot> {
        binding.validate()?;
        deadline(timeout)?;
        if cancel.is_cancelled() {
            return Err("cancelled");
        }
        // A completed asynchronous cleanup can be observed without requiring a
        // separate status call. Do not re-start or retry any prior operation.
        let previous = lock(&self.inner.registry)
            .entries
            .get(binding.profile_id())
            .map(|e| e.binding.clone());
        if let Some(previous) = previous {
            tokio::select! { biased;
                _ = cancel.wait() => return Err("cancelled"),
                result = self.status(&previous) => { result?; }
            }
        }
        let (attempt, operation) = {
            let mut registry = lock(&self.inner.registry);
            if !registry.entries.contains_key(binding.profile_id())
                && registry.entries.len() >= MAX_PROFILE_HISTORY
            {
                return Err("mobile_node_history_capacity");
            }
            if let Some(entry) = registry.entries.get(binding.profile_id()) {
                if entry.state != State::Stopped {
                    return Err(if entry.binding == binding {
                        "mobile_node_busy"
                    } else {
                        "mobile_node_binding_mismatch"
                    });
                }
                // Catalog revision cannot be reused for another network.
                // Vault identity generations have their own unique reference.
                if binding.profile_revision < entry.binding.profile_revision
                    || (binding.profile_revision == entry.binding.profile_revision
                        && (binding.network_name != entry.binding.network_name
                            || binding.provider != entry.binding.provider))
                {
                    return Err("overlay_stale_revision");
                }
            }
            if cancel.is_cancelled() {
                return Err("cancelled");
            }
            let attempt = registry.next_attempt;
            registry.next_attempt = attempt.checked_add(1).ok_or("mobile_node_capacity")?;
            let operation = match source {
                StartSource::EasyTier(source) => self.inner.runtime.start_easytier_profile(
                    binding.spec(attempt),
                    Some(source),
                    timeout,
                ),
                StartSource::Tailscale(source) => self.inner.runtime.start_tailscale_profile(
                    binding.spec(attempt),
                    Some(source),
                    timeout,
                ),
            }
            .map_err(code)?;
            registry.entries.insert(
                binding.profile_id.clone(),
                Entry {
                    binding: binding.clone(),
                    attempt,
                    state: State::Starting,
                    node: None,
                },
            );
            (attempt, operation)
        };
        let mut guard = Starting {
            inner: self.inner.clone(),
            binding: binding.clone(),
            attempt,
            timeout,
            armed: true,
            claimed_native: false,
        };
        let node = tokio::select! { biased;
            _ = cancel.wait() => return Err("cancelled"),
            value = operation => value.map_err(code)?,
        };
        guard.claimed_native = true;
        let initial_state = if binding.provider == BindingProvider::Tailscale {
            let status = self.inner.runtime.node_status(&node).map_err(code)?;
            tokio::select! { biased;
                _=cancel.wait()=>return Err("cancelled"),
                value=status=>State::from_native(value.map_err(code)?),
            }
        } else {
            State::EngineStarted
        };
        if !initial_state.live() {
            return Err("mobile_node_failed");
        }
        if cancel.is_cancelled() {
            return Err("cancelled");
        }
        {
            let mut registry = lock(&self.inner.registry);
            let entry = registry
                .entries
                .get_mut(binding.profile_id())
                .ok_or("overlay_stale_revision")?;
            // stop/status may have retired this start while native completed.
            if entry.attempt != attempt
                || entry.binding != binding
                || entry.state != State::Starting
                || cancel.is_cancelled()
            {
                return Err("cancelled");
            }
            entry.node = Some(node);
            entry.state = initial_state;
        }
        guard.armed = false;
        Ok(Snapshot {
            binding,
            state: initial_state,
        })
    }

    pub async fn begin_login(
        &self,
        binding: &Binding,
        timeout: Duration,
        cancel: Cancellation,
    ) -> Result<LoginSnapshot> {
        self.login_checked(binding, None, timeout, cancel, true)
            .await
    }
    pub async fn begin_login_attempt(
        &self,
        attempt: &NodeAttempt,
        timeout: Duration,
        cancel: Cancellation,
    ) -> Result<LoginSnapshot> {
        self.owns_attempt(attempt)?;
        self.login_checked(
            &attempt.binding,
            Some(attempt.attempt),
            timeout,
            cancel,
            true,
        )
        .await
    }
    /// Poll an existing authorization; never calls begin_login again.
    pub async fn login_status(
        &self,
        binding: &Binding,
        timeout: Duration,
        cancel: Cancellation,
    ) -> Result<LoginSnapshot> {
        self.login_checked(binding, None, timeout, cancel, false)
            .await
    }
    /// Used for a previously published auth review, including same-Binding
    /// restarts. A stale review must not read or authorize a replacement node.
    pub async fn login_status_attempt(
        &self,
        attempt: &NodeAttempt,
        timeout: Duration,
        cancel: Cancellation,
    ) -> Result<LoginSnapshot> {
        self.owns_attempt(attempt)?;
        self.login_checked(
            &attempt.binding,
            Some(attempt.attempt),
            timeout,
            cancel,
            false,
        )
        .await
    }
    async fn login_checked(
        &self,
        binding: &Binding,
        expected_attempt: Option<u64>,
        timeout: Duration,
        cancel: Cancellation,
        begin: bool,
    ) -> Result<LoginSnapshot> {
        let original = cancel.clone();
        self.login_checked_with_cancel_check(
            binding,
            expected_attempt,
            timeout,
            cancel,
            begin,
            Arc::new(move || original.is_cancelled()),
        )
        .await
    }
    async fn login_checked_with_cancel_check(
        &self,
        binding: &Binding,
        expected_attempt: Option<u64>,
        timeout: Duration,
        cancel: Cancellation,
        begin: bool,
        worker_cancel: Arc<dyn Fn() -> bool + Send + Sync>,
    ) -> Result<LoginSnapshot> {
        binding.validate()?;
        deadline(timeout)?;
        if binding.provider != BindingProvider::Tailscale {
            return Err("overlay_provider_unavailable");
        }
        let (attempt, node) = {
            let registry = lock(&self.inner.registry);
            let entry = registry
                .entries
                .get(binding.profile_id())
                .ok_or("mobile_node_not_started")?;
            if entry.binding != *binding {
                return Err("mobile_node_binding_mismatch");
            }
            if expected_attempt.is_some_and(|expected| expected != entry.attempt) {
                return Err("overlay_stale_revision");
            }
            if !entry.state.live() {
                return Err("mobile_node_not_started");
            }
            (
                entry.attempt,
                entry.node.clone().ok_or("mobile_node_not_started")?,
            )
        };
        if cancel.is_cancelled() {
            return Err("cancelled");
        }
        let operation = if begin {
            self.inner
                .runtime
                .begin_node_login_with_cancel_check(&node, timeout, worker_cancel)
        } else {
            self.inner
                .runtime
                .node_login_status_with_cancel_check(&node, timeout, worker_cancel)
        }
        .map_err(code)?;
        let login = tokio::select! { biased; _=cancel.wait()=>return Err("cancelled"),result=operation=>result.map_err(code)? };
        let mut registry = lock(&self.inner.registry);
        let entry = registry
            .entries
            .get_mut(binding.profile_id())
            .ok_or("overlay_stale_revision")?;
        if entry.attempt != attempt
            || entry.binding != *binding
            || !entry.state.live()
            || cancel.is_cancelled()
        {
            return Err("cancelled");
        }
        entry.state = State::from_native(login.state);
        Ok(LoginSnapshot {
            binding: binding.clone(),
            state: entry.state,
            auth_url: login.auth_url.map(|url| url.as_str().to_owned()),
        })
    }

    pub async fn status(&self, binding: &Binding) -> Result<Snapshot> {
        self.status_checked(binding, None).await
    }

    /// Observe only the captured attempt; never query a replacement node.
    pub async fn status_attempt(&self, attempt: &NodeAttempt) -> Result<Snapshot> {
        self.owns_attempt(attempt)?;
        self.status_checked(&attempt.binding, Some(attempt.attempt))
            .await
    }

    async fn status_checked(&self, binding: &Binding, expected: Option<u64>) -> Result<Snapshot> {
        binding.validate()?;
        let attempt = {
            let registry = lock(&self.inner.registry);
            let Some(entry) = registry.entries.get(binding.profile_id()) else {
                if expected.is_some() {
                    return Err("overlay_stale_revision");
                }
                return Ok(Snapshot {
                    binding: binding.clone(),
                    state: State::Stopped,
                });
            };
            if expected.is_some_and(|expected| entry.attempt != expected) {
                return Err("overlay_stale_revision");
            }
            if entry.binding != *binding {
                return Err("mobile_node_binding_mismatch");
            }
            if entry.state == State::Stopped {
                return Ok(Snapshot {
                    binding: binding.clone(),
                    state: State::Stopped,
                });
            }
            entry.attempt
        };
        let state = match self
            .inner
            .runtime
            .node_status_revision(&binding.profile(), attempt)
        {
            Err(Failure::ProfileMissing) => State::Stopped,
            Err(error) => return Err(code(error)),
            Ok(operation) => State::from_native(operation.await.map_err(code)?),
        };
        let mut registry = lock(&self.inner.registry);
        let entry = registry
            .entries
            .get_mut(binding.profile_id())
            .ok_or("overlay_stale_revision")?;
        if entry.attempt != attempt || entry.binding != *binding {
            return Err("overlay_stale_revision");
        }
        // An earlier status response cannot reopen an entry retired by stop or
        // attach a node whose start result has not been claimed by its caller.
        entry.state = match (entry.state, state) {
            (State::Closing | State::Stopped, next) if next.live() => entry.state,
            (State::Starting, next) if next.live() && entry.node.is_none() => State::Starting,
            _ => state,
        };
        if entry.state == State::Stopped {
            entry.node = None;
        }
        Ok(Snapshot {
            binding: binding.clone(),
            state: entry.state,
        })
    }

    /// Find the service's actual saved binding, even after its vault reference
    /// disappears. A GUI must revoke its SSH sessions before explicit stop.
    pub async fn status_profile(&self, profile_id: &str) -> Result<Option<Snapshot>> {
        let binding = lock(&self.inner.registry)
            .entries
            .get(profile_id)
            .map(|e| e.binding.clone());
        match binding {
            Some(binding) => self.status(&binding).await.map(Some),
            None => Ok(None),
        }
    }

    /// Retire admission synchronously before waiting for cleanup. Starting and
    /// Closing are valid inputs. A failed cleanup remains reserved; another
    /// explicit stop retries only the original attempt, never starts it again.
    pub async fn stop(&self, binding: &Binding, timeout: Duration) -> Result<Snapshot> {
        self.stop_checked(binding, None, timeout).await
    }

    /// Retirement and native cleanup admission compare the captured attempt
    /// while the service registry is locked, before any side effect or await.
    pub async fn stop_attempt(&self, attempt: &NodeAttempt, timeout: Duration) -> Result<Snapshot> {
        self.owns_attempt(attempt)?;
        self.stop_checked(&attempt.binding, Some(attempt.attempt), timeout)
            .await
    }

    async fn stop_checked(
        &self,
        binding: &Binding,
        expected: Option<u64>,
        timeout: Duration,
    ) -> Result<Snapshot> {
        binding.validate()?;
        deadline(timeout)?;
        let (attempt, operation) = {
            let mut registry = lock(&self.inner.registry);
            let Some(entry) = registry.entries.get_mut(binding.profile_id()) else {
                if expected.is_some() {
                    return Err("overlay_stale_revision");
                }
                return Ok(Snapshot {
                    binding: binding.clone(),
                    state: State::Stopped,
                });
            };
            if expected.is_some_and(|expected| entry.attempt != expected) {
                return Err("overlay_stale_revision");
            }
            if entry.binding != *binding {
                return Err("mobile_node_binding_mismatch");
            }
            if entry.state == State::Stopped {
                return Ok(Snapshot {
                    binding: binding.clone(),
                    state: State::Stopped,
                });
            }
            entry.state = State::Closing;
            match self
                .inner
                .runtime
                .retry_node_cleanup(&binding.profile(), entry.attempt, timeout)
            {
                Ok(operation) => (entry.attempt, Some(operation)),
                Err(Failure::ProfileMissing) => (entry.attempt, None),
                Err(error) => return Err(code(error)),
            }
        };
        if let Some(operation) = operation {
            operation.await.map_err(code)?;
        }
        let mut registry = lock(&self.inner.registry);
        let entry = registry
            .entries
            .get_mut(binding.profile_id())
            .ok_or("overlay_stale_revision")?;
        if entry.attempt != attempt || entry.binding != *binding {
            return Err("overlay_stale_revision");
        }
        entry.state = State::Stopped;
        entry.node = None;
        Ok(Snapshot {
            binding: binding.clone(),
            state: State::Stopped,
        })
    }

    /// Captures only the claimed exact NodeLease. A retained dialer cannot
    /// follow a stop/restart or a changed binding, even at the same address.
    pub fn dialer(&self, binding: &Binding, timeout: Duration) -> Result<OverlayDialer> {
        binding.validate()?;
        deadline(timeout)?;
        let registry = lock(&self.inner.registry);
        let entry = registry
            .entries
            .get(binding.profile_id())
            .ok_or("mobile_node_not_started")?;
        if entry.binding != *binding {
            return Err("mobile_node_binding_mismatch");
        }
        let ready = match binding.provider {
            BindingProvider::EasyTier => entry.state == State::EngineStarted,
            BindingProvider::Tailscale => entry.state == State::Running,
            BindingProvider::ZeroTier => false,
        };
        if !ready {
            return Err("mobile_node_not_started");
        }
        OverlayDialer::new(
            self.inner.runtime.clone(),
            entry.node.clone().ok_or("mobile_node_not_started")?,
            timeout,
        )
    }
}
enum StartSource {
    EasyTier(Arc<dyn SecureConfigSource>),
    Tailscale(Arc<dyn NativeStateSource>),
}
struct Starting {
    inner: Arc<Inner>,
    binding: Binding,
    attempt: u64,
    timeout: Duration,
    armed: bool,
    claimed_native: bool,
}
impl Drop for Starting {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let mut needs_cleanup = false;
        if let Some(entry) = lock(&self.inner.registry)
            .entries
            .get_mut(self.binding.profile_id())
            && entry.attempt == self.attempt
            && entry.state == State::Starting
        {
            entry.state = State::Closing;
            needs_cleanup = self.claimed_native;
        }
        // The start future may already have consumed a successful NodeLease.
        // Exact-attempt cleanup also covers cancellation at that boundary.
        if needs_cleanup {
            let _ = self.inner.runtime.retry_node_cleanup(
                &self.binding.profile(),
                self.attempt,
                self.timeout,
            );
        }
    }
}

#[cfg(test)]
mod tests;

#[cfg(all(test, feature = "overlay-native-fixture"))]
pub(crate) static NATIVE_FIXTURE_SERIAL: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
