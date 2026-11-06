//! App-owned node leases. This runtime has no built-in secure-store implementation;
//! absent one, startup refuses before reading state or entering native code.
use super::*;
use crate::easytier::EasyTierBackend;
use crate::tailscale::{LoginStatus, NativeStateSource, TailscaleBackend};

pub const MAX_NODES: usize = 8;

/// One lifecycle registry for all app-owned providers. Concrete backends own
/// their native epochs; cancellation/drain/revision rules remain in NodeEntry.
trait ManagedBackend: Backend {
    fn managed_status(&self) -> Result<NodeStatus>;
    fn managed_stop(&self, deadline: Duration) -> Result<()>;
    fn managed_login(&self, _deadline: Duration) -> Result<LoginStatus> {
        Err(Failure::ProviderUnavailable)
    }
    fn managed_login_status(&self, _deadline: Duration) -> Result<LoginStatus> {
        Err(Failure::ProviderUnavailable)
    }
}
impl ManagedBackend for EasyTierBackend {
    fn managed_status(&self) -> Result<NodeStatus> {
        self.node_status()
    }
    fn managed_stop(&self, deadline: Duration) -> Result<()> {
        self.stop_node(deadline)
    }
}

impl ManagedBackend for TailscaleBackend {
    fn managed_status(&self) -> Result<NodeStatus> {
        self.node_status()
    }
    fn managed_stop(&self, deadline: Duration) -> Result<()> {
        self.stop_node(deadline)
    }
    fn managed_login(&self, deadline: Duration) -> Result<LoginStatus> {
        self.begin_login(deadline)
    }
    fn managed_login_status(&self, deadline: Duration) -> Result<LoginStatus> {
        self.login_status(deadline)
    }
}

/// Public metadata only; secret material is obtained on the lifecycle worker.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NodeSpec {
    pub profile: ProfileKey,
    /// Strictly increasing process-local start attempt, never durable identity.
    pub revision: u64,
    /// Persisted public configuration revision; stable across stop/restart.
    pub profile_revision: u32,
    pub network: String,
    pub identity_ref: String,
}
fn validate_spec(spec: &NodeSpec, provider: Provider) -> Result<()> {
    if spec.profile.provider != provider
        || spec.revision == 0
        || spec.profile_revision == 0
        || spec.profile.id.is_empty()
        || spec.profile.id.len() > 128
        || !spec
            .profile
            .id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        || spec.network.is_empty()
        || spec.network.len() > 256
        || spec.network.chars().any(char::is_control)
        || spec.identity_ref.is_empty()
        || spec.identity_ref.len() > 256
        || spec.identity_ref.chars().any(char::is_control)
    {
        return Err(Failure::InvalidRoute);
    }
    Ok(())
}

