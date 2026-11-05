use super::*;
use crate::easytier::EasyTierBackend;
use std::{sync::atomic::AtomicUsize, task::Wake};

unsafe extern "C" {
    fn fixture_reset();
    fn fixture_metric(metric: i32) -> i32;
    fn fixture_control(operation: i32);
}
static SERIAL: Mutex<()> = Mutex::new(());
const TIME: Duration = Duration::from_secs(2);
fn metric(index: i32) -> i32 {
    unsafe { fixture_metric(index) }
}
fn control(index: i32) {
    unsafe { fixture_control(index) }
}
fn until(predicate: impl Fn() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !predicate() {
        assert!(
            Instant::now() < deadline,
            "synthetic ABI fixture phase timed out"
        );
        thread::sleep(Duration::from_millis(2));
    }
}
fn isolated() -> MutexGuard<'static, ()> {
    let guard = lock(&SERIAL);
    until(|| metric(0) == 0 && metric(5) == 0);
    unsafe {
        fixture_reset();
    }
    guard
}
fn key(provider: Provider, id: &str) -> ProfileKey {
    ProfileKey {
        provider,
        id: id.into(),
    }
}
fn easy(runtime: &OverlayRuntime, id: &str, native_key: &str, network: &str) -> ProfileKey {
    let profile = key(Provider::EasyTier, id);
    runtime
        .attach_profile(
            profile.clone(),
            Arc::new(EasyTierBackend::linked(native_key, network).unwrap()),
        )
        .unwrap();
    profile
}
fn open(runtime: &OverlayRuntime, owner: &Owner, profile: &ProfileKey, host: &str) -> StreamLease {
    runtime
        .open(owner, profile, host, 22, TIME)
        .unwrap()
        .wait(TIME)
        .unwrap()
}
fn close(runtime: &OverlayRuntime, owner: &Owner, lease: &StreamLease) {
    runtime.close(owner, lease).unwrap();
}
fn drained(runtime: &OverlayRuntime) {
    until(|| runtime.reserved_streams() == 0 && metric(0) == 0 && metric(5) == 0);
}

#[test]
fn abi_full_duplex_read_does_not_block_write_or_half_close() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "phone-a", "instance-a", "network-a");
    let lease = open(&runtime, &owner, &profile, "read-block");
    assert_eq!(lease.evidence(), Evidence::SyntheticNativeFixture);
    let reader = runtime.read(&owner, &lease, 32, TIME).unwrap();
    until(|| metric(5) == 1);
    assert_eq!(
        runtime
            .write(&owner, &lease, b"A\xe4\xb8\xad".to_vec(), TIME)
            .unwrap()
            .wait(TIME),
        Ok(4)
    );
    assert_eq!(reader.wait(TIME).unwrap(), b"A\xe4\xb8\xad");
    runtime
        .shutdown_write(&owner, &lease, TIME)
        .unwrap()
        .wait(TIME)
        .unwrap();
    assert!(
        runtime
            .read(&owner, &lease, 32, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap()
            .is_empty()
    );
    close(&runtime, &owner, &lease);
    drained(&runtime);
    assert_eq!(metric(2), 1);
    assert_eq!(metric(4), 1);
}

#[test]
fn owner_and_runtime_tokens_reject_cross_host_calls_before_abi() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let other = runtime.new_owner();
    let foreign_runtime = OverlayRuntime::new();
    let foreign = foreign_runtime.new_owner();
    let profile = easy(&runtime, "profile", "owner-instance", "owner-network");
    let lease = open(&runtime, &owner, &profile, "echo");
    assert!(matches!(
        runtime.write(&other, &lease, b"wrong".to_vec(), TIME),
        Err(Failure::WrongOwner)
    ));
    assert!(matches!(
        runtime.read(&foreign, &lease, 1, TIME),
        Err(Failure::WrongOwner)
    ));
    assert_eq!(runtime.close(&other, &lease), Err(Failure::WrongOwner));
    assert!(matches!(
        foreign_runtime.open(&owner, &profile, "echo", 22, TIME),
        Err(Failure::WrongOwner)
    ));
    assert_eq!(metric(2), 0);
    assert_eq!(metric(3), 0);
    close(&runtime, &owner, &lease);
    close(&runtime, &owner, &lease);
    drained(&runtime);
    assert_eq!(metric(4), 1);
}

