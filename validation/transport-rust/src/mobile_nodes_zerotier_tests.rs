use super::*;

fn zerotier_binding(profile_id: &str, network_id: &str) -> Binding {
    Binding::with_provider(
        BindingProvider::ZeroTier,
        profile_id.into(),
        1,
        network_id.into(),
        "shared-device-vault".into(),
    )
    .unwrap()
}

#[test]
fn zerotier_binding_requires_canonical_nonzero_network_id() {
    assert!(zerotier_binding("zt", "0123456789abcdef").provider() == &BindingProvider::ZeroTier);
    for network_id in [
        "",
        "0123456789abcde",
        "0123456789abcdef0",
        "0123456789ABCDEf",
        "0123456789abcdeg",
        "0000000000000000",
    ] {
        assert_eq!(
            Binding::with_provider(
                BindingProvider::ZeroTier,
                "zt".into(),
                1,
                network_id.into(),
                "shared-device-vault".into(),
            )
            .unwrap_err(),
            "mobile_node_invalid_binding",
            "accepted invalid ZeroTier network id {network_id:?}"
        );
    }
}

#[test]
fn zerotier_network_states_and_optional_device_online_serialize_without_changing_legacy_shape() {
    assert_eq!(
        serde_json::to_value(State::ZeroTierConfigured).unwrap(),
        serde_json::json!("zero-tier-configured")
    );
    let binding = zerotier_binding("zt", "0123456789abcdef");
    let zt = serde_json::to_value(Snapshot {
        binding: binding.clone(),
        state: State::ZeroTierConfigured,
        device_online: Some(false),
    })
    .unwrap();
    assert_eq!(zt["deviceOnline"], false);
    assert_eq!(zt["state"], "zero-tier-configured");
    let legacy = serde_json::to_value(Snapshot {
        binding,
        state: State::EngineStarted,
        device_online: None,
    })
    .unwrap();
    assert!(legacy.get("deviceOnline").is_none());
}

#[cfg(not(any(
    feature = "overlay-linked-zerotier",
    feature = "overlay-zerotier-fixture"
)))]
#[tokio::test]
async fn unlinked_zerotier_rejects_before_calling_native_device_source() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct MustNotAcquire(AtomicUsize);
    impl NativeDeviceSource for MustNotAcquire {
        fn acquire(
            &self,
            _: &NodeSpec,
            _: Duration,
        ) -> overlay_runtime::Result<NativeDeviceConfig> {
            self.0.fetch_add(1, Ordering::SeqCst);
            panic!("unlinked ZeroTier must reject before source acquisition")
        }
    }
    let source = Arc::new(MustNotAcquire(AtomicUsize::new(0)));
    let result = MobileNodeService::new()
        .start_zerotier(
            zerotier_binding("unlinked", "0123456789abcdef"),
            source.clone(),
            Duration::from_secs(2),
            Cancellation::default(),
        )
        .await;
    assert_eq!(result.unwrap_err(), "overlay_provider_unavailable");
    assert_eq!(source.0.load(Ordering::SeqCst), 0);
}

#[cfg(feature = "overlay-zerotier-fixture")]
mod fixture {
    use super::*;
    use std::sync::{
        Mutex,
        atomic::{AtomicUsize, Ordering},
    };

    const WAIT: Duration = Duration::from_secs(2);
    static SERIAL: Mutex<()> = Mutex::new(());

    unsafe extern "C" {
        fn hp_zt_fixture_reset();
        fn hp_zt_fixture_state(phase: u32, online: u32);
        fn hp_zt_fixture_metric(index: i32) -> i32;
    }

    struct FakeSession {
        identity_ref: String,
        owner: u64,
        retired: Arc<AtomicUsize>,
    }
    impl NativeDeviceSession for FakeSession {
        fn identity_ref(&self) -> &str {
            &self.identity_ref
        }
        fn owner(&self) -> u64 {
            self.owner
        }
        fn retire_after_network(&self, _: Duration) -> overlay_runtime::Result<()> {
            self.retired.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }
    struct FakeSource {
        owner: u64,
        retired: Arc<AtomicUsize>,
    }
    impl NativeDeviceSource for FakeSource {
        fn acquire(
            &self,
            spec: &NodeSpec,
            _: Duration,
        ) -> overlay_runtime::Result<NativeDeviceConfig> {
            NativeDeviceConfig::for_spec(
                spec,
                Arc::new(FakeSession {
                    identity_ref: spec.identity_ref.clone(),
                    owner: self.owner,
                    retired: self.retired.clone(),
                }),
                None,
            )
        }
    }

