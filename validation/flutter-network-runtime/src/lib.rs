//! Android Flutter bridge over the same owned managed node and byte stream.
//! The default build has no engine, identity, sockets or provider fallback.
#[cfg(all(target_os = "android", feature = "native-fixture"))]
compile_error!("synthetic native fixture is forbidden in Android app builds");

use herdr_readonly_transport::{
    Cancellation,
    mobile_nodes::{
        Binding, BindingProvider, MobileNodeService, NativeDeviceSource, NativeStateSource,
        SecureConfigSource, Snapshot, State,
    },
    tailscale_settings::TailscaleSettings,
    transport::{ByteStream, Dialer},
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    future::poll_fn,
    pin::Pin,
    sync::{
        Arc, Mutex, MutexGuard,
        atomic::{AtomicBool, Ordering},
    },
    task::Poll,
    time::Duration,
};
use tokio::io::ReadBuf;
use zeroize::Zeroizing;

mod native;

type Result<T> = std::result::Result<T, &'static str>;
const MAX_SCOPES: usize = 4;
const MAX_STREAMS: usize = 32;
const MAX_TOMBSTONES: usize = 4096;
const MAX_BYTES: usize = 65_536;
const DEADLINE: Duration = Duration::from_secs(10);
const READ_WAIT: Duration = Duration::from_millis(250);
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poison| poison.into_inner())
}

trait SourceFactory: Send + Sync {
    fn available(&self) -> Result<()>;
    fn create(&self, binding: &Binding, peers: Vec<String>) -> Result<Arc<dyn SecureConfigSource>>;
    fn available_for(&self, provider: &BindingProvider) -> Result<()> {
        match provider {
            BindingProvider::EasyTier => self.available(),
            _ => Err("overlay_provider_unavailable"),
        }
    }
    fn create_tailscale(
        &self,
        _binding: &Binding,
        _settings: &TailscaleSettings,
    ) -> Result<Arc<dyn NativeStateSource>> {
        Err("overlay_provider_unavailable")
    }
    fn create_zerotier(&self, _binding: &Binding) -> Result<Arc<dyn NativeDeviceSource>> {
        Err("overlay_provider_unavailable")
    }
}
struct AndroidSource;
impl SourceFactory for AndroidSource {
    fn available(&self) -> Result<()> {
        if !cfg!(feature = "network-easytier") {
            return Err("overlay_provider_unavailable");
        }
        if !herdr_android_network_source::is_initialized() {
            return Err("network_native_context_unavailable");
        }
        Ok(())
    }
    fn create(&self, binding: &Binding, peers: Vec<String>) -> Result<Arc<dyn SecureConfigSource>> {
        self.available()?;
        herdr_android_network_source::AndroidSecureConfigSource::new(
            binding.profile_id().into(),
            binding.profile_revision(),
            binding.network_name().into(),
            binding.identity_ref().into(),
            peers,
        )
        .map(|source| Arc::new(source) as Arc<dyn SecureConfigSource>)
    }
    fn available_for(&self, provider: &BindingProvider) -> Result<()> {
        match provider {
            BindingProvider::EasyTier => self.available(),
            BindingProvider::Tailscale => {
                if !cfg!(feature = "network-tailscale") {
                    return Err("overlay_provider_unavailable");
                }
                if !herdr_android_network_source::is_tailscale_initialized() {
                    return Err("network_native_context_unavailable");
                }
                Ok(())
            }
            #[cfg(feature = "network-zerotier")]
            BindingProvider::ZeroTier => {
                if !herdr_android_network_source::is_zerotier_initialized() {
                    return Err("network_native_context_unavailable");
                }
                Ok(())
            }
            #[cfg(not(feature = "network-zerotier"))]
            BindingProvider::ZeroTier => Err("overlay_provider_unavailable"),
        }
    }
    fn create_tailscale(
        &self,
        binding: &Binding,
        settings: &TailscaleSettings,
    ) -> Result<Arc<dyn NativeStateSource>> {
        self.available_for(&BindingProvider::Tailscale)?;
        herdr_android_network_source::AndroidTailscaleSource::new(
            binding.profile_id().into(),
            binding.profile_revision(),
            binding.network_name().into(),
            binding.identity_ref().into(),
            settings.hostname().into(),
            settings.control_url().into(),
        )
        .map(|source| Arc::new(source) as Arc<dyn NativeStateSource>)
    }
    #[cfg(feature = "network-zerotier")]
    fn create_zerotier(&self, binding: &Binding) -> Result<Arc<dyn NativeDeviceSource>> {
        self.available_for(&BindingProvider::ZeroTier)?;
        herdr_readonly_transport::android_zerotier::AndroidZeroTierSource::new(
            binding.profile_id().into(),
            binding.profile_revision(),
            binding.network_name().into(),
            binding.identity_ref().into(),
        )
        .map_err(|_| "network_identity_unavailable")
        .map(|source| Arc::new(source) as Arc<dyn NativeDeviceSource>)
    }
}