/// Routing-only second provider. It invokes the same failure-injecting C ABI
/// fixture; it is explicitly NOT a Tailscale implementation or network test.
struct FixtureSecondProvider(EasyTierBackend);
impl Backend for FixtureSecondProvider {
    fn provider(&self) -> Provider {
        Provider::Tailscale
    }
    fn evidence(&self) -> Evidence {
        Evidence::SyntheticNativeFixture
    }
    fn open(&self, host: &str, port: u16, deadline: Duration) -> Result<u64> {
        self.0.open(host, port, deadline)
    }
    fn read(&self, id: u64, max: usize, deadline: Duration) -> Result<Vec<u8>> {
        self.0.read(id, max, deadline)
    }
    fn write(&self, id: u64, bytes: &[u8], deadline: Duration) -> Result<usize> {
        self.0.write(id, bytes, deadline)
    }
    fn shutdown_write(&self, id: u64, deadline: Duration) -> Result<()> {
        self.0.shutdown_write(id, deadline)
    }
    fn close(&self, id: u64) -> Result<()> {
        self.0.close(id)
    }
}

#[test]
fn same_address_routes_stay_bound_to_provider_profile_and_native_network() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let a = runtime.new_owner();
    let b = runtime.new_owner();
    let c = runtime.new_owner();
    let first = easy(&runtime, "first", "instance-first", "network-first");
    let second = easy(&runtime, "second", "instance-second", "network-second");
    let third = key(Provider::Tailscale, "third-fixture");
    runtime
        .attach_profile(
            third.clone(),
            Arc::new(FixtureSecondProvider(
                EasyTierBackend::linked("synthetic-ts", "synthetic-network").unwrap(),
            )),
        )
        .unwrap();
    let one = open(&runtime, &a, &first, "100.64.0.9");
    let two = open(&runtime, &b, &second, "100.64.0.9");
    let three = open(&runtime, &c, &third, "100.64.0.9");
    assert_eq!(
        runtime
            .read(&a, &one, 128, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap(),
        b"instance-first|network-first"
    );
    assert_eq!(
        runtime
            .read(&b, &two, 128, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap(),
        b"instance-second|network-second"
    );
    assert_eq!(
        runtime
            .read(&c, &three, 128, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap(),
        b"synthetic-ts|synthetic-network"
    );
    assert_eq!(runtime.detach_profile(&first), Ok(1));
    until(|| !one.is_active());
    assert!(matches!(
        runtime.write(&a, &one, b"old".to_vec(), TIME),
        Err(Failure::WrongOwner)
    ));
    assert_eq!(
        runtime
            .write(&b, &two, b"only-b".to_vec(), TIME)
            .unwrap()
            .wait(TIME),
        Ok(6)
    );
    assert_eq!(
        runtime
            .write(&c, &three, b"only-c".to_vec(), TIME)
            .unwrap()
            .wait(TIME),
        Ok(6)
    );
    assert_eq!(
        runtime
            .read(&b, &two, 32, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap(),
        b"only-b"
    );
    assert_eq!(
        runtime
            .read(&c, &three, 32, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap(),
        b"only-c"
    );
    runtime.cancel_owner(&b).unwrap();
    assert!(three.is_active());
    close(&runtime, &c, &three);
    drained(&runtime);
    assert_eq!(
        runtime.require_provider(Provider::Tailscale),
        Err(Failure::ProviderUnavailable)
    );
    assert_eq!(
        runtime.require_provider(Provider::ZeroTier),
        Err(Failure::ProviderUnavailable)
    );
}

#[test]
fn pending_cancel_keeps_budget_and_closes_every_late_handle_once() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "pending", "pending-instance", "pending-network");
    let attempts: Vec<_> = (0..MAX_STREAMS)
        .map(|_| runtime.open(&owner, &profile, "late", 22, TIME).unwrap())
        .collect();
    until(|| metric(1) == MAX_STREAMS as i32);
    runtime.cancel_owner(&owner).unwrap();
    assert_eq!(runtime.reserved_streams(), MAX_STREAMS);
    let replacement = runtime.new_owner();
    assert!(matches!(
        runtime.open(&replacement, &profile, "echo", 22, TIME),
        Err(Failure::Capacity)
    ));
    for attempt in attempts {
        assert!(matches!(attempt.wait(TIME), Err(Failure::Cancelled)));
    }
    assert_eq!(runtime.reserved_streams(), MAX_STREAMS);
    control(1);
    drained(&runtime);
    assert_eq!(metric(4), MAX_STREAMS as i32);
    let replacement_lease = open(&runtime, &replacement, &profile, "echo");
    close(&runtime, &replacement, &replacement_lease);
    drained(&runtime);
}

#[test]
fn cancel_during_native_write_is_unknown_and_budget_waits_for_foreign_return() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "writer", "write-instance", "write-network");
    let lease = open(&runtime, &owner, &profile, "slow-write");
    let writer = runtime
        .write(&owner, &lease, b"one-attempt".to_vec(), TIME)
        .unwrap();
    until(|| metric(2) == 1 && metric(5) == 1);
    close(&runtime, &owner, &lease);
    until(|| metric(4) == 1);
    assert_eq!(runtime.reserved_streams(), 1);
    assert_eq!(writer.wait(TIME), Err(Failure::UnknownWrite));
    assert!(matches!(
        runtime.write(&owner, &lease, b"no-replay".to_vec(), TIME),
        Err(Failure::WrongOwner)
    ));
    control(2);
    drained(&runtime);
    assert_eq!(metric(2), 1);
}