/// A short-lived borrowed configuration, deliberately neither Debug nor Clone.
/// Does not save to disk. Best-effort overwrite does not erase engine copies.
pub struct SecretConfig(Vec<u8>);
impl SecretConfig {
    pub fn from_bytes(bytes: Vec<u8>) -> Result<Self> {
        if bytes.is_empty() || bytes.len() > MAX_IO || bytes.contains(&0) {
            return Err(Failure::InvalidRoute);
        }
        Ok(Self(bytes))
    }
    #[cfg(feature = "linked-easytier")]
    pub(crate) fn nul_terminated(bytes: Vec<u8>) -> Self {
        Self(bytes)
    }
    #[cfg(feature = "linked-easytier")]
    pub(crate) fn bytes(&self) -> &[u8] {
        &self.0
    }
}
impl Drop for SecretConfig {
    fn drop(&mut self) {
        for byte in &mut self.0 {
            // SAFETY: exclusively owned initialized bytes; prevent dead-store removal.
            unsafe {
                std::ptr::write_volatile(byte, 0);
            }
        }
    }
}
/// Host integration must load only this device's safe-storage reference and
/// construct an in-memory configuration. Do not implement a plaintext fallback.
/// Host crates inject their own platform implementation; none is built in here.
pub trait SecureConfigSource: Send + Sync + 'static {
    fn load(&self, spec: &NodeSpec) -> Result<SecretConfig>;
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NodeStatus {
    Starting,
    EngineStarted,
    NeedsLogin,
    NeedsMachineAuth,
    Running,
    Closing,
    Stopped,
}
/// Immutable saved binding + one runtime start attempt. Never exposes native ID.
#[derive(Clone)]
pub struct NodeLease {
    entry: Arc<NodeEntry>,
    runtime: Weak<Inner>,
}
impl NodeLease {
    pub fn profile(&self) -> &ProfileKey {
        &self.entry.spec.profile
    }
    pub fn revision(&self) -> u64 {
        self.entry.spec.revision
    }
    pub fn profile_revision(&self) -> u32 {
        self.entry.spec.profile_revision
    }
    /// Safe-storage reference only, never identity state or secret config.
    pub fn identity_ref(&self) -> &str {
        &self.entry.spec.identity_ref
    }
    pub fn evidence(&self) -> Evidence {
        self.entry.backend.evidence()
    }
}
pub(super) struct NodeEntry {
    spec: NodeSpec,
    profile: Arc<Profile>,
    backend: Arc<dyn ManagedBackend>,
    pending: AtomicBool,
    admission_retired: AtomicBool,
    // Covers admission through native login/status return. Stop closes
    // admission first and waits for this lease before native teardown.
    login_busy: AtomicBool,
    start_cancelled: Arc<AtomicBool>,
    start_completion: Mutex<Option<Weak<Completion<NodeLease>>>>,
    closing: AtomicBool,
    stop_busy: AtomicBool,
    cleanup_requested: AtomicBool,
    stopped: AtomicBool,
}

struct LoginAdmission<'a>(&'a NodeEntry);
impl<'a> LoginAdmission<'a> {
    fn acquire(entry: &'a NodeEntry) -> Result<Self> {
        // SeqCst pairs with retire_admission + the stop worker's busy load:
        // either stop sees this claim or this worker sees retirement.
        entry
            .login_busy
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| Failure::Busy)?;
        Ok(Self(entry))
    }
}
impl Drop for LoginAdmission<'_> {
    fn drop(&mut self) {
        self.0.login_busy.store(false, Ordering::Release);
    }
}

impl NodeEntry {
    /// Called with the runtime registry held, shared with start activation.
    pub(super) fn retire_admission(&self) -> bool {
        self.admission_retired.store(true, Ordering::SeqCst);
        self.profile.active.store(false, Ordering::Release);
        let pending = self.pending.load(Ordering::Acquire);
        if pending {
            self.closing.store(true, Ordering::Release);
            self.start_cancelled.store(true, Ordering::Release);
        }
        pending
    }
    fn wake_detached_start(&self) {
        let completion = lock(&self.start_completion)
            .as_ref()
            .and_then(Weak::upgrade);
        if let Some(completion) = completion {
            completion.changed.notify_all();
            let waker = { lock(&completion.waker).take() };
            if let Some(waker) = waker {
                waker.wake();
            }
        }
    }
}

