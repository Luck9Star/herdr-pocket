//! Foreground transport ownership experiment. No node starts, identities,
//! system TCP/DNS fallback, GUI integration, or verified overlay connectivity.
use std::{
    collections::HashMap,
    future::Future,
    pin::Pin,
    sync::{
        Arc, Condvar, Mutex, MutexGuard, Weak,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    task::{Context, Poll, Waker},
    thread,
    time::{Duration, Instant},
};

pub mod easytier;
pub mod nodes;

pub const MAX_STREAMS: usize = 32;
pub const MAX_IO: usize = 65_536;
pub const MAX_DEADLINE: Duration = Duration::from_secs(60);

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Provider {
    EasyTier,
    Tailscale,
    ZeroTier,
}
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ProfileKey {
    pub provider: Provider,
    pub id: String,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Evidence {
    CandidateAbiOnly,
    SyntheticNativeFixture,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Failure {
    ProviderUnavailable,
    IdentityUnavailable,
    StaleRevision,
    InvalidRoute,
    InvalidDeadline,
    WrongOwner,
    ProfileMissing,
    ProfileUnavailable,
    Capacity,
    Cancelled,
    Busy,
    WorkerUnavailable,
    NativeRejected(i32),
    NativeRead(i32),
    /// Read deadline expired after a cancel-safe native read returned without
    /// consuming bytes. Unlike an unknown write, the same read may continue.
    ReadTimedOut,
    UnknownWrite,
    ClosePending,
    WaitTimeout,
    InvalidNativeResponse,
}
pub type Result<T> = std::result::Result<T, Failure>;

/// Implementors must return handles only for this provider/profile, never use
/// system TCP as an overlay fallback, and keep native code loaded for self's
/// entire lifetime. open's Err must own no native handle; close must be safe
/// concurrently with read/write and unblock them. No write retries are allowed.
pub trait Backend: Send + Sync + 'static {
    fn provider(&self) -> Provider;
    fn evidence(&self) -> Evidence;
    fn open(&self, host: &str, port: u16, deadline: Duration) -> Result<u64>;
    /// ReadTimedOut is allowed only after this call has fully stopped without
    /// consuming bytes; no late native read may remain in flight.
    fn read(&self, handle: u64, max: usize, deadline: Duration) -> Result<Vec<u8>>;
    /// A positive count is only the locally accepted prefix, not remote delivery.
    fn write(&self, handle: u64, bytes: &[u8], deadline: Duration) -> Result<usize>;
    fn shutdown_write(&self, handle: u64, deadline: Duration) -> Result<()>;
    fn close(&self, handle: u64) -> Result<()>;
}

fn lock<T>(value: &Mutex<T>) -> MutexGuard<'_, T> {
    value.lock().unwrap_or_else(|poison| poison.into_inner())
}
fn valid_deadline(value: Duration) -> bool {
    !value.is_zero() && value <= MAX_DEADLINE
}
fn valid_host(host: &str) -> bool {
    !host.is_empty()
        && host.len() <= 253
        && host
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
        && !host.starts_with('.')
        && !host.ends_with('.')
}
struct Profile {
    backend: Arc<dyn Backend>,
    revision: u64,
    active: AtomicBool,
}
enum OpenRoute<'a> {
    Legacy,
    Revision(u64),
    Node(&'a Arc<Profile>),
}
struct OwnerState {
    runtime: Arc<()>,
    active: AtomicBool,
}
#[derive(Clone)]
pub struct Owner {
    state: Arc<OwnerState>,
}
#[derive(Clone)]
pub struct StreamLease {
    entry: Arc<Entry>,
}
impl StreamLease {
    pub fn profile(&self) -> &ProfileKey {
        &self.entry.profile_key
    }
    pub fn evidence(&self) -> Evidence {
        self.entry.profile.backend.evidence()
    }
    /// Runtime admission revision (managed start attempt), not the persisted
    /// public profile revision. Zero denotes the legacy external backend.
    pub fn profile_revision(&self) -> u64 {
        self.entry.profile.revision
    }
    /// open allocates a pending native handle. No API here claims TCP readiness.
    pub fn is_active(&self) -> bool {
        self.entry.active()
    }
}
struct Entry {
    id: u64,
    runtime: Weak<Inner>,
    owner: Arc<OwnerState>,
    profile: Arc<Profile>,
    profile_key: ProfileKey,
    handle: Mutex<Option<u64>>,
    closing: AtomicBool,
    close_started: AtomicBool,
    native_closed: AtomicBool,
    read_busy: AtomicBool,
    write_busy: AtomicBool,
    next_operation: AtomicU64,
    wakers: Mutex<HashMap<u64, Waker>>,
}
impl Entry {
    fn active(&self) -> bool {
        !self.closing.load(Ordering::Acquire)
            && self.owner.active.load(Ordering::Acquire)
            && self.profile.active.load(Ordering::Acquire)
    }
    fn wake(&self) {
        let wakers: Vec<_> = lock(&self.wakers).drain().map(|(_, value)| value).collect();
        for waker in wakers {
            waker.wake();
        }
    }
}
struct Registry {
    next_id: u64,
    entries: HashMap<u64, Arc<Entry>>,
    profiles: HashMap<ProfileKey, Arc<Profile>>,
    nodes: HashMap<ProfileKey, Arc<nodes::NodeEntry>>,
    revisions: HashMap<ProfileKey, u64>,
}
struct Inner {
    identity: Arc<()>,
    registry: Mutex<Registry>,
}

impl Inner {
    fn remove(&self, entry: &Entry) {
        lock(&self.registry).entries.remove(&entry.id);
        entry.wake();
    }
    fn cancel(self: &Arc<Self>, entry: &Arc<Entry>) {
        entry.closing.store(true, Ordering::Release);
        entry.wake();
        // A pending native open keeps its budget. Its own completion registers
        // and closes the late handle; cancellation cannot release that slot.
        if lock(&entry.handle).is_none() {
            return;
        }
        if entry.close_started.swap(true, Ordering::AcqRel) {
            return;
        }
        let inner = self.clone();
        let owned = entry.clone();
        if thread::Builder::new()
            .name("overlay-close".into())
            .spawn(move || {
                let Some(handle) = lock(&owned.handle).take() else {
                    return;
                };
                if owned.profile.backend.close(handle).is_ok() {
                    owned.native_closed.store(true, Ordering::Release);
                    if !owned.read_busy.load(Ordering::Acquire)
                        && !owned.write_busy.load(Ordering::Acquire)
                    {
                        inner.remove(&owned);
                    }
                } else {
                    // Cleanup failure retains its native handle and global budget.
                    // An explicit close retry is permitted; opening more is not.
                    *lock(&owned.handle) = Some(handle);
                    owned.close_started.store(false, Ordering::Release);
                    owned.wake();
                }
            })
            .is_err()
        {
            entry.close_started.store(false, Ordering::Release);
        }
    }
}

pub struct OverlayRuntime {
    inner: Arc<Inner>,
}
impl Default for OverlayRuntime {
    fn default() -> Self {
        Self::new()
    }
}
impl OverlayRuntime {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Inner {
                identity: Arc::new(()),
                registry: Mutex::new(Registry {
                    next_id: 1,
                    entries: HashMap::new(),
                    profiles: HashMap::new(),
                    nodes: HashMap::new(),
                    revisions: HashMap::new(),
                }),
            }),
        }
    }
    pub fn new_owner(&self) -> Owner {
        Owner {
            state: Arc::new(OwnerState {
                runtime: self.inner.identity.clone(),
                active: AtomicBool::new(true),
            }),
        }
    }
    pub fn attach_profile(&self, key: ProfileKey, backend: Arc<dyn Backend>) -> Result<()> {
        if key.provider != backend.provider()
            || key.id.is_empty()
            || key.id.len() > 128
            || !key
                .id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return Err(Failure::InvalidRoute);
        }
        let mut registry = lock(&self.inner.registry);
        if registry.nodes.contains_key(&key) {
            return Err(Failure::Busy);
        }
        if let Some(previous) = registry.profiles.get(&key)
            && (previous.active.load(Ordering::Acquire)
                || registry
                    .entries
                    .values()
                    .any(|e| Arc::ptr_eq(&e.profile, previous)))
        {
            return Err(Failure::Busy);
        }
        registry.profiles.insert(
            key,
            Arc::new(Profile {
                backend,
                revision: 0,
                active: AtomicBool::new(true),
            }),
        );
        Ok(())
    }
    /// No Tailscale/ZeroTier bridge is supplied by this crate. A caller cannot
    /// request one and silently receive EasyTier or ordinary TCP instead.
    pub fn require_provider(&self, provider: Provider) -> Result<()> {
        if provider == Provider::EasyTier && cfg!(feature = "linked-easytier") {
            Ok(())
        } else {
            Err(Failure::ProviderUnavailable)
        }
    }
    fn owner_valid(&self, owner: &Owner) -> bool {
        Arc::ptr_eq(&owner.state.runtime, &self.inner.identity)
            && owner.state.active.load(Ordering::Acquire)
    }
    fn lease_valid(&self, owner: &Owner, lease: &StreamLease) -> bool {
        self.owner_valid(owner)
            && Arc::ptr_eq(&owner.state, &lease.entry.owner)
            && lease.entry.active()
            && lease
                .entry
                .runtime
                .upgrade()
                .is_some_and(|r| Arc::ptr_eq(&r, &self.inner))
    }
    /// Legacy backend experiment. Managed profiles require open_revision.
    pub fn open(
        &self,
        owner: &Owner,
        key: &ProfileKey,
        host: &str,
        port: u16,
        deadline: Duration,
    ) -> Result<Operation<StreamLease>> {
        self.open_checked(owner, key, OpenRoute::Legacy, host, port, deadline)
    }
    pub fn open_revision(
        &self,
        owner: &Owner,
        key: &ProfileKey,
        revision: u64,
        host: &str,
        port: u16,
        deadline: Duration,
    ) -> Result<Operation<StreamLease>> {
        self.open_checked(
            owner,
            key,
            OpenRoute::Revision(revision),
            host,
            port,
            deadline,
        )
    }
    fn open_checked(
        &self,
        owner: &Owner,
        key: &ProfileKey,
        route: OpenRoute<'_>,
        host: &str,
        port: u16,
        deadline: Duration,
    ) -> Result<Operation<StreamLease>> {
        if !self.owner_valid(owner) {
            return Err(Failure::WrongOwner);
        }
        if !valid_host(host) || port == 0 {
            return Err(Failure::InvalidRoute);
        }
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        let entry = {
            let mut registry = lock(&self.inner.registry);
            let profile = registry
                .profiles
                .get(key)
                .cloned()
                .ok_or(Failure::ProfileMissing)?;
            if match route {
                OpenRoute::Revision(expected) => expected != profile.revision,
                OpenRoute::Legacy => profile.revision != 0,
                OpenRoute::Node(expected) => !Arc::ptr_eq(expected, &profile),
            } {
                return Err(Failure::StaleRevision);
            }
            if !profile.active.load(Ordering::Acquire) {
                return Err(Failure::ProfileUnavailable);
            }
            if registry.entries.len() >= MAX_STREAMS {
                return Err(Failure::Capacity);
            }
            let id = registry.next_id;
            registry.next_id = id.checked_add(1).ok_or(Failure::Capacity)?;
            let entry = Arc::new(Entry {
                id,
                runtime: Arc::downgrade(&self.inner),
                owner: owner.state.clone(),
                profile,
                profile_key: key.clone(),
                handle: Mutex::new(None),
                closing: AtomicBool::new(false),
                close_started: AtomicBool::new(false),
                native_closed: AtomicBool::new(false),
                read_busy: AtomicBool::new(false),
                write_busy: AtomicBool::new(false),
                next_operation: AtomicU64::new(1),
                wakers: Mutex::new(HashMap::new()),
            });
            registry.entries.insert(id, entry.clone());
            entry
        };
        let operation = Operation::new(self.inner.clone(), entry.clone(), false);
        let completion = operation.completion.clone();
        let inner = self.inner.clone();
        let host = host.to_owned();
        let owned = entry.clone();
        if thread::Builder::new()
            .name("overlay-open".into())
            .spawn(move || {
                if !owned.active() {
                    inner.remove(&owned);
                    completion.finish(Err(Failure::Cancelled));
                    return;
                }
                match owned.profile.backend.open(&host, port, deadline) {
                    Ok(handle) if handle != 0 => {
                        *lock(&owned.handle) = Some(handle);
                        if owned.active() {
                            completion.finish(Ok(StreamLease {
                                entry: owned.clone(),
                            }));
                        } else {
                            inner.cancel(&owned);
                            completion.finish(Err(Failure::Cancelled));
                        }
                    }
                    Ok(_) => {
                        inner.remove(&owned);
                        completion.finish(Err(Failure::InvalidNativeResponse));
                    }
                    Err(error) => {
                        inner.remove(&owned);
                        completion.finish(Err(error));
                    }
                }
            })
            .is_err()
        {
            self.inner.remove(&entry);
            operation.completion.finish(Err(Failure::WorkerUnavailable));
        }
        Ok(operation)
    }
    pub fn read(
        &self,
        owner: &Owner,
        lease: &StreamLease,
        max: usize,
        deadline: Duration,
    ) -> Result<Operation<Vec<u8>>> {
        if !self.lease_valid(owner, lease) {
            return Err(Failure::WrongOwner);
        }
        if max == 0 || max > MAX_IO {
            return Err(Failure::InvalidRoute);
        }
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        if lease.entry.read_busy.swap(true, Ordering::AcqRel) {
            return Err(Failure::Busy);
        }
        self.io(lease, false, false, move |backend, handle| {
            backend.read(handle, max, deadline)
        })
    }
    pub fn write(
        &self,
        owner: &Owner,
        lease: &StreamLease,
        bytes: Vec<u8>,
        deadline: Duration,
    ) -> Result<Operation<usize>> {
        if !self.lease_valid(owner, lease) {
            return Err(Failure::WrongOwner);
        }
        if bytes.is_empty() || bytes.len() > MAX_IO {
            return Err(Failure::InvalidRoute);
        }
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        if lease.entry.write_busy.swap(true, Ordering::AcqRel) {
            return Err(Failure::Busy);
        }
        self.io(lease, true, true, move |backend, handle| {
            backend.write(handle, &bytes, deadline)
        })
    }
    pub fn shutdown_write(
        &self,
        owner: &Owner,
        lease: &StreamLease,
        deadline: Duration,
    ) -> Result<Operation<()>> {
        if !self.lease_valid(owner, lease) {
            return Err(Failure::WrongOwner);
        }
        if !valid_deadline(deadline) {
            return Err(Failure::InvalidDeadline);
        }
        if lease.entry.write_busy.swap(true, Ordering::AcqRel) {
            return Err(Failure::Busy);
        }
        self.io(lease, true, true, move |backend, handle| {
            backend.shutdown_write(handle, deadline)
        })
    }
    fn io<T: Send + 'static>(
        &self,
        lease: &StreamLease,
        write_slot: bool,
        write_outcome: bool,
        call: impl FnOnce(&dyn Backend, u64) -> Result<T> + Send + 'static,
    ) -> Result<Operation<T>> {
        let entry = lease.entry.clone();
        let operation = Operation::new(self.inner.clone(), entry.clone(), write_outcome);
        let completion = operation.completion.clone();
        let owned = entry.clone();
        let inner = self.inner.clone();
        if thread::Builder::new()
            .name(
                if write_slot {
                    "overlay-write"
                } else {
                    "overlay-read"
                }
                .into(),
            )
            .spawn(move || {
                let handle = { *lock(&owned.handle) };
                let result = if !owned.active() {
                    Err(Failure::Cancelled)
                } else if let Some(handle) = handle {
                    call(owned.profile.backend.as_ref(), handle)
                } else {
                    Err(Failure::Cancelled)
                };
                // Native read/write never hold the lifecycle/handle lock, so close
                // has an independent worker and can interrupt either direction.
                if write_slot {
                    owned.write_busy.store(false, Ordering::Release);
                } else {
                    owned.read_busy.store(false, Ordering::Release);
                }
                if matches!(
                    &result,
                    Err(Failure::UnknownWrite | Failure::InvalidNativeResponse)
                ) {
                    inner.cancel(&owned);
                }
                if owned.native_closed.load(Ordering::Acquire)
                    && !owned.read_busy.load(Ordering::Acquire)
                    && !owned.write_busy.load(Ordering::Acquire)
                {
                    inner.remove(&owned);
                }
                completion.finish(result);
            })
            .is_err()
        {
            if write_slot {
                entry.write_busy.store(false, Ordering::Release);
            } else {
                entry.read_busy.store(false, Ordering::Release);
            }
            operation.completion.finish(Err(Failure::WorkerUnavailable));
        }
        Ok(operation)
    }
    pub fn close(&self, owner: &Owner, lease: &StreamLease) -> Result<()> {
        if !Arc::ptr_eq(&owner.state.runtime, &self.inner.identity)
            || !Arc::ptr_eq(&owner.state, &lease.entry.owner)
        {
            return Err(Failure::WrongOwner);
        }
        self.inner.cancel(&lease.entry);
        Ok(())
    }
    pub fn cancel_owner(&self, owner: &Owner) -> Result<usize> {
        if !Arc::ptr_eq(&owner.state.runtime, &self.inner.identity) {
            return Err(Failure::WrongOwner);
        }
        owner.state.active.store(false, Ordering::Release);
        let entries: Vec<_> = lock(&self.inner.registry)
            .entries
            .values()
            .filter(|entry| Arc::ptr_eq(&entry.owner, &owner.state))
            .cloned()
            .collect();
        for entry in &entries {
            self.inner.cancel(entry);
        }
        Ok(entries.len())
    }
    /// Permanently revokes this profile revision's admission and closes its
    /// streams. A pending managed start is cancelled and its late node cleaned
    /// up; an already-started node remains available for status/explicit stop.
    /// Never touches another profile/provider or persisted identity.
    pub fn detach_profile(&self, key: &ProfileKey) -> Result<usize> {
        let (entries, managed) = {
            let registry = lock(&self.inner.registry);
            let profile = registry.profiles.get(key).ok_or(Failure::ProfileMissing)?;
            profile.active.store(false, Ordering::Release);
            let managed = registry.nodes.get(key).map(|node| {
                let pending = node.retire_admission();
                (node.clone(), pending)
            });
            let entries = registry
                .entries
                .values()
                .filter(|entry| Arc::ptr_eq(&entry.profile, profile))
                .cloned()
                .collect::<Vec<_>>();
            (entries, managed)
        };
        for entry in &entries {
            self.inner.cancel(entry);
        }
        if let Some((node, pending)) = managed {
            self.inner.finish_profile_detach(node, pending);
        }
        Ok(entries.len())
    }
    /// Includes pending native opens and close workers until actual cleanup.
    pub fn reserved_streams(&self) -> usize {
        lock(&self.inner.registry).entries.len()
    }
}
impl Drop for OverlayRuntime {
    fn drop(&mut self) {
        let entries: Vec<_> = lock(&self.inner.registry)
            .entries
            .values()
            .cloned()
            .collect();
        for entry in entries {
            self.inner.cancel(&entry);
        }
        self.stop_nodes_on_drop();
    }
}