#[test]
fn short_write_reports_only_prefix_and_unknown_after_progress_never_retries() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "short", "short-instance", "short-network");
    let short = open(&runtime, &owner, &profile, "short");
    runtime
        .read(&owner, &short, 128, TIME)
        .unwrap()
        .wait(TIME)
        .unwrap();
    assert_eq!(
        runtime
            .write(&owner, &short, b"abcdef".to_vec(), TIME)
            .unwrap()
            .wait(TIME),
        Ok(2)
    );
    assert_eq!(metric(2), 1);
    assert_eq!(metric(6), 2);
    assert_eq!(
        runtime
            .read(&owner, &short, 32, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap(),
        b"ab"
    );
    close(&runtime, &owner, &short);
    drained(&runtime);
    let unknown = open(&runtime, &owner, &profile, "unknown");
    assert_eq!(
        runtime
            .write(&owner, &unknown, b"xyz".to_vec(), TIME)
            .unwrap()
            .wait(TIME),
        Err(Failure::UnknownWrite)
    );
    drained(&runtime);
    assert_eq!(metric(2), 2);
    assert_eq!(metric(6), 3);
    assert!(matches!(
        runtime.write(&owner, &unknown, b"xyz".to_vec(), TIME),
        Err(Failure::WrongOwner)
    ));
}

#[test]
fn read_cancellation_and_unconsumed_open_close_only_their_owned_streams() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "drop", "drop-instance", "drop-network");
    let lease = open(&runtime, &owner, &profile, "read-block");
    let reader = runtime.read(&owner, &lease, 10, TIME).unwrap();
    until(|| metric(5) == 1);
    reader.cancel();
    assert_eq!(reader.wait(TIME), Err(Failure::Cancelled));
    drained(&runtime);
    let attempt = runtime.open(&owner, &profile, "late", 22, TIME).unwrap();
    until(|| metric(1) == 2);
    drop(attempt);
    assert_eq!(runtime.reserved_streams(), 1);
    control(1);
    drained(&runtime);
    assert_eq!(metric(4), 2);
}

#[test]
fn rejection_invalid_routes_limits_and_inflight_io_do_not_become_success() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "reject", "reject-instance", "reject-network");
    assert!(matches!(
        runtime
            .open(&owner, &profile, "reject", 22, TIME)
            .unwrap()
            .wait(TIME),
        Err(Failure::NativeRejected(-3))
    ));
    assert_eq!(runtime.reserved_streams(), 0);
    for host in ["https://host", "::1", "host\0name", "a b"] {
        assert!(matches!(
            runtime.open(&owner, &profile, host, 22, TIME),
            Err(Failure::InvalidRoute)
        ));
    }
    assert!(matches!(
        runtime.open(&owner, &profile, "host", 22, Duration::ZERO),
        Err(Failure::InvalidDeadline)
    ));
    assert!(matches!(
        runtime.open(&owner, &key(Provider::ZeroTier, "absent"), "host", 22, TIME),
        Err(Failure::ProfileMissing)
    ));
    let lease = open(&runtime, &owner, &profile, "read-block");
    assert!(matches!(
        runtime.read(&owner, &lease, MAX_IO + 1, TIME),
        Err(Failure::InvalidRoute)
    ));
    let reader = runtime.read(&owner, &lease, 1, TIME).unwrap();
    until(|| metric(5) == 1);
    assert!(matches!(
        runtime.read(&owner, &lease, 1, TIME),
        Err(Failure::Busy)
    ));
    close(&runtime, &owner, &lease);
    assert_eq!(reader.wait(TIME), Err(Failure::Cancelled));
    drained(&runtime);
}