/// Await from the UI executor. Foreign calls always stay on owned workers.
/// Dropping/cancelling start retires its original revision; late completion
/// drains/stops that node, never attaches it to a later revision.
pub struct NodeOperation<T> {
    completion: Arc<Completion<T>>,
    cancelled: Arc<AtomicBool>,
    on_cancel: Option<Box<dyn Fn() + Send + Sync>>,
    consumed: bool,
}
impl<T> NodeOperation<T> {
    fn new(on_cancel: Option<Box<dyn Fn() + Send + Sync>>) -> Self {
        Self {
            completion: Arc::new(Completion {
                value: Mutex::new(None),
                changed: Condvar::new(),
                waker: Mutex::new(None),
            }),
            cancelled: Arc::new(AtomicBool::new(false)),
            on_cancel,
            consumed: false,
        }
    }
    pub fn cancel(&self) {
        if !self.cancelled.swap(true, Ordering::SeqCst) {
            if let Some(callback) = &self.on_cancel {
                callback();
            }
            self.completion.changed.notify_all();
            if let Some(waker) = lock(&self.completion.waker).take() {
                waker.wake();
            }
        }
    }
    pub fn try_result(&mut self) -> Option<Result<T>> {
        if self.consumed {
            return Some(Err(Failure::Cancelled));
        }
        if self.cancelled.load(Ordering::Acquire) {
            self.consumed = true;
            return Some(Err(Failure::Cancelled));
        }
        let result = lock(&self.completion.value).take();
        if result.is_some() {
            self.consumed = true;
        }
        result
    }
    pub fn wait(mut self, timeout: Duration) -> Result<T> {
        if !valid_deadline(timeout) {
            return Err(Failure::InvalidDeadline);
        }
        let until = Instant::now() + timeout;
        loop {
            if let Some(result) = self.try_result() {
                return result;
            }
            let Some(remaining) = until.checked_duration_since(Instant::now()) else {
                return Err(Failure::WaitTimeout);
            };
            let guard = lock(&self.completion.value);
            drop(
                self.completion
                    .changed
                    .wait_timeout(guard, remaining.min(Duration::from_millis(10))),
            );
        }
    }
}
impl<T> Future for NodeOperation<T> {
    type Output = Result<T>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        if let Some(result) = this.try_result() {
            return Poll::Ready(result);
        }
        *lock(&this.completion.waker) = Some(cx.waker().clone());
        match this.try_result() {
            Some(result) => Poll::Ready(result),
            None => Poll::Pending,
        }
    }
}
impl<T> Drop for NodeOperation<T> {
    fn drop(&mut self) {
        if !self.consumed {
            self.cancel();
        }
    }
}