    fn metric(index: i32) -> i32 {
        unsafe { hp_zt_fixture_metric(index) }
    }

    #[tokio::test]
    async fn shared_owner_keeps_profile_leases_and_configured_online_route_gate_separate() {
        let _serial = SERIAL.lock().unwrap_or_else(|poison| poison.into_inner());
        unsafe { hp_zt_fixture_reset() };
        let retired = Arc::new(AtomicUsize::new(0));
        let service = MobileNodeService::new();
        let first = zerotier_binding("zt-first", "0000000000000001");
        let second = zerotier_binding("zt-second", "0000000000000002");

        let first_start = service
            .start_zerotier(
                first.clone(),
                Arc::new(FakeSource {
                    owner: 0x7171,
                    retired: retired.clone(),
                }),
                WAIT,
                Cancellation::default(),
            )
            .await
            .unwrap();
        let second_start = service
            .start_zerotier(
                second.clone(),
                Arc::new(FakeSource {
                    owner: 0x7171,
                    retired: retired.clone(),
                }),
                WAIT,
                Cancellation::default(),
            )
            .await
            .unwrap();
        assert_eq!(first_start.state, State::ZeroTierConfigured);
        assert_eq!(second_start.state, State::ZeroTierConfigured);
        assert_eq!(first_start.device_online, Some(true));
        assert_eq!(metric(0), 2);
        assert_eq!(metric(2), 2);
        assert!(service.dialer(&first, WAIT).is_ok());

        unsafe { hp_zt_fixture_state(2, 0) };
        let offline = service.status(&first).await.unwrap();
        assert_eq!(offline.state, State::ZeroTierConfigured);
        assert_eq!(offline.device_online, Some(false));
        assert!(matches!(
            service.dialer(&first, WAIT),
            Err("mobile_node_not_started")
        ));

        unsafe { hp_zt_fixture_state(1, 1) };
        let requesting = service.status(&first).await.unwrap();
        assert_eq!(requesting.state, State::ZeroTierRequesting);
        assert!(matches!(
            service.dialer(&first, WAIT),
            Err("mobile_node_not_started")
        ));

        unsafe { hp_zt_fixture_state(3, 1) };
        assert_eq!(
            service.status(&first).await.unwrap().state,
            State::ZeroTierDenied
        );
        assert!(matches!(
            service.dialer(&first, WAIT),
            Err("mobile_node_not_started")
        ));

        unsafe { hp_zt_fixture_state(2, 1) };
        assert_eq!(
            service.status(&first).await.unwrap().state,
            State::ZeroTierConfigured
        );
        assert!(service.dialer(&first, WAIT).is_ok());
        service.stop(&first, WAIT).await.unwrap();
        assert_eq!(
            metric(0),
            1,
            "stopping one profile must leave the other lease active"
        );
        assert_eq!(
            service.status(&second).await.unwrap().state,
            State::ZeroTierConfigured
        );
        service.stop(&second, WAIT).await.unwrap();
        assert_eq!(metric(0), 0);
        assert_eq!(metric(3), 2);
        assert_eq!(retired.load(Ordering::SeqCst), 2);

        for (phase, expected) in [
            (4, State::ZeroTierNotFound),
            (5, State::ZeroTierPortError),
            (6, State::ZeroTierClientOld),
            (7, State::ZeroTierAuthRequired),
            (9, State::ZeroTierUnknown),
        ] {
            unsafe { hp_zt_fixture_state(phase, 0) };
            let probe = zerotier_binding("phase-probe", "0000000000000003");
            let snapshot = service
                .start_zerotier(
                    probe.clone(),
                    Arc::new(FakeSource {
                        owner: 0x7171,
                        retired: retired.clone(),
                    }),
                    WAIT,
                    Cancellation::default(),
                )
                .await
                .unwrap();
            assert_eq!(snapshot.state, expected);
            assert_eq!(service.status(&probe).await.unwrap().state, expected);
            service.stop(&probe, WAIT).await.unwrap();
        }
        assert_eq!(metric(0), 0);
        assert_eq!(metric(1), 0);
        unsafe { hp_zt_fixture_reset() };
    }
}