#[test]
fn failed_close_retains_budget_and_explicit_retry_does_not_touch_another_profile() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "close", "close-instance", "close-network");
    let lease = open(&runtime, &owner, &profile, "close-fail");
    close(&runtime, &owner, &lease);
    until(|| metric(3) == 1);
    assert_eq!(runtime.reserved_streams(), 1);
    assert_eq!(metric(0), 1);
    until(|| {
        close(&runtime, &owner, &lease);
        metric(4) == 1
    });
    drained(&runtime);
    assert_eq!(metric(3), 2);
}

struct WakeCounter(AtomicUsize);
impl Wake for WakeCounter {
    fn wake(self: Arc<Self>) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn future_cancellation_wakes_without_waiting_for_late_native_open() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "future", "future-instance", "future-network");
    let mut operation = runtime.open(&owner, &profile, "late", 22, TIME).unwrap();
    until(|| metric(1) == 1);
    let counter = Arc::new(WakeCounter(AtomicUsize::new(0)));
    let waker = Waker::from(counter.clone());
    let mut context = Context::from_waker(&waker);
    assert!(Pin::new(&mut operation).poll(&mut context).is_pending());
    runtime.cancel_owner(&owner).unwrap();
    assert!(counter.0.load(Ordering::SeqCst) > 0);
    assert!(matches!(
        Pin::new(&mut operation).poll(&mut context),
        Poll::Ready(Err(Failure::Cancelled))
    ));
    assert_eq!(runtime.reserved_streams(), 1);
    control(1);
    drained(&runtime);
}

#[test]
fn dropping_ready_unclaimed_open_and_runtime_during_open_own_their_cleanup() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "drop-ready", "ready-instance", "ready-network");
    let operation = runtime.open(&owner, &profile, "echo", 22, TIME).unwrap();
    until(|| metric(0) == 1);
    drop(operation);
    drained(&runtime);
    let mut pending = runtime.open(&owner, &profile, "late", 22, TIME).unwrap();
    until(|| metric(1) == 2);
    let registry = runtime.inner.clone();
    drop(runtime);
    assert!(matches!(
        pending.try_result(),
        Some(Err(Failure::Cancelled))
    ));
    assert_eq!(lock(&registry.registry).entries.len(), 1);
    control(1);
    until(|| lock(&registry.registry).entries.is_empty() && metric(0) == 0);
    assert_eq!(metric(4), 2);
}

#[test]
fn profile_replacement_waits_for_old_cleanup_and_old_lease_never_routes_to_it() {
    let _serial = isolated();
    let runtime = OverlayRuntime::new();
    let owner = runtime.new_owner();
    let profile = easy(&runtime, "replace", "old-instance", "old-network");
    let old = open(&runtime, &owner, &profile, "close-fail");
    runtime.detach_profile(&profile).unwrap();
    until(|| metric(3) == 1);
    let replacement = || Arc::new(EasyTierBackend::linked("new-instance", "new-network").unwrap());
    assert_eq!(
        runtime.attach_profile(profile.clone(), replacement()),
        Err(Failure::Busy)
    );
    until(|| {
        close(&runtime, &owner, &old);
        metric(4) == 1
    });
    drained(&runtime);
    runtime
        .attach_profile(profile.clone(), replacement())
        .unwrap();
    let current = open(&runtime, &owner, &profile, "echo");
    assert!(matches!(
        runtime.write(&owner, &old, b"do-not-forward".to_vec(), TIME),
        Err(Failure::WrongOwner)
    ));
    assert_eq!(
        runtime
            .read(&owner, &current, 128, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap(),
        b"new-instance|new-network"
    );
    assert_eq!(metric(2), 0);
    close(&runtime, &owner, &current);
    drained(&runtime);
}