impl OverlayRuntime {
    pub fn start_easytier_profile(
        &self,
        spec: NodeSpec,
        source: Option<Arc<dyn SecureConfigSource>>,
        deadline: Duration,
    ) -> Result<NodeOperation<NodeLease>> {
        let source = source.ok_or(Failure::IdentityUnavailable)?;
        self.require_provider(Provider::EasyTier)?;
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        validate_spec(&spec, Provider::EasyTier)?;
        let backend = Arc::new(EasyTierBackend::managed(&spec.network)?);
        let starter = backend.clone();
        self.start_managed_profile(
            spec,
            backend,
            move |spec| source.load(spec),
            move |config, deadline| starter.start_node(&config, deadline),
            deadline,
        )
    }
    pub fn start_tailscale_profile(
        &self,
        spec: NodeSpec,
        source: Option<Arc<dyn NativeStateSource>>,
        deadline: Duration,
    ) -> Result<NodeOperation<NodeLease>> {
        let source = source.ok_or(Failure::IdentityUnavailable)?;
        self.require_provider(Provider::Tailscale)?;
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        validate_spec(&spec, Provider::Tailscale)?;
        let backend = Arc::new(TailscaleBackend::managed(&spec)?);
        let starter = backend.clone();
        self.start_managed_profile(
            spec,
            backend,
            move |spec| source.load(spec),
            move |config, deadline| starter.start_node(config, deadline),
            deadline,
        )
    }
    fn start_managed_profile<C, L, S>(
        &self,
        spec: NodeSpec,
        backend: Arc<dyn ManagedBackend>,
        load: L,
        start: S,
        deadline: Duration,
    ) -> Result<NodeOperation<NodeLease>>
    where
        C: Send + 'static,
        L: FnOnce(&NodeSpec) -> Result<C> + Send + 'static,
        S: FnOnce(C, Duration) -> Result<()> + Send + 'static,
    {
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        validate_spec(&spec, backend.provider())?;
        let profile = Arc::new(Profile {
            backend: backend.clone(),
            revision: spec.revision,
            active: AtomicBool::new(false),
        });
        let entry = Arc::new(NodeEntry {
            spec,
            profile: profile.clone(),
            backend,
            pending: AtomicBool::new(true),
            admission_retired: AtomicBool::new(false),
            login_busy: AtomicBool::new(false),
            start_cancelled: Arc::new(AtomicBool::new(false)),
            start_completion: Mutex::new(None),
            closing: AtomicBool::new(false),
            stop_busy: AtomicBool::new(false),
            cleanup_requested: AtomicBool::new(false),
            stopped: AtomicBool::new(false),
        });
        {
            let mut registry = lock(&self.inner.registry);
            if registry.nodes.contains_key(&entry.spec.profile)
                || registry.profiles.get(&entry.spec.profile).is_some_and(|p| {
                    p.active.load(Ordering::Acquire)
                        || registry
                            .entries
                            .values()
                            .any(|e| Arc::ptr_eq(&e.profile, p))
                })
            {
                return Err(Failure::Busy);
            }
            if registry
                .revisions
                .get(&entry.spec.profile)
                .is_some_and(|r| *r >= entry.spec.revision)
            {
                return Err(Failure::StaleRevision);
            }
            if registry.nodes.len() >= MAX_NODES {
                return Err(Failure::Capacity);
            }
            registry
                .revisions
                .insert(entry.spec.profile.clone(), entry.spec.revision);
            registry
                .profiles
                .insert(entry.spec.profile.clone(), profile);
            registry
                .nodes
                .insert(entry.spec.profile.clone(), entry.clone());
        }
        let inner = self.inner.clone();
        let cancel_entry = entry.clone();
        let cancel_inner = inner.clone();
        let mut operation = NodeOperation::new(Some(Box::new(move || {
            cancel_entry.closing.store(true, Ordering::Release);
            cancel_entry.profile.active.store(false, Ordering::Release);
            cancel_inner.spawn_node_stop(cancel_entry.clone(), deadline, None);
        })));
        operation.cancelled = entry.start_cancelled.clone();
        *lock(&entry.start_completion) = Some(Arc::downgrade(&operation.completion));
        let completion = operation.completion.clone();
        let cancelled = operation.cancelled.clone();
        let owned = entry.clone();
        if thread::Builder::new()
            .name("overlay-node-start".into())
            .spawn(move || {
                let result = if cancelled.load(Ordering::Acquire)
                    || owned.admission_retired.load(Ordering::Acquire)
                {
                    Err(Failure::Cancelled)
                } else {
                    load(&owned.spec).and_then(|config| {
                        if cancelled.load(Ordering::Acquire)
                            || owned.admission_retired.load(Ordering::Acquire)
                        {
                            Err(Failure::Cancelled)
                        } else {
                            start(config, deadline)
                        }
                    })
                };
                // Registry mutex serializes readiness with retirement and replacement.
                {
                    let registry = lock(&inner.registry);
                    if result.is_ok()
                        && !owned.closing.load(Ordering::Acquire)
                        && !owned.admission_retired.load(Ordering::Acquire)
                        && !cancelled.load(Ordering::Acquire)
                        && registry
                            .nodes
                            .get(&owned.spec.profile)
                            .is_some_and(|n| Arc::ptr_eq(n, &owned))
                    {
                        owned.profile.active.store(true, Ordering::Release);
                    } else {
                        owned.closing.store(true, Ordering::Release);
                    }
                    owned.pending.store(false, Ordering::Release);
                }
                if owned.closing.load(Ordering::Acquire) {
                    inner.spawn_node_stop(owned.clone(), deadline, None);
                    completion.finish(Err(result.err().unwrap_or(Failure::Cancelled)));
                } else {
                    completion.finish(Ok(NodeLease {
                        entry: owned,
                        runtime: Arc::downgrade(&inner),
                    }));
                }
            })
            .is_err()
        {
            entry.pending.store(false, Ordering::Release);
            entry.closing.store(true, Ordering::Release);
            self.inner.spawn_node_stop(entry, deadline, None);
            operation.completion.finish(Err(Failure::WorkerUnavailable));
        }
        Ok(operation)
    }
    fn owned_node(&self, lease: &NodeLease) -> Result<Arc<NodeEntry>> {
        if !lease
            .runtime
            .upgrade()
            .is_some_and(|r| Arc::ptr_eq(&r, &self.inner))
        {
            return Err(Failure::WrongOwner);
        }
        Ok(lease.entry.clone())
    }
    /// Open only the exact app-owned node epoch, never a same-name node from
    /// another runtime. Admission/revision is checked again by open_revision.
    pub fn open_node(
        &self,
        owner: &Owner,
        node: &NodeLease,
        host: &str,
        port: u16,
        deadline: Duration,
    ) -> Result<Operation<StreamLease>> {
        let entry = self.owned_node(node)?;
        if !lock(&self.inner.registry)
            .nodes
            .get(node.profile())
            .is_some_and(|current| Arc::ptr_eq(current, &entry))
        {
            return Err(Failure::StaleRevision);
        }
        // Exact profile Arc is checked again while open holds the admission
        // lock, so even a same-revision replacement cannot race this lease.
        self.open_checked(
            owner,
            node.profile(),
            OpenRoute::Node(&entry.profile),
            host,
            port,
            deadline,
        )
    }
    /// Observe one exact attempt, including pending/failed start cleanup for
    /// which no NodeLease was delivered. Never follows a replacement attempt.
    pub fn node_status_revision(
        &self,
        key: &ProfileKey,
        revision: u64,
    ) -> Result<NodeOperation<NodeStatus>> {
        let entry = lock(&self.inner.registry)
            .nodes
            .get(key)
            .cloned()
            .ok_or(Failure::ProfileMissing)?;
        if entry.spec.revision != revision {
            return Err(Failure::StaleRevision);
        }
        self.node_status(&NodeLease {
            entry,
            runtime: Arc::downgrade(&self.inner),
        })
    }
    pub fn node_status(&self, lease: &NodeLease) -> Result<NodeOperation<NodeStatus>> {
        let entry = self.owned_node(lease)?;
        let operation = NodeOperation::new(None);
        let completion = operation.completion.clone();
        if thread::Builder::new()
            .name("overlay-node-status".into())
            .spawn(move || {
                let result = if entry.stopped.load(Ordering::Acquire) {
                    Ok(NodeStatus::Stopped)
                } else if entry.closing.load(Ordering::Acquire) {
                    Ok(NodeStatus::Closing)
                } else if entry.pending.load(Ordering::Acquire) {
                    Ok(NodeStatus::Starting)
                } else {
                    entry.backend.managed_status()
                };
                let result = if entry.stopped.load(Ordering::Acquire) {
                    Ok(NodeStatus::Stopped)
                } else if entry.closing.load(Ordering::Acquire) {
                    Ok(NodeStatus::Closing)
                } else {
                    result
                };
                completion.finish(result);
            })
            .is_err()
        {
            operation.completion.finish(Err(Failure::WorkerUnavailable));
        }
        Ok(operation)
    }
    /// Explicit login only. No retry and no raw backend logs. Cancellation
    /// before admission prevents dispatch; after admission it discards the
    /// result. Stop waits for admitted work before native teardown. No retry.
    pub fn begin_node_login(
        &self,
        lease: &NodeLease,
        deadline: Duration,
    ) -> Result<NodeOperation<LoginStatus>> {
        self.login_operation(lease, deadline, true, None)
    }
    /// Native worker checks the caller's original cancellation at admission.
    /// The checker must be nonblocking and observe the caller's cancellation
    /// using sequentially consistent atomic operations.
    pub fn begin_node_login_with_cancel_check(
        &self,
        lease: &NodeLease,
        deadline: Duration,
        check: Arc<dyn Fn() -> bool + Send + Sync>,
    ) -> Result<NodeOperation<LoginStatus>> {
        self.login_operation(lease, deadline, true, Some(check))
    }
    /// Read only; never reissues interactive authentication. Native keeps URLs
    /// hidden until an explicit login was requested on this exact node.
    pub fn node_login_status(
        &self,
        lease: &NodeLease,
        deadline: Duration,
    ) -> Result<NodeOperation<LoginStatus>> {
        self.login_operation(lease, deadline, false, None)
    }
    /// Read-only counterpart with the same original-cancellation admission check.
    pub fn node_login_status_with_cancel_check(
        &self,
        lease: &NodeLease,
        deadline: Duration,
        check: Arc<dyn Fn() -> bool + Send + Sync>,
    ) -> Result<NodeOperation<LoginStatus>> {
        self.login_operation(lease, deadline, false, Some(check))
    }
    fn login_operation(
        &self,
        lease: &NodeLease,
        deadline: Duration,
        begin: bool,
        external_cancel: Option<Arc<dyn Fn() -> bool + Send + Sync>>,
    ) -> Result<NodeOperation<LoginStatus>> {
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        let entry = self.owned_node(lease)?;
        if entry.closing.load(Ordering::Acquire)
            || entry.stopped.load(Ordering::Acquire)
            || entry.pending.load(Ordering::Acquire)
            || entry.admission_retired.load(Ordering::Acquire)
        {
            return Err(Failure::ProfileUnavailable);
        }
        let operation = NodeOperation::new(None);
        let completion = operation.completion.clone();
        let cancelled = operation.cancelled.clone();
        if thread::Builder::new()
            .name("overlay-node-login".into())
            .spawn(move || {
                let result = {
                    // Claim before checking retirement: stop either observes
                    // this lease, or retires first and this worker refuses.
                    // No queued worker can call a backend after a completed
                    // stop. Concurrent polls/logins return Busy, never replay.
                    let check_external = || {
                        external_cancel.as_ref().is_some_and(|check| {
                            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| check()))
                                .unwrap_or(true)
                        })
                    };
                    // Early rejection is not admission. The CAS below is the
                    // linearization point shared with retirement and stop.
                    let admission = if check_external() {
                        Err(Failure::Cancelled)
                    } else {
                        LoginAdmission::acquire(&entry)
                    };
                    match admission {
                        Err(error) => Err(error),
                        Ok(_admission) => {
                            if cancelled.load(Ordering::SeqCst)
                                || check_external()
                                || entry.admission_retired.load(Ordering::SeqCst)
                            {
                                Err(Failure::Cancelled)
                            } else if begin {
                                entry.backend.managed_login(deadline)
                            } else {
                                entry.backend.managed_login_status(deadline)
                            }
                        }
                    }
                };
                completion.finish(
                    if entry.closing.load(Ordering::Acquire)
                        || entry.stopped.load(Ordering::Acquire)
                        || entry.admission_retired.load(Ordering::Acquire)
                    {
                        Err(Failure::Cancelled)
                    } else {
                        result
                    },
                );
            })
            .is_err()
        {
            operation.completion.finish(Err(Failure::WorkerUnavailable));
        }
        Ok(operation)
    }
    pub fn stop_node(&self, lease: &NodeLease, deadline: Duration) -> Result<NodeOperation<()>> {
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        let entry = self.owned_node(lease)?;
        let operation = NodeOperation::new(None);
        self.inner
            .spawn_node_stop(entry, deadline, Some(operation.completion.clone()));
        Ok(operation)
    }
    /// Includes starting, failed-start cleanup, drain and failed-stop nodes.
    pub fn reserved_nodes(&self) -> usize {
        lock(&self.inner.registry).nodes.len()
    }
    /// Retry cleanup by exact profile revision after a failed/cancelled start.
    /// It never starts the node again and cannot retire a newer revision.
    pub fn retry_node_cleanup(
        &self,
        key: &ProfileKey,
        revision: u64,
        deadline: Duration,
    ) -> Result<NodeOperation<()>> {
        let entry = lock(&self.inner.registry)
            .nodes
            .get(key)
            .cloned()
            .ok_or(Failure::ProfileMissing)?;
        if entry.spec.revision != revision {
            return Err(Failure::StaleRevision);
        }
        self.stop_node(
            &NodeLease {
                entry,
                runtime: Arc::downgrade(&self.inner),
            },
            deadline,
        )
    }
    pub(super) fn stop_nodes_on_drop(&self) {
        let entries: Vec<_> = lock(&self.inner.registry).nodes.values().cloned().collect();
        for entry in entries {
            self.inner.spawn_node_stop(entry, MAX_DEADLINE, None);
        }
    }
}
impl Inner {
    pub(super) fn finish_profile_detach(
        self: &Arc<Self>,
        entry: Arc<NodeEntry>,
        was_pending: bool,
    ) {
        // Wake outside the registry lock: an executor's Wake may reenter us.
        entry.wake_detached_start();
        if was_pending {
            self.spawn_node_stop(entry, MAX_DEADLINE, None);
        }
    }
    fn spawn_node_stop(
        self: &Arc<Self>,
        entry: Arc<NodeEntry>,
        deadline: Duration,
        completion: Option<Arc<Completion<()>>>,
    ) {
        // Admission closes under the same registry mutex used by open/start ready.
        let was_pending = {
            let _registry = lock(&self.registry);
            entry.closing.store(true, Ordering::Release);
            entry.retire_admission()
        };
        if was_pending {
            entry.wake_detached_start();
        }
        if entry.stopped.load(Ordering::Acquire) {
            if let Some(c) = completion {
                c.finish(Ok(()));
            }
            return;
        }
        if entry.stop_busy.swap(true, Ordering::AcqRel) {
            if completion.is_none() {
                entry.cleanup_requested.store(true, Ordering::Release);
            }
            if let Some(c) = completion {
                c.finish(Err(Failure::Busy));
            }
            return;
        }
        let inner = self.clone();
        let owned = entry.clone();
        let completed = completion.clone();
        if thread::Builder::new()
            .name("overlay-node-stop".into())
            .spawn(move || {
                let until = Instant::now() + deadline;
                let streams: Vec<_> = lock(&inner.registry)
                    .entries
                    .values()
                    .filter(|e| Arc::ptr_eq(&e.profile, &owned.profile))
                    .cloned()
                    .collect();
                for stream in streams {
                    inner.cancel(&stream);
                }
                let mut native_stop_attempted = false;
                let result = loop {
                    let drained = !owned.pending.load(Ordering::Acquire)
                        && !owned.login_busy.load(Ordering::SeqCst)
                        && !lock(&inner.registry)
                            .entries
                            .values()
                            .any(|e| Arc::ptr_eq(&e.profile, &owned.profile));
                    if drained {
                        let remaining = until.saturating_duration_since(Instant::now());
                        break if remaining.is_zero() {
                            Err(Failure::ClosePending)
                        } else {
                            native_stop_attempted = true;
                            owned.backend.managed_stop(remaining)
                        };
                    }
                    if Instant::now() >= until {
                        break Err(Failure::ClosePending);
                    }
                    thread::sleep(Duration::from_millis(2));
                };
                if result.is_ok() {
                    owned.stopped.store(true, Ordering::Release);
                    let mut registry = lock(&inner.registry);
                    if registry
                        .nodes
                        .get(&owned.spec.profile)
                        .is_some_and(|n| Arc::ptr_eq(n, &owned))
                    {
                        registry.nodes.remove(&owned.spec.profile);
                    }
                }
                owned.stop_busy.store(false, Ordering::Release);
                if let Some(c) = completed {
                    c.finish(result);
                }
                // If late start requested cleanup while this worker was exiting,
                // hand that request to a fresh worker. Never replay start.
                if owned.cleanup_requested.swap(false, Ordering::AcqRel)
                    && !native_stop_attempted
                    && !owned.pending.load(Ordering::Acquire)
                    && !owned.stopped.load(Ordering::Acquire)
                {
                    inner.spawn_node_stop(owned, deadline, None);
                }
            })
            .is_err()
        {
            entry.stop_busy.store(false, Ordering::Release);
            if let Some(c) = completion {
                c.finish(Err(Failure::WorkerUnavailable));
            }
        }
    }
}

#[cfg(all(test, not(feature = "linked-easytier")))]
mod unavailable_tests {
    use super::*;
    struct MustNotLoad;
    impl SecureConfigSource for MustNotLoad {
        fn load(&self, _: &NodeSpec) -> Result<SecretConfig> {
            panic!("missing bridge must refuse before identity load")
        }
    }
    #[test]
    fn missing_bridge_and_secure_store_fail_closed_without_identity_access() {
        let runtime = OverlayRuntime::new();
        let spec = NodeSpec {
            profile: ProfileKey {
                provider: Provider::EasyTier,
                id: "no-bridge".into(),
            },
            revision: 1,
            profile_revision: 1,
            network: "synthetic".into(),
            identity_ref: "synthetic-ref".into(),
        };
        assert!(matches!(
            runtime.start_easytier_profile(spec.clone(), None, Duration::from_secs(1)),
            Err(Failure::IdentityUnavailable)
        ));
        assert!(matches!(
            runtime.start_easytier_profile(
                spec,
                Some(Arc::new(MustNotLoad)),
                Duration::from_secs(1)
            ),
            Err(Failure::ProviderUnavailable)
        ));
        assert_eq!(runtime.reserved_nodes(), 0);
    }
}
