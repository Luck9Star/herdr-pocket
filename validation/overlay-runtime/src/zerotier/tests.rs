use super::*;
use crate::{OverlayRuntime, ProfileKey};
use std::sync::atomic::{AtomicUsize, Ordering};

fn spec(profile: &str, network: &str) -> NodeSpec {
    NodeSpec {
        profile: ProfileKey {
            provider: Provider::ZeroTier,
            id: profile.into(),
        },
        revision: 1,
        profile_revision: 1,
        network: network.into(),
        identity_ref: "device-fixture".into(),
    }
}
const TIME: Duration = Duration::from_secs(2);
struct Absent(AtomicUsize);
impl NativeDeviceSource for Absent {
    fn acquire(&self, _: &NodeSpec, _: Duration) -> Result<NativeDeviceConfig> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(Failure::IdentityUnavailable)
    }
}
#[test]
fn rejects_invalid_network_metadata_before_custody() {
    for network in [
        "",
        "0",
        "0000000000000000",
        "0123456789ABCDEf",
        "12345678901234567",
        "../1111111111111",
    ] {
        assert_eq!(
            validate_spec(&spec("a", network)),
            Err(Failure::InvalidRoute)
        );
    }
    assert!(validate_spec(&spec("a", "0123456789abcdef")).is_ok());
}
#[cfg(not(feature = "linked-zerotier"))]
#[test]
fn unavailable_refuses_before_acquiring_device() {
    let source = Arc::new(Absent(AtomicUsize::new(0)));
    let runtime = OverlayRuntime::new();
    assert!(matches!(
        runtime.start_zerotier_profile(spec("a", "0000000000000001"), Some(source.clone()), TIME),
        Err(Failure::ProviderUnavailable)
    ));
    assert_eq!(source.0.load(Ordering::SeqCst), 0);
    assert_eq!(runtime.reserved_nodes(), 0);
}