enum StartSource {
    EasyTier(Arc<dyn SecureConfigSource>),
    Tailscale(Arc<dyn NativeStateSource>),
    #[cfg(feature = "network-zerotier")]
    ZeroTier(Arc<dyn NativeDeviceSource>),
}

#[derive(Default)]
struct Scope {
    active: bool,
    last_open: u64,
    cancelled_ahead: HashSet<u64>,
}
struct NodeOwner {
    scope: u64,
    generation: u64,
    binding: Binding,
    cancel: Cancellation,
    start_pending: bool,
    auth_review: Option<AuthReview>,
}
struct AuthReview {
    attempt: herdr_readonly_transport::mobile_nodes::NodeAttempt,
    url: String,
    token: String,
}
#[derive(Clone, Copy, Eq, PartialEq)]
enum OpenState {
    Reserved,
    Opening,
    Retired,
}
struct PendingOpen {
    scope: u64,
    state: OpenState,
    cancel: Cancellation,
}
struct Stream {
    scope: u64,
    open_id: u64,
    stream: Mutex<Box<dyn ByteStream>>,
    read_busy: AtomicBool,
    write_busy: AtomicBool,
    retired: AtomicBool,
    cancel: Cancellation,
}
impl Stream {
    fn retire(&self) {
        self.retired.store(true, Ordering::Release);
        self.cancel.cancel();
        // The only implementation admitted here is OverlayStream: each poll
        // and abort only manipulates async state; no FFI runs under this lock.
        lock(&self.stream).abort();
    }
}
struct Registry {
    next_scope: u64,
    next_token: u64,
    scopes: HashMap<u64, Scope>,
    nodes: HashMap<String, NodeOwner>,
    opens: HashMap<(u64, u64), PendingOpen>,
    streams: HashMap<String, Arc<Stream>>,
}
struct Bridge {
    service: MobileNodeService,
    factory: Arc<dyn SourceFactory>,
    executor: &'static tokio::runtime::Runtime,
    registry: Mutex<Registry>,
}
pub(crate) struct Reply {
    value: Value,
    bytes: Option<Vec<u8>>,
}
impl Reply {
    fn value(value: Value) -> Self {
        Self { value, bytes: None }
    }
}
impl Bridge {
    fn new(factory: Arc<dyn SourceFactory>) -> Result<Arc<Self>> {
        static EXECUTOR: std::sync::OnceLock<Result<tokio::runtime::Runtime>> =
            std::sync::OnceLock::new();
        let executor = EXECUTOR
            .get_or_init(|| {
                tokio::runtime::Builder::new_multi_thread()
                    .worker_threads(2)
                    .max_blocking_threads(4)
                    .thread_name("flutter-network")
                    .enable_all()
                    .build()
                    .map_err(|_| "network_worker_unavailable")
            })
            .as_ref()
            .map_err(|code| *code)?;
        Ok(Arc::new(Self {
            service: MobileNodeService::new(),
            factory,
            executor,
            registry: Mutex::new(Registry {
                next_scope: 1,
                next_token: 1,
                scopes: HashMap::new(),
                nodes: HashMap::new(),
                opens: HashMap::new(),
                streams: HashMap::new(),
            }),
        }))
    }
    fn reap_locked(&self, registry: &mut Registry) {
        // Conservative physical-cleanup evidence: runtime zero proves every
        // retired open/stream has drained. Until then all ledger slots remain.
        if self.service.reserved_streams() == 0 {
            registry
                .opens
                .retain(|_, op| op.state != OpenState::Retired);
            registry
                .streams
                .retain(|_, stream| !stream.retired.load(Ordering::Acquire));
        }
        registry.scopes.retain(|id, scope| {
            scope.active
                || registry.nodes.values().any(|node| node.scope == *id)
                || registry.opens.values().any(|open| open.scope == *id)
                || registry.streams.values().any(|stream| stream.scope == *id)
        });
    }
    fn new_scope(&self) -> Result<u64> {
        let mut registry = lock(&self.registry);
        self.reap_locked(&mut registry);
        if registry.scopes.len() >= MAX_SCOPES {
            return Err("network_scope_capacity");
        }
        let id = registry.next_scope;
        if id > i64::MAX as u64 {
            return Err("network_scope_capacity");
        }
        registry.next_scope = id.checked_add(1).ok_or("network_scope_capacity")?;
        registry.scopes.insert(
            id,
            Scope {
                active: true,
                ..Scope::default()
            },
        );
        Ok(id)
    }
    fn scope(registry: &Registry, scope: u64, read_only: bool) -> Result<()> {
        match registry.scopes.get(&scope) {
            Some(value) if read_only || value.active => Ok(()),
            _ => Err("network_scope_unavailable"),
        }
    }
    fn reserve_open(&self, scope: u64, raw: &str) -> Result<Value> {
        let id = open_id(raw)?;
        let mut registry = lock(&self.registry);
        self.reap_locked(&mut registry);
        Self::scope(&registry, scope, false)?;
        let current = registry.scopes.get(&scope).unwrap();
        if id <= current.last_open {
            return Err("network_open_id_reused");
        }
        let current = registry.scopes.get_mut(&scope).unwrap();
        current.last_open = id;
        let cancelled = current.cancelled_ahead.contains(&id);
        current.cancelled_ahead.retain(|value| *value > id);
        if cancelled {
            return Err("cancelled");
        }
        // Every valid admission attempt consumes its ID, including capacity
        // rejection. A failed request is never replayable under the same ID.
        if registry.opens.len() + registry.streams.len() >= MAX_STREAMS {
            return Err("network_capacity");
        }
        registry.opens.insert(
            (scope, id),
            PendingOpen {
                scope,
                state: OpenState::Reserved,
                cancel: Cancellation::default(),
            },
        );
        Ok(json!({"reserved":true}))
    }
    fn cancel_open(&self, scope: u64, raw: &str) -> Result<Reply> {
        let id = open_id(raw)?;
        let mut registry = lock(&self.registry);
        Self::scope(&registry, scope, false)?;
        if let Some(open) = registry.opens.get_mut(&(scope, id)) {
            open.cancel.cancel();
            if open.state == OpenState::Reserved {
                open.state = OpenState::Retired;
            }
        } else if let Some(stream) = registry
            .streams
            .values()
            .find(|s| s.scope == scope && s.open_id == id)
        {
            stream.retire();
        } else {
            let current = registry.scopes.get_mut(&scope).unwrap();
            if id > current.last_open {
                if current.cancelled_ahead.len() >= MAX_TOMBSTONES
                    && !current.cancelled_ahead.contains(&id)
                {
                    return Err("network_cancel_capacity");
                }
                current.cancelled_ahead.insert(id);
            }
        }
        Ok(Reply::value(json!({"cancelled":true})))
    }
    fn close_scope(self: &Arc<Self>, scope: u64) -> Result<Value> {
        let nodes = {
            let mut registry = lock(&self.registry);
            Self::scope(&registry, scope, true)?;
            registry.scopes.get_mut(&scope).unwrap().active = false;
            for open in registry.opens.values_mut().filter(|op| op.scope == scope) {
                open.cancel.cancel();
                if open.state == OpenState::Reserved {
                    open.state = OpenState::Retired;
                }
            }
            for stream in registry
                .streams
                .values()
                .filter(|stream| stream.scope == scope)
            {
                stream.retire();
            }
            registry
                .nodes
                .values()
                .filter(|node| node.scope == scope)
                .map(|node| {
                    node.cancel.cancel();
                    self.service
                        .capture_attempt(&node.binding)
                        .map(|attempt| (node.binding.clone(), node.generation, attempt))
                })
                .collect::<Result<Vec<_>>>()?
        };
        for (binding, generation, attempt) in nodes {
            let Some(attempt) = attempt else {
                // Cancellation preceded capture under service admission's
                // mutex: this pending start can never admit an attempt later.
                self.remove_node(scope, &binding, generation);
                continue;
            };
            let bridge = self.clone();
            self.executor.spawn(async move {
                let until = tokio::time::Instant::now() + DEADLINE;
                let _ =
                    tokio::time::timeout_at(until, bridge.service.stop_attempt(&attempt, DEADLINE))
                        .await;
                // Cancellation may already own the cleanup worker (Busy).
                // Observe its result without retrying stop or native start.
                loop {
                    let state = bridge.service.status_attempt(&attempt).await;
                    if matches!(&state, Ok(snapshot) if snapshot.state == State::Stopped)
                        || matches!(state, Err("overlay_stale_revision"))
                    {
                        bridge.remove_node(scope, &binding, generation);
                        break;
                    }
                    if tokio::time::Instant::now() >= until {
                        break;
                    }
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            });
        }
        self.reap_locked(&mut lock(&self.registry));
        Ok(json!({"closing":true}))
    }
    fn remove_node(&self, scope: u64, binding: &Binding, generation: u64) {
        let mut registry = lock(&self.registry);
        if registry
            .nodes
            .get(binding.profile_id())
            .is_some_and(|node| node.scope == scope && node.generation == generation)
        {
            registry.nodes.remove(binding.profile_id());
        }
        self.reap_locked(&mut registry);
    }
    async fn status_node(
        &self,
        scope: u64,
        profile: &str,
        provider: Option<BindingProvider>,
    ) -> Result<Reply> {
        valid_profile(profile)?;
        let owner = {
            let registry = lock(&self.registry);
            Self::scope(&registry, scope, true)?;
            match registry.nodes.get(profile) {
                Some(owner)
                    if owner.scope == scope
                        && provider
                            .as_ref()
                            .is_some_and(|value| owner.binding.provider() != value) =>
                {
                    return Err("mobile_node_binding_mismatch");
                }
                Some(owner) if owner.scope == scope => Some((
                    owner.binding.clone(),
                    owner.generation,
                    owner.start_pending && !owner.cancel.is_cancelled(),
                    self.service.capture_attempt(&owner.binding)?,
                )),
                Some(_) => return Err("network_scope_mismatch"),
                None => None,
            }
        };
        if let Some((binding, generation, pending, attempt)) = owner {
            let snapshot = match attempt {
                Some(attempt) => match self.service.status_attempt(&attempt).await {
                    Ok(snapshot) if pending && snapshot.state == State::Stopped => Snapshot {
                        binding: binding.clone(),
                        state: State::Starting,
                        device_online: None,
                    },
                    Err("overlay_stale_revision") if pending => Snapshot {
                        binding: binding.clone(),
                        state: State::Starting,
                        device_online: None,
                    },
                    result => result?,
                },
                None => Snapshot {
                    binding: binding.clone(),
                    device_online: None,
                    state: if pending {
                        State::Starting
                    } else {
                        State::Stopped
                    },
                },
            };
            if snapshot.state == State::Stopped {
                self.remove_node(scope, &binding, generation);
            }
            return Ok(Reply::value(
                serde_json::to_value(snapshot).map_err(|_| "network_failed")?,
            ));
        }
        let state = if self
            .factory
            .available_for(&provider.unwrap_or(BindingProvider::EasyTier))
            .is_ok()
        {
            "stopped"
        } else {
            "unavailable"
        };
        Ok(Reply::value(json!({"state":state,"binding":null})))
    }
    async fn start_node(&self, scope: u64, args: StartArgs) -> Result<Reply> {
        let provider = args.binding.provider();
        let source = match provider {
            BindingProvider::EasyTier => {
                let peers = args.peers.ok_or("invalid_network_request")?;
                if args.settings.is_some() {
                    return Err("invalid_network_request");
                }
                self.factory.available_for(provider)?;
                StartSource::EasyTier(self.factory.create(&args.binding, peers)?)
            }
            BindingProvider::Tailscale => {
                if args.peers.is_some() {
                    return Err("invalid_network_request");
                }
                let settings = args.settings.ok_or("invalid_network_request")?;
                let settings = TailscaleSettings::new(&settings.control_url, &settings.hostname)?;
                if settings.network_name() != args.binding.network_name() {
                    return Err("mobile_node_binding_mismatch");
                }
                self.factory.available_for(provider)?;
                StartSource::Tailscale(self.factory.create_tailscale(&args.binding, &settings)?)
            }
            #[cfg(feature = "network-zerotier")]
            BindingProvider::ZeroTier => {
                if args.peers.is_some() || args.settings.is_some() {
                    return Err("invalid_network_request");
                }
                self.factory.available_for(provider)?;
                StartSource::ZeroTier(self.factory.create_zerotier(&args.binding)?)
            }
            #[cfg(not(feature = "network-zerotier"))]
            BindingProvider::ZeroTier => return Err("overlay_provider_unavailable"),
        };
        let (generation, cancel) = {
            let mut registry = lock(&self.registry);
            Self::scope(&registry, scope, false)?;
            if registry.nodes.contains_key(args.binding.profile_id()) {
                return Err("mobile_node_busy");
            }
            let generation = registry.next_token;
            registry.next_token = generation.checked_add(1).ok_or("network_capacity")?;
            let cancel = Cancellation::default();
            registry.nodes.insert(
                args.binding.profile_id().into(),
                NodeOwner {
                    scope,
                    generation,
                    binding: args.binding.clone(),
                    cancel: cancel.clone(),
                    start_pending: true,
                    auth_review: None,
                },
            );
            (generation, cancel)
        };
        let result = tokio::time::timeout(DEADLINE, async {
            match source {
                StartSource::EasyTier(source) => {
                    self.service
                        .start(args.binding.clone(), source, DEADLINE, cancel.clone())
                        .await
                }
                StartSource::Tailscale(source) => {
                    self.service
                        .start_tailscale(args.binding.clone(), source, DEADLINE, cancel.clone())
                        .await
                }
                #[cfg(feature = "network-zerotier")]
                StartSource::ZeroTier(source) => {
                    self.service
                        .start_zerotier(args.binding.clone(), source, DEADLINE, cancel.clone())
                        .await
                }
            }
        })
        .await;
        if let Some(owner) = lock(&self.registry)
            .nodes
            .get_mut(args.binding.profile_id())
            && owner.scope == scope
            && owner.generation == generation
        {
            owner.start_pending = false;
        }
        match result {
            Ok(Ok(snapshot)) => {
                let registry = lock(&self.registry);
                Self::scope(&registry, scope, false)?;
                if !registry
                    .nodes
                    .get(args.binding.profile_id())
                    .is_some_and(|node| node.scope == scope && node.generation == generation)
                {
                    return Err("cancelled");
                }
                Ok(Reply::value(
                    serde_json::to_value(snapshot).map_err(|_| "network_failed")?,
                ))
            }
            result => {
                cancel.cancel();
                let cleanup = {
                    let registry = lock(&self.registry);
                    registry
                        .nodes
                        .get(args.binding.profile_id())
                        .filter(|owner| owner.scope == scope && owner.generation == generation)
                        .map(|_| self.service.capture_attempt(&args.binding))
                };
                let stopped = match cleanup {
                    Some(Ok(None)) => true,
                    Some(Ok(Some(attempt))) => {
                        let state = self.service.status_attempt(&attempt).await;
                        matches!(&state, Ok(snapshot) if snapshot.state == State::Stopped)
                            || matches!(state, Err("overlay_stale_revision"))
                    }
                    _ => false,
                };
                if stopped {
                    self.remove_node(scope, &args.binding, generation);
                }
                match result {
                    Ok(Err(code)) => Err(code),
                    _ => Err("network_start_unknown"),
                }
            }
        }
    }
    async fn stop_node(&self, scope: u64, binding: Binding) -> Result<Reply> {
        let generation = {
            let registry = lock(&self.registry);
            Self::scope(&registry, scope, false)?;
            if let Some(owner) = registry.nodes.get(binding.profile_id()) {
                if owner.scope != scope {
                    return Err("network_scope_mismatch");
                }
                if owner.binding != binding {
                    return Err("mobile_node_binding_mismatch");
                }
                owner.cancel.cancel();
                Some((owner.generation, self.service.capture_attempt(&binding)?))
            } else {
                None
            }
        };
        let Some((generation, attempt)) = generation else {
            let snapshot = self.service.status(&binding).await?;
            if snapshot.state != State::Stopped {
                return Err("mobile_node_not_started");
            }
            return Ok(Reply::value(
                serde_json::to_value(snapshot).map_err(|_| "network_failed")?,
            ));
        };
        let snapshot = match attempt {
            Some(attempt) => {
                tokio::time::timeout(DEADLINE, self.service.stop_attempt(&attempt, DEADLINE))
                    .await
                    .map_err(|_| "mobile_node_cleanup_pending")??
            }
            None => Snapshot {
                binding: binding.clone(),
                state: State::Stopped,
                device_online: None,
            },
        };
        if snapshot.state == State::Stopped {
            self.remove_node(scope, &binding, generation);
        }
        Ok(Reply::value(
            serde_json::to_value(snapshot).map_err(|_| "network_failed")?,
        ))
    }
    fn login_owner(
        &self,
        scope: u64,
        binding: &Binding,
    ) -> Result<(
        u64,
        Cancellation,
        herdr_readonly_transport::mobile_nodes::NodeAttempt,
    )> {
        let registry = lock(&self.registry);
        Self::scope(&registry, scope, false)?;
        let owner = registry
            .nodes
            .get(binding.profile_id())
            .ok_or("mobile_node_not_started")?;
        if owner.scope != scope {
            return Err("network_scope_mismatch");
        }
        if &owner.binding != binding {
            return Err("mobile_node_binding_mismatch");
        }
        if binding.provider() != &BindingProvider::Tailscale {
            return Err("overlay_provider_unavailable");
        }
        let attempt = self
            .service
            .capture_attempt(binding)?
            .ok_or("mobile_node_not_started")?;
        Ok((owner.generation, owner.cancel.clone(), attempt))
    }
    async fn login_node(&self, scope: u64, binding: Binding, begin: bool) -> Result<Reply> {
        let (generation, cancel, attempt) = self.login_owner(scope, &binding)?;
        if begin {
            let mut registry = lock(&self.registry);
            Self::scope(&registry, scope, false)?;
            let owner = registry
                .nodes
                .get_mut(binding.profile_id())
                .ok_or("cancelled")?;
            if owner.scope != scope || owner.generation != generation || cancel.is_cancelled() {
                return Err("cancelled");
            }
            owner.auth_review = None;
        }
        let mut login = if begin {
            self.service
                .begin_login_attempt(&attempt, DEADLINE, cancel.clone())
                .await?
        } else {
            self.service
                .login_status_attempt(&attempt, DEADLINE, cancel.clone())
                .await?
        };
        if !matches!(login.state, State::NeedsLogin | State::NeedsMachineAuth) {
            login.auth_url = None;
        }
        let mut registry = lock(&self.registry);
        Self::scope(&registry, scope, false)?;
        let valid = registry
            .nodes
            .get(binding.profile_id())
            .is_some_and(|owner| {
                owner.scope == scope
                    && owner.generation == generation
                    && owner.binding == binding
                    && !cancel.is_cancelled()
            });
        if !valid {
            return Err("cancelled");
        }
        let review_token = if login.auth_url.is_some() {
            let id = registry.next_token;
            registry.next_token = id.checked_add(1).ok_or("network_capacity")?;
            Some(format!("review-{id:x}"))
        } else {
            None
        };
        let owner = registry
            .nodes
            .get_mut(binding.profile_id())
            .ok_or("cancelled")?;
        owner.auth_review =
            login
                .auth_url
                .as_ref()
                .zip(review_token.as_ref())
                .map(|(url, token)| AuthReview {
                    attempt,
                    url: url.clone(),
                    token: token.clone(),
                });
        let mut value = serde_json::to_value(login).map_err(|_| "network_failed")?;
        value["reviewToken"] = json!(review_token);
        Ok(Reply::value(value))
    }

    async fn review_open(&self, scope: u64, args: OpenLoginArgs) -> Result<Reply> {
        let (generation, cancel, attempt, reviewed_url) = {
            let registry = lock(&self.registry);
            Self::scope(&registry, scope, false)?;
            let owner = registry
                .nodes
                .get(args.binding.profile_id())
                .ok_or("mobile_node_not_started")?;
            if owner.scope != scope {
                return Err("network_scope_mismatch");
            }
            if owner.binding != args.binding {
                return Err("mobile_node_binding_mismatch");
            }
            let review = owner.auth_review.as_ref().ok_or("network_login_changed")?;
            if review.url != args.url || review.token != args.review_token {
                return Err("network_login_changed");
            }
            (
                owner.generation,
                owner.cancel.clone(),
                review.attempt.clone(),
                review.url.clone(),
            )
        };
        let login = self
            .service
            .login_status_attempt(&attempt, DEADLINE, cancel.clone())
            .await?;
        if login.binding != args.binding
            || login.auth_url.as_deref() != Some(reviewed_url.as_str())
            || !matches!(login.state, State::NeedsLogin | State::NeedsMachineAuth)
        {
            return Err("network_login_changed");
        }
        let mut registry = lock(&self.registry);
        Self::scope(&registry, scope, false)?;
        let owner = registry
            .nodes
            .get_mut(args.binding.profile_id())
            .ok_or("network_login_changed")?;
        if owner.scope != scope
            || owner.generation != generation
            || owner.binding != args.binding
            || cancel.is_cancelled()
            || owner
                .auth_review
                .as_ref()
                .is_none_or(|r| r.url != reviewed_url || r.token != args.review_token)
        {
            return Err("network_login_changed");
        }
        owner.auth_review = None;
        Ok(Reply::value(json!({"reviewed":true})))
    }
    async fn open_stream(self: &Arc<Self>, scope: u64, args: OpenArgs) -> Result<Reply> {
        let id = open_id(&args.open_id)?;
        let mut guard = OpenGuard {
            bridge: self.clone(),
            scope,
            id,
            armed: true,
        };
        let cancel = {
            let mut registry = lock(&self.registry);
            Self::scope(&registry, scope, false)?;
            let owner = registry
                .nodes
                .get(args.binding.profile_id())
                .ok_or("mobile_node_not_started")?;
            if owner.scope != scope {
                return Err("network_scope_mismatch");
            }
            if owner.binding != args.binding {
                return Err("mobile_node_binding_mismatch");
            }
            let pending = registry
                .opens
                .get_mut(&(scope, id))
                .ok_or("network_open_not_reserved")?;
            if pending.state != OpenState::Reserved {
                return Err("network_open_id_reused");
            }
            if pending.cancel.is_cancelled() {
                registry.opens.remove(&(scope, id));
                return Err("cancelled");
            }
            pending.state = OpenState::Opening;
            pending.cancel.clone()
        };
        let dialer = self.service.dialer(&args.binding, DEADLINE)?;
        let result =
            tokio::time::timeout(DEADLINE, dialer.dial(args.host, args.port, cancel.clone())).await;
        let stream = match result {
            Ok(Ok(stream)) => stream,
            Ok(Err(code)) => return Err(code),
            Err(_) => {
                cancel.cancel();
                return Err("network_open_unknown");
            }
        };
        let route = stream.route_identity().ok_or("network_route_missing")?;
        let stream = Arc::new(Stream {
            scope,
            open_id: id,
            stream: Mutex::new(stream),
            read_busy: AtomicBool::new(false),
            write_busy: AtomicBool::new(false),
            retired: AtomicBool::new(false),
            cancel: cancel.clone(),
        });
        let mut registry = lock(&self.registry);
        let active = registry
            .scopes
            .get(&scope)
            .is_some_and(|scope| scope.active);
        let token = registry.next_token;
        registry.next_token = token.checked_add(1).ok_or("network_capacity")?;
        let token = format!("stream-{token:x}");
        if !active || cancel.is_cancelled() {
            stream.retire();
            registry.opens.remove(&(scope, id));
            registry.streams.insert(token, stream);
            guard.armed = false;
            return Err("cancelled");
        }
        registry.opens.remove(&(scope, id));
        registry.streams.insert(token.clone(), stream);
        guard.armed = false;
        Ok(Reply::value(json!({"streamId":token,"route":route})))
    }
    fn stream(&self, scope: u64, token: &str, allow_closed: bool) -> Result<Arc<Stream>> {
        let registry = lock(&self.registry);
        Self::scope(&registry, scope, false)?;
        let stream = registry.streams.get(token).ok_or("network_stream_closed")?;
        if stream.scope != scope {
            return Err("network_scope_mismatch");
        }
        if !allow_closed && stream.retired.load(Ordering::Acquire) {
            return Err("network_stream_closed");
        }
        Ok(stream.clone())
    }
    async fn read_stream(&self, scope: u64, args: ReadArgs) -> Result<Reply> {
        if args.max_bytes == 0 || args.max_bytes > MAX_BYTES {
            return Err("invalid_network_request");
        }
        let stream = self.stream(scope, &args.stream_id, false)?;
        let _busy = Busy::new(&stream.read_busy)?;
        let mut bytes = vec![0; args.max_bytes];
        let read = poll_fn(|cx| {
            let mut buffer = ReadBuf::new(&mut bytes);
            match Pin::new(&mut **lock(&stream.stream)).poll_read(cx, &mut buffer) {
                Poll::Ready(Ok(())) => Poll::Ready(Ok(buffer.filled().len())),
                Poll::Ready(Err(_)) => Poll::Ready(Err("overlay_transport_failed")),
                Poll::Pending => Poll::Pending,
            }
        });
        match tokio::time::timeout(READ_WAIT, read).await {
            Ok(Ok(count)) => {
                bytes.truncate(count);
                Ok(Reply {
                    value: json!({"eof":count == 0}),
                    bytes: Some(bytes),
                })
            }
            Ok(Err(code)) => {
                stream.retire();
                Err(code)
            }
            // Dropping only poll_fn leaves the original native read Operation
            // in OverlayStream. A future pull resumes it; no second read starts.
            Err(_) => Ok(Reply {
                value: json!({"eof":false}),
                bytes: Some(Vec::new()),
            }),
        }
    }
    async fn write_stream(&self, scope: u64, token: &str, bytes: Vec<u8>) -> Result<Reply> {
        let bytes = Zeroizing::new(bytes);
        if bytes.is_empty() || bytes.len() > MAX_BYTES {
            return Err("invalid_network_request");
        }
        let stream = self.stream(scope, token, false)?;
        let _busy = Busy::new(&stream.write_busy)?;
        let write = poll_fn(|cx| Pin::new(&mut **lock(&stream.stream)).poll_write(cx, &bytes));
        match tokio::time::timeout(DEADLINE, write).await {
            Ok(Ok(count)) if count > 0 && count <= bytes.len() => {
                Ok(Reply::value(json!({"accepted":count})))
            }
            _ => {
                stream.retire();
                Err("overlay_unknown_write")
            }
        }
    }
    async fn write_control(&self, scope: u64, token: &str, shutdown: bool) -> Result<Reply> {
        let stream = self.stream(scope, token, false)?;
        let _busy = Busy::new(&stream.write_busy)?;
        let operation = poll_fn(|cx| {
            let mut original = lock(&stream.stream);
            if shutdown {
                Pin::new(&mut **original).poll_shutdown(cx)
            } else {
                Pin::new(&mut **original).poll_flush(cx)
            }
        });
        match tokio::time::timeout(DEADLINE, operation).await {
            Ok(Ok(())) => Ok(Reply::value(if shutdown {
                json!({"shutdown":true})
            } else {
                json!({"flushed":true})
            })),
            _ => {
                stream.retire();
                Err("overlay_unknown_write")
            }
        }
    }
    async fn call(
        self: &Arc<Self>,
        scope: u64,
        method: &str,
        args: &str,
        bytes: Vec<u8>,
    ) -> Result<Reply> {
        let mut bytes = Zeroizing::new(bytes);
        if args.len() > 40_000 || bytes.len() > MAX_BYTES {
            return Err("invalid_network_request");
        }
        match method {
            "available" => {
                Self::scope(&lock(&self.registry), scope, true)?;
                let available_args: AvailableArgs = parse(args)?;
                let provider = available_args.provider.unwrap_or(BindingProvider::EasyTier);
                let available = self.factory.available_for(&provider);
                Ok(Reply::value(
                    json!({"available":available.is_ok(),"reason":available.err()}),
                ))
            }
            "nodeStatus" => {
                let args: ProfileArgs = parse(args)?;
                self.status_node(scope, &args.profile_id, args.provider)
                    .await
            }
            "nodeStart" => self.start_node(scope, parse(args)?).await,
            "nodeLogin" | "nodeLoginStatus" => {
                self.login_node(
                    scope,
                    parse::<BindingArgs>(args)?.binding,
                    method == "nodeLogin",
                )
                .await
            }
            "nodeAuthorizeOpen" => self.review_open(scope, parse(args)?).await,
            "nodeStop" => {
                self.stop_node(scope, parse::<BindingArgs>(args)?.binding)
                    .await
            }
            "streamOpen" => self.open_stream(scope, parse(args)?).await,
            "cancelOpen" => self.cancel_open(scope, &parse::<OpenIdArgs>(args)?.open_id),
            "streamRead" => self.read_stream(scope, parse(args)?).await,
            "streamWrite" => {
                self.write_stream(
                    scope,
                    &parse::<StreamArgs>(args)?.stream_id,
                    std::mem::take(&mut *bytes),
                )
                .await
            }
            "streamFlush" | "streamShutdown" => {
                self.write_control(
                    scope,
                    &parse::<StreamArgs>(args)?.stream_id,
                    method == "streamShutdown",
                )
                .await
            }
            "streamClose" => {
                self.stream(scope, &parse::<StreamArgs>(args)?.stream_id, true)?
                    .retire();
                Ok(Reply::value(json!({"closed":true})))
            }
            _ => Err("invalid_network_request"),
        }
    }
}
fn open_id(raw: &str) -> Result<u64> {
    if raw.is_empty()
        || raw.len() > 20
        || raw.starts_with('0')
        || !raw.bytes().all(|b| b.is_ascii_digit())
    {
        return Err("network_open_id_invalid");
    }
    raw.parse().map_err(|_| "network_open_id_invalid")
}
fn valid_profile(value: &str) -> Result<()> {
    if value.len() == 32
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        Ok(())
    } else {
        Err("invalid_network_request")
    }
}
fn parse<T: serde::de::DeserializeOwned>(args: &str) -> Result<T> {
    serde_json::from_str(args).map_err(|_| "invalid_network_request")
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ProfileArgs {
    profile_id: String,
    provider: Option<BindingProvider>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BindingArgs {
    binding: Binding,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StartArgs {
    binding: Binding,
    peers: Option<Vec<String>>,
    settings: Option<SettingsArgs>,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct OpenLoginArgs {
    binding: Binding,
    url: String,
    review_token: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SettingsArgs {
    control_url: String,
    hostname: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AvailableArgs {
    provider: Option<BindingProvider>,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct OpenArgs {
    binding: Binding,
    host: String,
    port: u16,
    open_id: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct OpenIdArgs {
    open_id: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReadArgs {
    stream_id: String,
    max_bytes: usize,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StreamArgs {
    stream_id: String,
}
struct Busy<'a>(&'a AtomicBool);
impl<'a> Busy<'a> {
    fn new(flag: &'a AtomicBool) -> Result<Self> {
        if flag.swap(true, Ordering::AcqRel) {
            Err("network_stream_busy")
        } else {
            Ok(Self(flag))
        }
    }
}
impl Drop for Busy<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}
struct OpenGuard {
    bridge: Arc<Bridge>,
    scope: u64,
    id: u64,
    armed: bool,
}
impl Drop for OpenGuard {
    fn drop(&mut self) {
        if self.armed
            && let Some(open) = lock(&self.bridge.registry)
                .opens
                .get_mut(&(self.scope, self.id))
        {
            open.cancel.cancel();
            open.state = OpenState::Retired;
        }
    }
}

#[cfg(test)]
mod tests;