struct Completion<T> {
    value: Mutex<Option<Result<T>>>,
    changed: Condvar,
    waker: Mutex<Option<Waker>>,
}
impl<T> Completion<T> {
    fn finish(&self, result: Result<T>) {
        *lock(&self.value) = Some(result);
        self.changed.notify_all();
        let waker = { lock(&self.waker).take() };
        if let Some(waker) = waker {
            waker.wake();
        }
    }
}
/// Poll as a Future from the UI/core executor; blocking wait is for non-UI
/// callers/tests only. Dropping an unconsumed operation cancels its own stream.
pub struct Operation<T> {
    inner: Arc<Inner>,
    entry: Arc<Entry>,
    id: u64,
    completion: Arc<Completion<T>>,
    write_outcome: bool,
    consumed: bool,
}
impl<T> Operation<T> {
    fn new(inner: Arc<Inner>, entry: Arc<Entry>, write_outcome: bool) -> Self {
        let id = entry.next_operation.fetch_add(1, Ordering::Relaxed);
        Self {
            inner,
            entry,
            id,
            completion: Arc::new(Completion {
                value: Mutex::new(None),
                changed: Condvar::new(),
                waker: Mutex::new(None),
            }),
            write_outcome,
            consumed: false,
        }
    }
    fn cancelled_failure(&self) -> Failure {
        if self.write_outcome {
            Failure::UnknownWrite
        } else {
            Failure::Cancelled
        }
    }
    pub fn cancel(&self) {
        self.inner.cancel(&self.entry);
        self.completion.changed.notify_all();
    }
    pub fn try_result(&mut self) -> Option<Result<T>> {
        if self.consumed {
            return Some(Err(Failure::Cancelled));
        }
        if !self.entry.active() {
            self.consumed = true;
            lock(&self.entry.wakers).remove(&self.id);
            return Some(Err(self.cancelled_failure()));
        }
        let result = lock(&self.completion.value).take();
        if result.is_some() {
            self.consumed = true;
            lock(&self.entry.wakers).remove(&self.id);
        }
        result
    }
    pub fn wait(mut self, timeout: Duration) -> Result<T> {
        if !valid_deadline(timeout) {
            return Err(Failure::InvalidDeadline);
        }
        let until = Instant::now()
            .checked_add(timeout)
            .ok_or(Failure::InvalidDeadline)?;
        loop {
            if let Some(result) = self.try_result() {
                return result;
            }
            let Some(remaining) = until.checked_duration_since(Instant::now()) else {
                return Err(if self.write_outcome {
                    Failure::UnknownWrite
                } else {
                    Failure::WaitTimeout
                });
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
impl<T> Future for Operation<T> {
    type Output = Result<T>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        if let Some(result) = this.try_result() {
            return Poll::Ready(result);
        }
        *lock(&this.completion.waker) = Some(cx.waker().clone());
        lock(&this.entry.wakers).insert(this.id, cx.waker().clone());
        // Avoid missing completion/cancellation between inspection and waker registration.
        match this.try_result() {
            Some(result) => Poll::Ready(result),
            None => Poll::Pending,
        }
    }
}
impl<T> Drop for Operation<T> {
    fn drop(&mut self) {
        lock(&self.entry.wakers).remove(&self.id);
        if !self.consumed {
            self.inner.cancel(&self.entry);
        }
    }
}

#[cfg(all(test, feature = "native-fixture"))]
mod tests;
