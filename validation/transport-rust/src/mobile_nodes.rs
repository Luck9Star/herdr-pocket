//! Reusable foreground managed-node lifecycle. Public bindings describe saved
//! configuration; attempt numbers are private and never enter recovery markers.
//! No default identity source, engine retry, transport fallback or joined claim.
use crate::{Cancellation, Result, overlay::OverlayDialer};
use overlay_runtime::nodes::{NodeLease, NodeStatus};
pub use overlay_runtime::nodes::{NodeSpec, SecretConfig, SecureConfigSource};
use overlay_runtime::{Failure, MAX_DEADLINE, OverlayRuntime, ProfileKey, Provider};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex, MutexGuard},
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
    profile_id: String,
    profile_revision: u32,
    network_name: String,
    identity_ref: String,
}
impl Binding {
    pub fn new(
        profile_id: String,
        profile_revision: u32,
        network_name: String,
        identity_ref: String,
    ) -> Result<Self> {
        let binding = Self {
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
            provider: Provider::EasyTier,
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
    Closing,
    Stopped,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    pub binding: Binding,
    pub state: State,
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

    pub async fn start(
        &self,
        binding: Binding,
        source: Arc<dyn SecureConfigSource>,
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
                        && binding.network_name != entry.binding.network_name)
                {
                    return Err("overlay_stale_revision");
                }
            }
            if cancel.is_cancelled() {
                return Err("cancelled");
            }
            let attempt = registry.next_attempt;
            registry.next_attempt = attempt.checked_add(1).ok_or("mobile_node_capacity")?;
            let operation = self
                .inner
                .runtime
                .start_easytier_profile(binding.spec(attempt), Some(source), timeout)
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
            entry.state = State::EngineStarted;
        }
        guard.armed = false;
        Ok(Snapshot {
            binding,
            state: State::EngineStarted,
        })
    }

    pub async fn status(&self, binding: &Binding) -> Result<Snapshot> {
        binding.validate()?;
        let attempt = {
            let registry = lock(&self.inner.registry);
            let Some(entry) = registry.entries.get(binding.profile_id()) else {
                return Ok(Snapshot {
                    binding: binding.clone(),
                    state: State::Stopped,
                });
            };
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
            Ok(operation) => match operation.await.map_err(code)? {
                NodeStatus::Starting => State::Starting,
                NodeStatus::EngineStarted => State::EngineStarted,
                NodeStatus::Closing => State::Closing,
                NodeStatus::Stopped => State::Stopped,
            },
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
            (State::Closing | State::Stopped, State::Starting | State::EngineStarted) => {
                entry.state
            }
            (State::Starting, State::EngineStarted) if entry.node.is_none() => State::Starting,
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
        binding.validate()?;
        deadline(timeout)?;
        let (attempt, operation) = {
            let mut registry = lock(&self.inner.registry);
            let Some(entry) = registry.entries.get_mut(binding.profile_id()) else {
                return Ok(Snapshot {
                    binding: binding.clone(),
                    state: State::Stopped,
                });
            };
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
        if entry.state != State::EngineStarted {
            return Err("mobile_node_not_started");
        }
        OverlayDialer::new(
            self.inner.runtime.clone(),
            entry.node.clone().ok_or("mobile_node_not_started")?,
            timeout,
        )
    }
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
