use super::*;
#[cfg(any(feature = "tailscale-fixture", not(feature = "linked-tailscale")))]
use crate::ProfileKey;
use crate::nodes::NodeSpec;
use std::collections::HashMap;
use std::sync::{
    Mutex,
    atomic::{AtomicUsize, Ordering},
};

#[derive(Default)]
struct MemoryStore {
    bytes: Mutex<HashMap<Vec<u8>, Vec<u8>>>,
    reads: AtomicUsize,
    writes: AtomicUsize,
}
impl NativeStateStore for MemoryStore {
    fn read(&self, key: &[u8]) -> StateStoreResult<Vec<u8>> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        crate::lock(&self.bytes)
            .get(key)
            .cloned()
            .ok_or(StateStoreError::Missing)
    }
    fn write(&self, key: &[u8], value: Option<&[u8]>) -> StateStoreResult<()> {
        self.writes.fetch_add(1, Ordering::SeqCst);
        let mut bytes = crate::lock(&self.bytes);
        if let Some(value) = value {
            bytes.insert(key.to_vec(), value.to_vec());
        } else {
            bytes.remove(key);
        }
        Ok(())
    }
}
#[cfg(any(feature = "tailscale-fixture", not(feature = "linked-tailscale")))]
fn spec(id: &str) -> NodeSpec {
    NodeSpec {
        profile: ProfileKey {
            provider: Provider::Tailscale,
            id: id.into(),
        },
        revision: 1,
        profile_revision: 3,
        network: "synthetic-tailnet".into(),
        identity_ref: "native-vault-reference".into(),
    }
}
#[cfg(feature = "tailscale-fixture")]
struct Source {
    store: Arc<MemoryStore>,
    hostname: &'static str,
}
#[cfg(feature = "tailscale-fixture")]
impl NativeStateSource for Source {
    fn load(&self, spec: &NodeSpec) -> Result<NativeNodeConfig> {
        NativeNodeConfig::for_spec(
            spec,
            NativeVettedDirectory::from_native_vetted(PathBuf::from(
                "/native-vetted/synthetic-no-files",
            ))?,
            self.hostname.into(),
            "https://controlplane.tailscale.com".into(),
            self.store.clone(),
        )
    }
}
#[test]
fn public_config_refuses_unreviewed_urls_and_relative_directory_without_store_reads() {
    let store = Arc::new(MemoryStore::default());
    for value in [
        "http://control.invalid",
        "https://user:password@control.invalid",
        "https://control.invalid/#fragment",
        "https://control.invalid\\evil",
        "https://control.invalid:0",
        "https://control.invalid:65536",
        "https://%63ontrol.invalid",
    ] {
        assert!(!reviewed_https(value));
    }
    assert!(reviewed_https("https://control.invalid:443/login?a=1&b=2"));
    assert!(NativeVettedDirectory::from_native_vetted(PathBuf::from("relative")).is_err());
    assert!(NativeVettedDirectory::from_native_vetted(PathBuf::from("/native/../escape")).is_err());
    assert_eq!(store.reads.load(Ordering::SeqCst), 0);
}
#[cfg(not(feature = "linked-tailscale"))]
#[test]
fn absent_bridge_does_not_load_native_custody() {
    struct MustNotLoad;
    impl NativeStateSource for MustNotLoad {
        fn load(&self, _: &NodeSpec) -> Result<NativeNodeConfig> {
            panic!("must refuse before identity access")
        }
    }
    let runtime = crate::OverlayRuntime::new();
    assert!(matches!(
        runtime.start_tailscale_profile(
            spec("absent"),
            Some(Arc::new(MustNotLoad)),
            Duration::from_secs(1)
        ),
        Err(Failure::ProviderUnavailable)
    ));
    assert_eq!(runtime.reserved_nodes(), 0);
}
#[cfg(feature = "tailscale-fixture")]
mod native {
    use super::*;
    use crate::{OverlayRuntime, lock};
    use std::{thread, time::Instant};
    static SERIAL: Mutex<()> = Mutex::new(());
    const TIME: Duration = Duration::from_secs(2);
    unsafe extern "C" {
        fn hp_ts_fixture_reset();
        fn hp_ts_fixture_control(op: i32);
        fn hp_ts_fixture_metric(index: i32) -> i32;
        fn hp_ts_fixture_all_running();
    }
    fn metric(index: i32) -> i32 {
        unsafe { hp_ts_fixture_metric(index) }
    }
    fn until(test: impl Fn() -> bool) {
        let until = Instant::now() + Duration::from_secs(5);
        while !test() {
            assert!(Instant::now() < until, "synthetic native phase timed out");
            thread::sleep(Duration::from_millis(2));
        }
    }
    fn isolated() -> std::sync::MutexGuard<'static, ()> {
        let guard = lock(&SERIAL);
        until(|| metric(2) == 0);
        unsafe { hp_ts_fixture_reset() };
        guard
    }
    fn start(
        runtime: &OverlayRuntime,
        id: &str,
        hostname: &'static str,
        store: Arc<MemoryStore>,
    ) -> crate::nodes::NodeLease {
        runtime
            .start_tailscale_profile(spec(id), Some(Arc::new(Source { store, hostname })), TIME)
            .unwrap()
            .wait(TIME)
            .unwrap()
    }
    #[test]
    fn callbacks_preserve_binary_keys_missing_empty_delete_and_login_is_explicit() {
        let _serial = isolated();
        let runtime = OverlayRuntime::new();
        let store = Arc::new(MemoryStore::default());
        let node = start(&runtime, "state", "fixture", store.clone());
        assert!(store.reads.load(Ordering::SeqCst) >= 4);
        assert_eq!(store.writes.load(Ordering::SeqCst), 4);
        assert!(lock(&store.bytes).is_empty());
        assert_eq!(
            runtime.node_status(&node).unwrap().wait(TIME).unwrap(),
            NodeStatus::NeedsLogin
        );
        assert_eq!(metric(5), 0);
        let owner = runtime.new_owner();
        assert!(matches!(
            runtime
                .open_node(&owner, &node, "peer.fixture.invalid", 22, TIME)
                .unwrap()
                .wait(TIME),
            Err(Failure::NativeRejected(7))
        ));
        let login = runtime
            .begin_node_login(&node, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        assert_eq!(login.state, NodeStatus::NeedsMachineAuth);
        assert_eq!(
            login.auth_url.as_ref().unwrap().as_str(),
            "https://login.fixture.invalid/a/token?x=1"
        );
        assert!(!format!("{login:?}").contains("token"));
        unsafe { hp_ts_fixture_all_running() };
        assert_eq!(
            runtime.node_status(&node).unwrap().wait(TIME).unwrap(),
            NodeStatus::Running
        );
        let stream = runtime
            .open_node(&owner, &node, "peer.fixture.invalid", 22, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        assert_eq!(stream.profile().provider, Provider::Tailscale);
        assert_eq!(stream.profile_revision(), 1);
        assert_eq!(
            runtime.read(&owner, &stream, 16, TIME).unwrap().wait(TIME),
            Err(Failure::ReadTimedOut)
        );
        assert_eq!(
            runtime
                .write(&owner, &stream, b"once".to_vec(), TIME)
                .unwrap()
                .wait(TIME)
                .unwrap(),
            4
        );
        assert_eq!(
            runtime
                .read(&owner, &stream, 16, TIME)
                .unwrap()
                .wait(TIME)
                .unwrap(),
            b"once"
        );
        runtime
            .shutdown_write(&owner, &stream, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        assert!(
            runtime
                .read(&owner, &stream, 16, TIME)
                .unwrap()
                .wait(TIME)
                .unwrap()
                .is_empty()
        );
        runtime.stop_node(&node, TIME).unwrap().wait(TIME).unwrap();
        until(|| runtime.reserved_streams() == 0);
        assert_eq!(runtime.reserved_nodes(), 0);
        assert_eq!(metric(7), 1);
    }
    #[test]
    fn cancelled_late_start_keeps_store_and_node_budget_until_original_ffi_and_release() {
        let _serial = isolated();
        unsafe { hp_ts_fixture_control(1) };
        let runtime = OverlayRuntime::new();
        let store = Arc::new(MemoryStore::default());
        let weak = Arc::downgrade(&store);
        let operation = runtime
            .start_tailscale_profile(
                spec("late"),
                Some(Arc::new(Source {
                    store: store.clone(),
                    hostname: "late-start",
                })),
                TIME,
            )
            .unwrap();
        drop(store);
        until(|| metric(3) == 1);
        operation.cancel();
        assert!(matches!(operation.wait(TIME), Err(Failure::Cancelled)));
        assert_eq!(runtime.reserved_nodes(), 1);
        assert!(weak.upgrade().is_some());
        assert_eq!(metric(1), 0);
        unsafe { hp_ts_fixture_control(2) };
        until(|| runtime.reserved_nodes() == 0 && metric(2) == 0);
        until(|| weak.upgrade().is_none());
        assert_eq!(metric(3), 1);
        assert_eq!(metric(1), 1);
    }
    #[test]
    fn failed_stop_retains_native_store_until_explicit_original_lease_cleanup() {
        let _serial = isolated();
        let runtime = OverlayRuntime::new();
        let store = Arc::new(MemoryStore::default());
        let weak = Arc::downgrade(&store);
        let node = start(&runtime, "cleanup", "stop-fail", store.clone());
        drop(store);
        assert!(matches!(
            runtime.stop_node(&node, TIME).unwrap().wait(TIME),
            Err(Failure::ClosePending)
        ));
        assert_eq!(runtime.reserved_nodes(), 1);
        assert!(weak.upgrade().is_some());
        assert_eq!(metric(1), 0);
        unsafe { hp_ts_fixture_control(3) };
        runtime.stop_node(&node, TIME).unwrap().wait(TIME).unwrap();
        until(|| weak.upgrade().is_none());
        assert_eq!(runtime.reserved_nodes(), 0);
    }
    #[test]
    fn unavailable_or_oversized_store_never_becomes_a_missing_identity() {
        let _serial = isolated();
        struct BadStore {
            oversized: bool,
            reads: AtomicUsize,
        }
        impl NativeStateStore for BadStore {
            fn read(&self, _: &[u8]) -> StateStoreResult<Vec<u8>> {
                self.reads.fetch_add(1, Ordering::SeqCst);
                if self.oversized {
                    Ok(vec![0; MAX_STATE_VALUE + 1])
                } else {
                    Err(StateStoreError::Unavailable)
                }
            }
            fn write(&self, _: &[u8], _: Option<&[u8]>) -> StateStoreResult<()> {
                panic!("bad reads cannot initialize state")
            }
        }
        struct BadSource(Arc<BadStore>);
        impl NativeStateSource for BadSource {
            fn load(&self, spec: &NodeSpec) -> Result<NativeNodeConfig> {
                NativeNodeConfig::for_spec(
                    spec,
                    NativeVettedDirectory::from_native_vetted(PathBuf::from(
                        "/native-vetted/synthetic-no-files",
                    ))?,
                    "fixture".into(),
                    "https://control.invalid".into(),
                    self.0.clone(),
                )
            }
        }
        for oversized in [false, true] {
            let runtime = OverlayRuntime::new();
            let store = Arc::new(BadStore {
                oversized,
                reads: AtomicUsize::new(0),
            });
            let result = runtime
                .start_tailscale_profile(
                    spec("unavailable"),
                    Some(Arc::new(BadSource(store.clone()))),
                    TIME,
                )
                .unwrap()
                .wait(TIME);
            assert!(matches!(result, Err(Failure::NativeRejected(8))));
            until(|| runtime.reserved_nodes() == 0);
            assert_eq!(store.reads.load(Ordering::SeqCst), 1);
        }
    }
    #[test]
    fn source_cannot_rebind_native_store_to_another_spec() {
        let _serial = isolated();
        struct WrongSource(Arc<MemoryStore>);
        impl NativeStateSource for WrongSource {
            fn load(&self, expected: &NodeSpec) -> Result<NativeNodeConfig> {
                let mut wrong = expected.clone();
                wrong.identity_ref = "different-native-store".into();
                NativeNodeConfig::for_spec(
                    &wrong,
                    NativeVettedDirectory::from_native_vetted(PathBuf::from(
                        "/native-vetted/synthetic-no-files",
                    ))?,
                    "fixture".into(),
                    "https://control.invalid".into(),
                    self.0.clone(),
                )
            }
        }
        let runtime = OverlayRuntime::new();
        let store = Arc::new(MemoryStore::default());
        let result = runtime
            .start_tailscale_profile(
                spec("wrong-spec"),
                Some(Arc::new(WrongSource(store.clone()))),
                TIME,
            )
            .unwrap()
            .wait(TIME);
        assert!(matches!(result, Err(Failure::InvalidRoute)));
        until(|| runtime.reserved_nodes() == 0);
        assert_eq!(metric(0), 0);
        assert_eq!(store.reads.load(Ordering::SeqCst), 0);
    }
    #[cfg(feature = "native-fixture")]
    #[test]
    fn tailscale_and_easytier_share_lifecycle_without_crossing_same_address_streams() {
        let _serial = isolated();
        let _easy = crate::tests::isolated();
        struct EasySource;
        impl crate::nodes::SecureConfigSource for EasySource {
            fn load(&self, spec: &NodeSpec) -> Result<crate::nodes::SecretConfig> {
                crate::nodes::SecretConfig::from_bytes(spec.network.clone().into_bytes())
            }
        }
        let runtime = OverlayRuntime::new();
        let tail = start(
            &runtime,
            "parallel",
            "fixture",
            Arc::new(MemoryStore::default()),
        );
        let mut easy_spec = spec("parallel");
        easy_spec.profile.provider = Provider::EasyTier;
        let easy = runtime
            .start_easytier_profile(easy_spec, Some(Arc::new(EasySource)), TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        unsafe { hp_ts_fixture_all_running() };
        let owner_a = runtime.new_owner();
        let owner_b = runtime.new_owner();
        let a = runtime
            .open_node(&owner_a, &tail, "echo", 22, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        let b = runtime
            .open_node(&owner_b, &easy, "echo", 22, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        assert_eq!(a.profile().provider, Provider::Tailscale);
        assert_eq!(b.profile().provider, Provider::EasyTier);
        runtime
            .write(&owner_a, &a, b"tailscale".to_vec(), TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        runtime
            .write(&owner_b, &b, b"easytier".to_vec(), TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        assert_eq!(
            runtime
                .read(&owner_a, &a, 32, TIME)
                .unwrap()
                .wait(TIME)
                .unwrap(),
            b"tailscale"
        );
        let easy_bytes = runtime
            .read(&owner_b, &b, MAX_IO, TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        // The independent EasyTier fixture prepends its managed instance and
        // selector. Tailscale's fixture has its own plain echo buffer.
        assert!(easy_bytes.starts_with(b"managed-"));
        assert!(easy_bytes.ends_with(b"easytier"));
        assert_ne!(easy_bytes, b"tailscale");
        runtime.stop_node(&tail, TIME).unwrap().wait(TIME).unwrap();
        assert!(b.is_active());
        runtime
            .write(&owner_b, &b, b"still-easy".to_vec(), TIME)
            .unwrap()
            .wait(TIME)
            .unwrap();
        runtime.stop_node(&easy, TIME).unwrap().wait(TIME).unwrap();
        assert_eq!(runtime.reserved_nodes(), 0);
    }
    #[test]
    fn malformed_status_and_unsafe_auth_urls_are_rejected_without_log_fallback() {
        let _serial = isolated();
        for wire in [
            b"{\"state\":\"Running\",\"state\":\"Running\"}".as_slice(),
            b"{\"state\":\"Invented\",\"auth_url\":\"\"}",
            b"{\"state\":\"Running\",\"auth_url\":\"\",\"extra\":\"x\"}",
        ] {
            assert!(linked::parse_status(wire).is_err());
        }
        let (state, url) = linked::parse_status(
            b"{\"auth_url\":\"https://control.invalid/a?x=1\\u0026b=2\",\"state\":\"NeedsLogin\"}",
        )
        .unwrap();
        assert_eq!(state, NodeStatus::NeedsLogin);
        assert_eq!(url, "https://control.invalid/a?x=1&b=2");
    }
}