#[cfg(feature = "zerotier-fixture")]
mod fixture {
    use super::*;
    use crate::lock;
    use std::sync::{Condvar, Mutex};
    use std::time::Instant;
    unsafe extern "C" {
        fn hp_zt_fixture_reset();
        fn hp_zt_fixture_control(op: i32);
        fn hp_zt_fixture_state(phase: u32, online: u32);
        fn hp_zt_fixture_metric(i: i32) -> i32;
    }
    static SERIAL: Mutex<()> = Mutex::new(());
    fn reset() {
        unsafe { hp_zt_fixture_reset() };
    }
    fn metric(i: i32) -> i32 {
        unsafe { hp_zt_fixture_metric(i) }
    }
    fn control(op: i32) {
        unsafe { hp_zt_fixture_control(op) };
    }
    fn until(mut condition: impl FnMut() -> bool) {
        let end = Instant::now() + TIME;
        while !condition() {
            assert!(Instant::now() < end, "fixture did not converge");
            std::thread::yield_now();
        }
    }
    #[derive(Default)]
    struct Pool {
        reservations: AtomicUsize,
        retires: AtomicUsize,
        fail_retire: AtomicBool,
    }
    struct Session {
        pool: Arc<Pool>,
        retired: AtomicBool,
    }
    impl NativeDeviceSession for Session {
        fn identity_ref(&self) -> &str {
            "device-fixture"
        }
        fn owner(&self) -> u64 {
            41
        }
        fn retire_after_network(&self, _: Duration) -> Result<()> {
            if self.pool.fail_retire.load(Ordering::SeqCst) {
                return Err(Failure::ClosePending);
            }
            if !self.retired.swap(true, Ordering::SeqCst) {
                self.pool.reservations.fetch_sub(1, Ordering::SeqCst);
                self.pool.retires.fetch_add(1, Ordering::SeqCst);
            }
            Ok(())
        }
    }
    struct Source {
        pool: Arc<Pool>,
        gate: Option<Arc<(Mutex<bool>, Condvar)>>,
        entered: AtomicBool,
        failure: Option<Failure>,
    }
    impl Source {
        fn new(pool: &Arc<Pool>) -> Arc<Self> {
            Arc::new(Self {
                pool: pool.clone(),
                gate: None,
                entered: AtomicBool::new(false),
                failure: None,
            })
        }
    }
    impl NativeDeviceSource for Source {
        fn acquire(&self, spec: &NodeSpec, _: Duration) -> Result<NativeDeviceConfig> {
            self.pool.reservations.fetch_add(1, Ordering::SeqCst);
            self.entered.store(true, Ordering::SeqCst);
            if let Some(gate) = &self.gate {
                let mut open = lock(&gate.0);
                while !*open {
                    open = gate.1.wait(open).unwrap();
                }
            }
            NativeDeviceConfig::for_spec(
                spec,
                Arc::new(Session {
                    pool: self.pool.clone(),
                    retired: AtomicBool::new(false),
                }),
                self.failure,
            )
        }
    }
    fn backend(profile: &str, network: &str, pool: &Arc<Pool>) -> ZeroTierBackend {
        let backend = ZeroTierBackend::managed(&spec(profile, network)).unwrap();
        backend
            .start_node(Source::new(pool), TIME, &AtomicBool::new(false))
            .unwrap();
        backend
    }
    #[test]
    fn shared_device_networks_isolate_routes_and_retire_independently() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let a = backend("a", "0000000000000001", &pool);
        let b = backend("b", "0000000000000002", &pool);
        let sa = a.open("10.1.1.1", 22, TIME).unwrap();
        let sb = b.open("fd00::2", 22, TIME).unwrap();
        assert_eq!(metric(7), 1);
        assert_eq!(
            a.open("10.1.1.2", 22, TIME),
            Err(Failure::NativeRejected(13))
        );
        assert_eq!(
            a.open("example.invalid", 22, TIME),
            Err(Failure::InvalidRoute)
        );
        assert_eq!(a.read(sb, 5, TIME), Err(Failure::WrongOwner));
        assert_eq!(a.write(sa, b"only-a", TIME), Ok(6));
        assert_eq!(b.read(sb, 10, TIME), Err(Failure::ReadTimedOut));
        a.stop_node(TIME).unwrap();
        assert_eq!(metric(0), 1);
        assert_eq!(metric(1), 1);
        assert_eq!(pool.reservations.load(Ordering::SeqCst), 1);
        assert_eq!(b.write(sb, b"live-b", TIME), Ok(6));
        assert_eq!(b.read(sb, 10, TIME).unwrap(), b"live-b");
        b.shutdown_write(sb, TIME).unwrap();
        assert!(b.read(sb, 10, TIME).unwrap().is_empty());
        b.stop_node(TIME).unwrap();
        assert_eq!(pool.reservations.load(Ordering::SeqCst), 0);
        assert_eq!(metric(1), 0);
    }
    #[test]
    fn configured_does_not_imply_online_or_reachability() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let b = backend("a", "0000000000000001", &pool);
        for (phase, expected) in [
            (1, NetworkPhase::Requesting),
            (2, NetworkPhase::Configured),
            (3, NetworkPhase::Denied),
            (4, NetworkPhase::NotFound),
            (5, NetworkPhase::PortError),
            (6, NetworkPhase::ClientOld),
            (7, NetworkPhase::AuthRequired),
            (9, NetworkPhase::Unknown),
        ] {
            unsafe { hp_zt_fixture_state(phase, 0) };
            assert_eq!(
                b.node_status(),
                Ok(NodeStatus::ZeroTier {
                    phase: expected,
                    online: false
                })
            );
        }
        assert_eq!(
            b.open("10.0.0.1", 22, TIME),
            Err(Failure::NativeRejected(13))
        );
        assert_eq!(metric(1), 0);
        b.stop_node(TIME).unwrap();
    }
    #[test]
    fn unknown_write_is_once_and_failed_close_keeps_device_custody() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let b = backend("a", "0000000000000001", &pool);
        let stream = b.open("10.0.0.1", 22, TIME).unwrap();
        control(5);
        assert_eq!(b.write(stream, b"once", TIME), Err(Failure::UnknownWrite));
        assert_eq!(metric(5), 1);
        control(1);
        assert_eq!(b.close(stream), Err(Failure::ClosePending));
        assert_eq!(b.stop_node(TIME), Err(Failure::ClosePending));
        assert_eq!(metric(0), 1);
        assert_eq!(metric(1), 1);
        assert_eq!(pool.retires.load(Ordering::SeqCst), 0);
        control(2);
        b.stop_node(TIME).unwrap();
        assert_eq!(pool.retires.load(Ordering::SeqCst), 1);
        assert_eq!(metric(1), 0);
    }
    #[test]
    fn failed_open_cleanup_is_bounded_and_retried_by_original_backend() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let b = backend("a", "0000000000000001", &pool);
        unsafe { hp_zt_fixture_state(3, 1) };
        control(1);
        for _ in 0..32 {
            assert_eq!(
                b.open("10.0.0.1", 22, TIME),
                Err(Failure::NativeRejected(13))
            );
        }
        assert_eq!(metric(1), 32);
        assert_eq!(b.open("10.0.0.1", 22, TIME), Err(Failure::Capacity));
        control(2);
        b.stop_node(TIME).unwrap();
        assert_eq!(metric(1), 0);
        assert_eq!(metric(0), 0);
    }
    #[test]
    fn failed_leave_and_vault_retirement_keep_original_reservation() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let b = backend("a", "0000000000000001", &pool);
        control(9);
        assert_eq!(b.stop_node(TIME), Err(Failure::WaitTimeout));
        assert_eq!(pool.retires.load(Ordering::SeqCst), 0);
        control(10);
        pool.fail_retire.store(true, Ordering::SeqCst);
        assert_eq!(b.stop_node(TIME), Err(Failure::ClosePending));
        assert_eq!(metric(0), 0);
        assert_eq!(pool.reservations.load(Ordering::SeqCst), 1);
        pool.fail_retire.store(false, Ordering::SeqCst);
        b.stop_node(TIME).unwrap();
        assert_eq!(pool.retires.load(Ordering::SeqCst), 1);
    }
    #[test]
    fn cancellation_during_acquire_retains_late_owner_without_join() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let gate = Arc::new((Mutex::new(false), Condvar::new()));
        let source = Arc::new(Source {
            pool: pool.clone(),
            gate: Some(gate.clone()),
            entered: AtomicBool::new(false),
            failure: None,
        });
        let runtime = OverlayRuntime::new();
        let operation = runtime
            .start_zerotier_profile(spec("a", "0000000000000001"), Some(source.clone()), TIME)
            .unwrap();
        until(|| source.entered.load(Ordering::SeqCst));
        operation.cancel();
        assert!(matches!(operation.wait(TIME), Err(Failure::Cancelled)));
        assert_eq!(pool.reservations.load(Ordering::SeqCst), 1);
        assert_eq!(runtime.reserved_nodes(), 1);
        *lock(&gate.0) = true;
        gate.1.notify_all();
        until(|| runtime.reserved_nodes() == 0);
        assert_eq!(metric(2), 0);
        assert_eq!(pool.retires.load(Ordering::SeqCst), 1);
    }
    #[test]
    fn expired_acquisition_cannot_start_a_new_join_with_a_fresh_budget() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let gate = Arc::new((Mutex::new(false), Condvar::new()));
        let source = Arc::new(Source {
            pool: pool.clone(),
            gate: Some(gate.clone()),
            entered: AtomicBool::new(false),
            failure: None,
        });
        let runtime = OverlayRuntime::new();
        let operation = runtime
            .start_zerotier_profile(
                spec("a", "0000000000000001"),
                Some(source.clone()),
                Duration::from_millis(10),
            )
            .unwrap();
        until(|| source.entered.load(Ordering::SeqCst));
        std::thread::sleep(Duration::from_millis(20));
        *lock(&gate.0) = true;
        gate.1.notify_all();
        assert!(matches!(operation.wait(TIME), Err(Failure::WaitTimeout)));
        until(|| runtime.reserved_nodes() == 0);
        assert_eq!(metric(2), 0);
        assert_eq!(pool.retires.load(Ordering::SeqCst), 1);
    }
    #[test]
    fn startup_failure_carrying_owner_and_late_join_both_drain() {
        let _serial = lock(&SERIAL);
        reset();
        let pool = Arc::new(Pool::default());
        let runtime = OverlayRuntime::new();
        let source = Arc::new(Source {
            pool: pool.clone(),
            gate: None,
            entered: AtomicBool::new(false),
            failure: Some(Failure::NativeRejected(5)),
        });
        let op = runtime
            .start_zerotier_profile(spec("a", "0000000000000001"), Some(source), TIME)
            .unwrap();
        assert!(matches!(op.wait(TIME), Err(Failure::NativeRejected(5))));
        until(|| runtime.reserved_nodes() == 0);
        assert_eq!(pool.retires.load(Ordering::SeqCst), 1);
        control(7);
        let op = runtime
            .start_zerotier_profile(
                spec("b", "0000000000000002"),
                Some(Source::new(&pool)),
                TIME,
            )
            .unwrap();
        until(|| metric(8) == 1);
        op.cancel();
        assert_eq!(runtime.reserved_nodes(), 1);
        control(8);
        assert!(matches!(op.wait(TIME), Err(Failure::Cancelled)));
        until(|| runtime.reserved_nodes() == 0);
        assert_eq!(metric(0), 0);
        assert_eq!(pool.retires.load(Ordering::SeqCst), 2);
    }
    #[test]
    fn zero_native_source_failure_has_no_network_side_effect() {
        let _serial = lock(&SERIAL);
        reset();
        let runtime = OverlayRuntime::new();
        let source = Arc::new(Absent(AtomicUsize::new(0)));
        let op = runtime
            .start_zerotier_profile(spec("a", "0000000000000001"), Some(source.clone()), TIME)
            .unwrap();
        assert!(matches!(op.wait(TIME), Err(Failure::IdentityUnavailable)));
        until(|| runtime.reserved_nodes() == 0);
        assert_eq!(source.0.load(Ordering::SeqCst), 1);
        assert_eq!(metric(2), 0);
    }
}
