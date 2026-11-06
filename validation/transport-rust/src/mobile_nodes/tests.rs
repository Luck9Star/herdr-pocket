use super::*;

fn binding(id: &str) -> Binding {
    Binding::new(
        id.into(),
        7,
        "synthetic-network".into(),
        "synthetic-vault-A".into(),
    )
    .unwrap()
}

#[test]
fn binding_is_bounded_public_metadata_and_has_no_attempt() {
    let value = serde_json::to_value(binding("profile")).unwrap();
    assert_eq!(
        value,
        serde_json::json!({
            "profileId":"profile", "profileRevision":7,
            "networkName":"synthetic-network", "identityRef":"synthetic-vault-A"
        })
    );
    for (id, revision, network, identity) in [
        ("", 1, "network", "ref"),
        ("invalid/id", 1, "network", "ref"),
        ("profile", 0, "network", "ref"),
        ("profile", 1, "", "ref"),
        ("profile", 1, "network\n", "ref"),
        ("profile", 1, "network", "ref\0"),
    ] {
        assert_eq!(
            Binding::new(id.into(), revision, network.into(), identity.into()).unwrap_err(),
            "mobile_node_invalid_binding"
        );
    }
}

#[test]
fn explicit_tailscale_provider_round_trips_while_legacy_binding_keeps_easytier() {
    let legacy = serde_json::to_value(binding("legacy")).unwrap();
    assert!(legacy.get("provider").is_none());
    let parsed: Binding = serde_json::from_value(legacy).unwrap();
    assert_eq!(parsed.provider(), &BindingProvider::EasyTier);
    let saved = Binding::with_provider(
        BindingProvider::Tailscale,
        "tail".into(),
        7,
        "tailnet".into(),
        "native-ref".into(),
    )
    .unwrap();
    let wire = serde_json::to_value(&saved).unwrap();
    assert_eq!(wire["provider"], "tailscale");
    assert_eq!(serde_json::from_value::<Binding>(wire).unwrap(), saved);
    assert!(serde_json::from_value::<Binding>(serde_json::json!({"provider":"system","profileId":"x","profileRevision":1,"networkName":"x","identityRef":"x"})).is_err());
}

#[cfg(not(any(
    feature = "overlay-native-fixture",
    feature = "overlay-tailscale-fixture"
)))]
#[test]
fn default_gate_rejects_synthetic_without_either_explicit_fixture_feature() {
    assert_eq!(
        crate::overlay::require_overlay_evidence(overlay_runtime::Evidence::SyntheticNativeFixture),
        Err("overlay_fixture_disabled")
    );
    assert_eq!(
        crate::overlay::require_overlay_evidence(overlay_runtime::Evidence::CandidateAbiOnly),
        Ok(())
    );
}
#[cfg(feature = "overlay-tailscale-fixture")]
#[test]
fn explicitly_selected_tailscale_fixture_is_accepted_as_synthetic_only() {
    assert_eq!(
        crate::overlay::require_overlay_evidence(overlay_runtime::Evidence::SyntheticNativeFixture),
        Ok(())
    );
}

#[cfg(not(any(
    feature = "overlay-linked-easytier",
    feature = "overlay-native-fixture"
)))]
#[tokio::test]
async fn default_build_refuses_before_loading_source_and_never_uses_fixture_fallback() {
    struct MustNotLoad;
    impl SecureConfigSource for MustNotLoad {
        fn load(&self, _: &NodeSpec) -> overlay_runtime::Result<SecretConfig> {
            panic!("missing native bridge must reject before source access")
        }
    }
    let service = MobileNodeService::new();
    let saved = binding("missing-bridge");
    assert_eq!(
        service
            .start(
                saved.clone(),
                Arc::new(MustNotLoad),
                Duration::from_secs(1),
                Cancellation::default()
            )
            .await
            .unwrap_err(),
        "overlay_provider_unavailable"
    );
    assert_eq!(service.reserved_nodes(), 0);
    assert_eq!(service.status(&saved).await.unwrap().state, State::Stopped);
    assert_eq!(
        service.status_profile(saved.profile_id()).await.unwrap(),
        None
    );
}

#[cfg(feature = "overlay-native-fixture")]
mod native {
    use super::*;
    use crate::transport::{Dialer, OverlayRouteIdentity};
    use std::future::Future;
    use std::sync::{
        Condvar,
        atomic::{AtomicUsize, Ordering},
    };
    use std::task::Poll;
    const TIME: Duration = Duration::from_secs(2);
    unsafe extern "C" {
        fn fixture_reset();
        fn fixture_control(operation: i32);
        fn fixture_metric(metric: i32) -> i32;
    }
    fn metric(value: i32) -> i32 {
        unsafe { fixture_metric(value) }
    }
    async fn until(predicate: impl Fn() -> bool) {
        tokio::time::timeout(Duration::from_secs(5), async {
            while !predicate() {
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
        })
        .await
        .expect("synthetic lifecycle phase timed out");
    }
    async fn isolated() -> tokio::sync::MutexGuard<'static, ()> {
        let guard = NATIVE_FIXTURE_SERIAL.lock().await;
        until(|| metric(0) == 0 && metric(5) == 0 && metric(7) == 0).await;
        unsafe { fixture_reset() };
        guard
    }
    #[derive(Default)]
    struct Source {
        mode: &'static str,
        loaded: AtomicUsize,
        specs: Mutex<Vec<NodeSpec>>,
        blocked: bool,
        release: (Mutex<bool>, Condvar),
    }
    impl Source {
        fn release(&self) {
            *lock(&self.release.0) = true;
            self.release.1.notify_all();
        }
    }
    impl SecureConfigSource for Source {
        fn load(&self, spec: &NodeSpec) -> overlay_runtime::Result<SecretConfig> {
            self.loaded.fetch_add(1, Ordering::SeqCst);
            lock(&self.specs).push(spec.clone());
            if self.blocked {
                let mut released = lock(&self.release.0);
                while !*released {
                    released = self.release.1.wait(released).unwrap();
                }
            }
            SecretConfig::from_bytes(format!("{};{}", spec.network, self.mode).into_bytes())
        }
    }
    async fn start(service: &MobileNodeService, saved: &Binding, source: Arc<Source>) {
        assert_eq!(
            service
                .start(saved.clone(), source, TIME, Cancellation::default())
                .await
                .unwrap()
                .state,
            State::EngineStarted
        );
    }
    async fn route(dialer: &OverlayDialer) -> OverlayRouteIdentity {
        let stream = dialer
            .dial("echo".into(), 22, Cancellation::default())
            .await
            .unwrap();
        let identity = stream.route_identity().unwrap();
        drop(stream);
        identity
    }
    fn recovery_target(route: OverlayRouteIdentity) -> crate::input::InputIdentity {
        crate::input::InputIdentity {
            route: Some(route),
            host: "synthetic.invalid".into(),
            port: 22,
            user: "synthetic".into(),
            host_key: "synthetic-key".into(),
            socket: "/synthetic/socket".into(),
            herdr: "/synthetic/herdr".into(),
            session: "synthetic".into(),
            pane: "w:p1".into(),
            terminal: "term_123".into(),
        }
    }
    struct Temp(std::path::PathBuf);
    impl Temp {
        fn new() -> Self {
            use ring::rand::SecureRandom;
            let mut bytes = [0; 16];
            ring::rand::SystemRandom::new().fill(&mut bytes).unwrap();
            let id = bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
            Self(std::env::temp_dir().join(format!("herdr-mobile-node-recovery-{id}")))
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    async fn stop(service: &MobileNodeService, saved: &Binding) {
        // Busy only means an earlier cleanup worker is still returning. This
        // loop represents distinct explicit host cleanup calls, never start.
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                match service.stop(saved, TIME).await {
                    Ok(snapshot) => {
                        assert_eq!(snapshot.state, State::Stopped);
                        break;
                    }
                    Err("mobile_node_busy") => tokio::task::yield_now().await,
                    other => panic!("unexpected cleanup result: {other:?}"),
                }
            }
        })
        .await
        .unwrap();
    }

    #[tokio::test]
    async fn same_config_restart_preserves_recovery_identity_but_old_dialer_stays_stale() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let saved = binding("restart");
        let source = Arc::new(Source::default());
        start(&service, &saved, source.clone()).await;
        let old = service.dialer(&saved, TIME).unwrap();
        let first_route = route(&old).await;
        assert_eq!(first_route.profile_revision, 7);
        stop(&service, &saved).await;
        start(&service, &saved, source.clone()).await;
        let new = service.dialer(&saved, TIME).unwrap();
        assert_eq!(route(&new).await, first_route);
        assert_eq!(
            old.dial("echo".into(), 22, Cancellation::default())
                .await
                .err(),
            Some("overlay_stale_revision")
        );
        {
            let specs = lock(&source.specs);
            assert_eq!(specs.len(), 2);
            assert!(specs[1].revision > specs[0].revision);
            assert_eq!(specs[0].profile_revision, 7);
            assert_eq!(specs[1].profile_revision, 7);
        }
        assert_eq!(metric(8), 2);
        stop(&service, &saved).await;
        until(|| metric(7) == 0 && service.reserved_nodes() == 0).await;
    }

    #[tokio::test]
    async fn status_does_not_publish_engine_started_before_start_claims_lease() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let saved = binding("claim-race");
        let source = Arc::new(Source {
            blocked: true,
            ..Source::default()
        });
        let mut starting =
            Box::pin(service.start(saved.clone(), source.clone(), TIME, Cancellation::default()));
        std::future::poll_fn(|cx| {
            assert!(starting.as_mut().poll(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        until(|| source.loaded.load(Ordering::SeqCst) == 1).await;
        source.release();
        // Wait for native completion without polling the service future. This
        // forces the gap between engine readiness and claimed lease publish.
        let attempt = lock(&service.inner.registry)
            .entries
            .get(saved.profile_id())
            .unwrap()
            .attempt;
        loop {
            if service
                .inner
                .runtime
                .node_status_revision(&saved.profile(), attempt)
                .unwrap()
                .await
                .unwrap()
                == NodeStatus::EngineStarted
            {
                break;
            }
            tokio::task::yield_now().await;
        }
        assert_eq!(service.status(&saved).await.unwrap().state, State::Starting);
        assert_eq!(
            service.dialer(&saved, TIME).err(),
            Some("mobile_node_not_started")
        );
        assert_eq!(starting.await.unwrap().state, State::EngineStarted);
        assert!(service.dialer(&saved, TIME).is_ok());
        stop(&service, &saved).await;
    }

    #[tokio::test]
    async fn captured_attempt_cannot_stop_or_observe_restarted_same_binding_or_another_service() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let saved = binding("captured-attempt");
        assert!(service.capture_attempt(&saved).unwrap().is_none());
        start(&service, &saved, Arc::new(Source::default())).await;
        let old = service.capture_attempt(&saved).unwrap().unwrap();
        assert_eq!(
            service.status_attempt(&old).await.unwrap().state,
            State::EngineStarted
        );
        stop(&service, &saved).await;
        start(&service, &saved, Arc::new(Source::default())).await;
        let current = service.capture_attempt(&saved).unwrap().unwrap();
        assert_eq!(
            service.stop_attempt(&old, TIME).await.unwrap_err(),
            "overlay_stale_revision"
        );
        assert_eq!(
            service.status_attempt(&old).await.unwrap_err(),
            "overlay_stale_revision"
        );
        let foreign = MobileNodeService::new();
        assert_eq!(
            foreign.stop_attempt(&current, TIME).await.unwrap_err(),
            "overlay_wrong_owner"
        );
        assert_eq!(
            foreign.status_attempt(&current).await.unwrap_err(),
            "overlay_wrong_owner"
        );
        assert_eq!(
            service.status(&saved).await.unwrap().state,
            State::EngineStarted
        );
        assert_eq!(metric(9), 1);
        assert_eq!(
            service.stop_attempt(&current, TIME).await.unwrap().state,
            State::Stopped
        );
    }

    #[tokio::test]
    async fn stopped_profile_history_is_bounded_without_evicting_known_binding_guards() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let source = Arc::new(Source::default());
        for i in 0..MAX_PROFILE_HISTORY {
            let saved = binding(&format!("history-{i}"));
            start(&service, &saved, source.clone()).await;
            stop(&service, &saved).await;
        }
        assert_eq!(service.reserved_nodes(), 0);
        assert_eq!(
            service
                .start(
                    binding("new-id-over-history-limit"),
                    source.clone(),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap_err(),
            "mobile_node_history_capacity"
        );
        assert_eq!(source.loaded.load(Ordering::SeqCst), MAX_PROFILE_HISTORY);
        let known = binding("history-0");
        start(&service, &known, source.clone()).await;
        stop(&service, &known).await;
        assert_eq!(
            lock(&service.inner.registry).entries.len(),
            MAX_PROFILE_HISTORY
        );
        assert_eq!(metric(8), (MAX_PROFILE_HISTORY + 1) as i32);
    }

    #[tokio::test]
    async fn concurrent_start_and_changed_binding_cannot_replace_pending_or_active_node() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let saved = binding("concurrent");
        let source = Arc::new(Source {
            blocked: true,
            ..Source::default()
        });
        let task_service = service.clone();
        let task_saved = saved.clone();
        let task_source = source.clone();
        let task = tokio::spawn(async move {
            task_service
                .start(task_saved, task_source, TIME, Cancellation::default())
                .await
        });
        until(|| source.loaded.load(Ordering::SeqCst) == 1).await;
        assert_eq!(service.status(&saved).await.unwrap().state, State::Starting);
        assert_eq!(
            service
                .start(saved.clone(), source.clone(), TIME, Cancellation::default())
                .await
                .unwrap_err(),
            "mobile_node_busy"
        );
        let changed = Binding::new(
            saved.profile_id.clone(),
            8,
            "other-network".into(),
            "other-vault".into(),
        )
        .unwrap();
        assert_eq!(
            service
                .start(
                    changed.clone(),
                    source.clone(),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap_err(),
            "mobile_node_binding_mismatch"
        );
        assert_eq!(
            service.status(&changed).await.unwrap_err(),
            "mobile_node_binding_mismatch"
        );
        assert_eq!(
            service.stop(&changed, TIME).await.unwrap_err(),
            "mobile_node_binding_mismatch"
        );
        assert_eq!(
            service.dialer(&changed, TIME).err(),
            Some("mobile_node_binding_mismatch")
        );
        source.release();
        assert_eq!(task.await.unwrap().unwrap().state, State::EngineStarted);
        assert_eq!(source.loaded.load(Ordering::SeqCst), 1);
        assert_eq!(
            service
                .status_profile(saved.profile_id())
                .await
                .unwrap()
                .unwrap()
                .binding,
            saved
        );
        let old = service.dialer(&saved, TIME).unwrap();
        stop(&service, &saved).await;
        let invalid_same_revision = Binding::new(
            saved.profile_id.clone(),
            7,
            "other-network".into(),
            saved.identity_ref.clone(),
        )
        .unwrap();
        assert_eq!(
            service
                .start(
                    invalid_same_revision,
                    Arc::new(Source::default()),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap_err(),
            "overlay_stale_revision"
        );
        start(&service, &changed, Arc::new(Source::default())).await;
        assert_eq!(
            old.dial("echo".into(), 22, Cancellation::default())
                .await
                .err(),
            Some("overlay_stale_revision")
        );
        stop(&service, &changed).await;
    }

    #[tokio::test]
    async fn recreated_vault_identity_has_distinct_recovery_binding_at_same_catalog_revision() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let saved = binding("identity");
        start(&service, &saved, Arc::new(Source::default())).await;
        let old = service.dialer(&saved, TIME).unwrap();
        let old_route = route(&old).await;
        let recreated = Binding::new(
            saved.profile_id.clone(),
            saved.profile_revision,
            saved.network_name.clone(),
            "synthetic-vault-B".into(),
        )
        .unwrap();
        assert_eq!(
            service
                .start(
                    recreated.clone(),
                    Arc::new(Source::default()),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap_err(),
            "mobile_node_binding_mismatch"
        );
        stop(&service, &saved).await;
        start(&service, &recreated, Arc::new(Source::default())).await;
        let new_route = route(&service.dialer(&recreated, TIME).unwrap()).await;
        assert_eq!(old_route.profile_revision, new_route.profile_revision);
        assert_ne!(old_route, new_route);
        // Use routes produced by the actual fixture streams, including the
        // vault generation, in the same durable unknown-input marker path.
        let temp = Temp::new();
        let recovery = crate::recovery::Recovery::open(temp.0.clone());
        let old_target = recovery_target(old_route);
        let new_target = recovery_target(new_route);
        let request = "0123456789abcdef0123456789abcdef";
        recovery.prepare(&old_target, request).unwrap();
        recovery.end_attempt(&old_target, request);
        assert_eq!(
            recovery.clear_confirmed(&new_target, None),
            Err("input_original_target_required")
        );
        assert!(recovery.unknown());
        recovery.clear_confirmed(&old_target, None).unwrap();
        recovery.prepare(&new_target, request).unwrap();
        recovery.end_attempt(&new_target, request);
        assert_eq!(
            recovery.clear_confirmed(&old_target, None),
            Err("input_original_target_required")
        );
        assert!(recovery.unknown());
        recovery.clear_confirmed(&new_target, None).unwrap();
        assert_eq!(
            old.dial("echo".into(), 22, Cancellation::default())
                .await
                .err(),
            Some("overlay_stale_revision")
        );
        assert_eq!(
            service.stop(&saved, TIME).await.unwrap_err(),
            "mobile_node_binding_mismatch"
        );
        stop(&service, &recreated).await;
    }

    #[tokio::test]
    async fn cancelled_late_native_start_retains_quota_and_never_attaches_or_retries_start() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let saved = binding("late");
        let cancel = Cancellation::default();
        let task_service = service.clone();
        let task_saved = saved.clone();
        let task_cancel = cancel.clone();
        let task = tokio::spawn(async move {
            task_service
                .start(
                    task_saved,
                    Arc::new(Source {
                        mode: "late-start",
                        ..Source::default()
                    }),
                    TIME,
                    task_cancel,
                )
                .await
        });
        until(|| metric(8) == 1 && metric(5) == 1).await;
        cancel.cancel();
        assert_eq!(
            tokio::time::timeout(Duration::from_millis(200), task)
                .await
                .unwrap()
                .unwrap()
                .unwrap_err(),
            "cancelled"
        );
        assert_eq!(service.reserved_nodes(), 1);
        assert_eq!(service.status(&saved).await.unwrap().state, State::Closing);
        assert_eq!(
            service
                .start(
                    saved.clone(),
                    Arc::new(Source::default()),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap_err(),
            "mobile_node_busy"
        );
        assert_eq!(
            service.dialer(&saved, TIME).err(),
            Some("mobile_node_not_started")
        );
        unsafe { fixture_control(3) };
        until(|| service.reserved_nodes() == 0 && metric(7) == 0).await;
        assert_eq!(metric(8), 1);
        assert_eq!(metric(9), 1);
        assert_eq!(service.status(&saved).await.unwrap().state, State::Stopped);
        start(&service, &saved, Arc::new(Source::default())).await;
        stop(&service, &saved).await;
    }

    #[tokio::test]
    async fn dropped_start_and_explicit_stop_during_secure_load_never_activate_late_result() {
        let _serial = isolated().await;
        for explicit_stop in [false, true] {
            let service = MobileNodeService::new();
            let saved = binding(if explicit_stop {
                "stop-loading"
            } else {
                "drop-loading"
            });
            let source = Arc::new(Source {
                blocked: true,
                ..Source::default()
            });
            let task_service = service.clone();
            let task_saved = saved.clone();
            let task_source = source.clone();
            let task = tokio::spawn(async move {
                task_service
                    .start(task_saved, task_source, TIME, Cancellation::default())
                    .await
            });
            until(|| source.loaded.load(Ordering::SeqCst) == 1).await;
            let stopping = if explicit_stop {
                let stopping_service = service.clone();
                let stopping_saved = saved.clone();
                Some(tokio::spawn(async move {
                    stopping_service.stop(&stopping_saved, TIME).await
                }))
            } else {
                task.abort();
                None
            };
            until(|| {
                lock(&service.inner.registry)
                    .entries
                    .get(saved.profile_id())
                    .unwrap()
                    .state
                    == State::Closing
            })
            .await;
            assert_eq!(service.reserved_nodes(), 1);
            source.release();
            if let Some(stopping) = stopping {
                assert_eq!(task.await.unwrap().unwrap_err(), "cancelled");
                assert_eq!(stopping.await.unwrap().unwrap().state, State::Stopped);
            } else {
                assert!(task.await.unwrap_err().is_cancelled());
            }
            until(|| service.reserved_nodes() == 0).await;
            assert_eq!(service.status(&saved).await.unwrap().state, State::Stopped);
            assert_eq!(
                service.dialer(&saved, TIME).err(),
                Some("mobile_node_not_started")
            );
        }
        assert_eq!(metric(8), 0);
    }

    #[tokio::test]
    async fn eight_failed_cleanup_nodes_keep_capacity_until_explicit_stop() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let source = Arc::new(Source {
            mode: "start-fail;stop-fail",
            ..Source::default()
        });
        let saved = (0..8)
            .map(|i| binding(&format!("quota-{i}")))
            .collect::<Vec<_>>();
        for value in &saved {
            assert_eq!(
                service
                    .start(value.clone(), source.clone(), TIME, Cancellation::default())
                    .await
                    .unwrap_err(),
                "mobile_node_failed"
            );
        }
        until(|| metric(9) == 8).await;
        assert_eq!(service.reserved_nodes(), 8);
        assert_eq!(
            service
                .start(
                    binding("ninth"),
                    source.clone(),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap_err(),
            "mobile_node_capacity"
        );
        assert_eq!(source.loaded.load(Ordering::SeqCst), 8);
        assert_eq!(metric(8), 8);
        for value in &saved {
            stop(&service, value).await;
        }
        assert_eq!(service.reserved_nodes(), 0);
        assert_eq!(metric(9), 16);
        assert_eq!(metric(8), 8);
    }
}

#[cfg(feature = "overlay-tailscale-fixture")]
mod tailscale_native {
    use super::*;
    use crate::transport::{Dialer, OverlayProvider};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    static SERIAL: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
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
    async fn until(test: impl Fn() -> bool) {
        tokio::time::timeout(Duration::from_secs(5), async {
            while !test() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
    }
    async fn isolated() -> tokio::sync::MutexGuard<'static, ()> {
        let guard = SERIAL.lock().await;
        until(|| metric(2) == 0).await;
        unsafe { hp_ts_fixture_reset() };
        guard
    }
    #[derive(Default)]
    struct Store(Mutex<HashMap<Vec<u8>, Vec<u8>>>);
    impl NativeStateStore for Store {
        fn read(&self, key: &[u8]) -> StateStoreResult<Vec<u8>> {
            lock(&self.0)
                .get(key)
                .cloned()
                .ok_or(StateStoreError::Missing)
        }
        fn write(&self, key: &[u8], value: Option<&[u8]>) -> StateStoreResult<()> {
            let mut rows = lock(&self.0);
            if let Some(value) = value {
                rows.insert(key.to_vec(), value.to_vec());
            } else {
                rows.remove(key);
            }
            Ok(())
        }
    }
    struct Source {
        store: Arc<Store>,
        hostname: &'static str,
        loaded: AtomicUsize,
    }
    impl NativeStateSource for Source {
        fn load(&self, spec: &NodeSpec) -> overlay_runtime::Result<NativeNodeConfig> {
            self.loaded.fetch_add(1, Ordering::SeqCst);
            NativeNodeConfig::for_spec(
                spec,
                NativeVettedDirectory::from_native_vetted(std::path::PathBuf::from(
                    "/native-vetted/synthetic-no-files",
                ))?,
                self.hostname.into(),
                "https://controlplane.tailscale.com".into(),
                self.store.clone(),
            )
        }
    }
    fn source(hostname: &'static str) -> Arc<Source> {
        Arc::new(Source {
            store: Arc::new(Store::default()),
            hostname,
            loaded: AtomicUsize::new(0),
        })
    }
    fn saved(id: &str) -> Binding {
        Binding::with_provider(
            BindingProvider::Tailscale,
            id.into(),
            9,
            "synthetic-tailnet".into(),
            "native-store-A".into(),
        )
        .unwrap()
    }
    #[tokio::test]
    async fn login_state_gates_dialer_and_route_keeps_provider_revision_identity() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let binding = saved("ts-mobile");
        let source = source("fixture");
        assert_eq!(
            service
                .start_tailscale(
                    binding.clone(),
                    source.clone(),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap()
                .state,
            State::NeedsLogin
        );
        assert_eq!(
            service.dialer(&binding, TIME).err(),
            Some("mobile_node_not_started")
        );
        assert_eq!(metric(5), 0);
        let login = service
            .begin_login(&binding, TIME, Cancellation::default())
            .await
            .unwrap();
        assert_eq!(login.state, State::NeedsMachineAuth);
        assert!(login.auth_url.as_ref().unwrap().starts_with("https://"));
        assert!(!format!("{login:?}").contains("token"));
        unsafe { hp_ts_fixture_all_running() };
        assert_eq!(
            service.status(&binding).await.unwrap().state,
            State::Running
        );
        let old_attempt = service.capture_attempt(&binding).unwrap().unwrap();
        let dialer = service.dialer(&binding, TIME).unwrap();
        let mut connected = dialer
            .dial("same-virtual-address".into(), 22, Cancellation::default())
            .await
            .unwrap();
        let route = connected
            .route_identity()
            .expect("must not fall back to system TCP");
        assert_eq!(route.provider, OverlayProvider::Tailscale);
        assert_eq!(route.profile_revision, 9);
        assert_eq!(route.identity_ref, "native-store-A");
        connected.write_all(b"once").await.unwrap();
        let mut bytes = [0; 4];
        connected.read_exact(&mut bytes).await.unwrap();
        assert_eq!(&bytes, b"once");
        assert_eq!(metric(7), 1);
        drop(connected);
        service.stop(&binding, TIME).await.unwrap();
        until(|| service.reserved_nodes() == 0).await;
        assert_eq!(
            service
                .start_tailscale(
                    binding.clone(),
                    source.clone(),
                    TIME,
                    Cancellation::default()
                )
                .await
                .unwrap()
                .state,
            State::NeedsLogin
        );
        assert_eq!(
            service.stop_attempt(&old_attempt, TIME).await.unwrap_err(),
            "overlay_stale_revision"
        );
        assert_eq!(
            dialer
                .dial("same-virtual-address".into(), 22, Cancellation::default())
                .await
                .err(),
            Some("overlay_stale_revision")
        );
        assert_eq!(source.loaded.load(Ordering::SeqCst), 2);
        service.stop(&binding, TIME).await.unwrap();
    }
    #[tokio::test]
    async fn auth_polling_and_old_attempt_never_reissue_login() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let binding = saved("ts-auth-attempt");
        let source = source("fixture");
        service
            .start_tailscale(
                binding.clone(),
                source.clone(),
                TIME,
                Cancellation::default(),
            )
            .await
            .unwrap();
        let old = service.capture_attempt(&binding).unwrap().unwrap();
        let before = service
            .login_status_attempt(&old, TIME, Cancellation::default())
            .await
            .unwrap();
        assert_eq!(before.state, State::NeedsLogin);
        assert!(before.auth_url.is_none());
        assert_eq!(metric(5), 0);
        let login = service
            .begin_login_attempt(&old, TIME, Cancellation::default())
            .await
            .unwrap();
        assert!(login.auth_url.is_some());
        for _ in 0..3 {
            assert_eq!(
                service
                    .login_status_attempt(&old, TIME, Cancellation::default())
                    .await
                    .unwrap()
                    .auth_url,
                login.auth_url
            );
        }
        assert_eq!(metric(5), 1);
        service.stop(&binding, TIME).await.unwrap();
        until(|| service.reserved_nodes() == 0).await;
        service
            .start_tailscale(binding.clone(), source, TIME, Cancellation::default())
            .await
            .unwrap();
        assert_eq!(
            service
                .begin_login_attempt(&old, TIME, Cancellation::default())
                .await
                .unwrap_err(),
            "overlay_stale_revision"
        );
        assert_eq!(
            service
                .login_status_attempt(&old, TIME, Cancellation::default())
                .await
                .unwrap_err(),
            "overlay_stale_revision"
        );
        assert!(
            service
                .login_status(&binding, TIME, Cancellation::default())
                .await
                .unwrap()
                .auth_url
                .is_none()
        );
        assert_eq!(metric(5), 1);
        service.stop(&binding, TIME).await.unwrap();
    }
    #[tokio::test]
    async fn original_cancel_before_login_admission_needs_no_future_repoll() {
        use std::future::Future;
        use std::task::{Context, Poll, Waker};
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let binding = saved("ts-cancel-before-admission");
        service
            .start_tailscale(
                binding.clone(),
                source("fixture"),
                TIME,
                Cancellation::default(),
            )
            .await
            .unwrap();
        let original = Cancellation::default();
        let attempt = service.capture_attempt(&binding).unwrap().unwrap();
        let (entered_tx, entered_rx) = std::sync::mpsc::channel();
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        let (checked_tx, checked_rx) = std::sync::mpsc::channel();
        let release_rx = Mutex::new(release_rx);
        let first = std::sync::atomic::AtomicBool::new(true);
        let original_for_worker = original.clone();
        let check: Arc<dyn Fn() -> bool + Send + Sync> = Arc::new(move || {
            if first.swap(false, Ordering::SeqCst) {
                entered_tx.send(()).unwrap();
                lock(&release_rx).recv().unwrap();
                // Model an early check that saw the still-live token before
                // its pause. The decisive check is after the admission CAS.
                false
            } else {
                let cancelled = original_for_worker.is_cancelled();
                checked_tx.send(cancelled).unwrap();
                cancelled
            }
        });
        let mut future = Box::pin(service.login_checked_with_cancel_check(
            &binding,
            Some(attempt.attempt),
            TIME,
            original.clone(),
            true,
            check,
        ));
        let waker = Waker::noop();
        let mut context = Context::from_waker(waker);
        assert!(matches!(future.as_mut().poll(&mut context), Poll::Pending));
        entered_rx.recv_timeout(TIME).unwrap();
        // Do not poll the service future after cancelling; its select! cannot
        // yet drop NodeOperation or propagate cancellation on our behalf.
        original.cancel();
        release_tx.send(()).unwrap();
        assert!(checked_rx.recv_timeout(TIME).unwrap());
        tokio::time::sleep(Duration::from_millis(20)).await;
        assert_eq!(metric(9), 0, "native login must not be admitted");
        assert_eq!(future.await.unwrap_err(), "cancelled");
        service.stop(&binding, TIME).await.unwrap();
        until(|| metric(2) == 0).await;
    }
    #[tokio::test]
    async fn cancel_after_login_admission_discards_result_and_stop_waits() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let binding = saved("ts-cancel-after-admission");
        service
            .start_tailscale(
                binding.clone(),
                source("fixture"),
                TIME,
                Cancellation::default(),
            )
            .await
            .unwrap();
        struct ReleaseLogin;
        impl Drop for ReleaseLogin {
            fn drop(&mut self) {
                unsafe { hp_ts_fixture_control(5) };
            }
        }
        unsafe { hp_ts_fixture_control(4) };
        let release = ReleaseLogin;
        let original = Cancellation::default();
        let task_cancel = original.clone();
        let worker = service.clone();
        let target = binding.clone();
        let task =
            tokio::spawn(async move { worker.begin_login(&target, TIME, task_cancel).await });
        until(|| metric(9) == 1).await;
        original.cancel();
        assert_eq!(task.await.unwrap().unwrap_err(), "cancelled");
        assert_eq!(
            service
                .stop(&binding, Duration::from_millis(20))
                .await
                .unwrap_err(),
            "mobile_node_cleanup_pending"
        );
        assert_eq!(metric(4), 0, "native stop must wait for admitted login");
        drop(release);
        until(|| metric(5) == 1).await;
        service.stop(&binding, TIME).await.unwrap();
        assert_eq!(metric(9), 1, "cancelled login must not replay");
        until(|| metric(2) == 0).await;
    }
    #[tokio::test]
    async fn stop_retains_node_until_admitted_login_returns_without_replay() {
        let _serial = isolated().await;
        let service = MobileNodeService::new();
        let binding = saved("ts-login-stop-drain");
        service
            .start_tailscale(
                binding.clone(),
                source("fixture"),
                TIME,
                Cancellation::default(),
            )
            .await
            .unwrap();
        struct ReleaseLogin;
        impl Drop for ReleaseLogin {
            fn drop(&mut self) {
                unsafe { hp_ts_fixture_control(5) };
            }
        }
        unsafe { hp_ts_fixture_control(4) };
        let release = ReleaseLogin;
        let worker = service.clone();
        let target = binding.clone();
        let task = tokio::spawn(async move {
            worker
                .begin_login(&target, TIME, Cancellation::default())
                .await
        });
        until(|| metric(9) == 1).await;
        assert_eq!(
            service
                .begin_login(&binding, TIME, Cancellation::default())
                .await
                .unwrap_err(),
            "mobile_node_busy"
        );
        assert_eq!(
            service
                .stop(&binding, Duration::from_millis(20))
                .await
                .unwrap_err(),
            "mobile_node_cleanup_pending"
        );
        assert_eq!(service.reserved_nodes(), 1);
        assert_eq!(metric(4), 0, "native stop must wait for admitted login");
        assert_eq!(metric(9), 1, "a concurrent login must not be dispatched");
        drop(release);
        assert!(
            task.await.unwrap().is_err(),
            "retired login result must not be published"
        );
        service.stop(&binding, TIME).await.unwrap();
        assert_eq!(metric(5), 1, "no automatic authentication replay");
        until(|| metric(2) == 0).await;
    }
    #[tokio::test]
    async fn cancelled_tailscale_start_uses_original_attempt_cleanup_without_replaying_source() {
        let _serial = isolated().await;
        unsafe { hp_ts_fixture_control(1) };
        let service = MobileNodeService::new();
        let binding = saved("late-mobile");
        let source = source("late-start");
        let cancel = Cancellation::default();
        let owned_service = service.clone();
        let owned_binding = binding.clone();
        let owned_source = source.clone();
        let owned_cancel = cancel.clone();
        let task = tokio::spawn(async move {
            owned_service
                .start_tailscale(owned_binding, owned_source, TIME, owned_cancel)
                .await
        });
        until(|| metric(3) == 1).await;
        cancel.cancel();
        assert_eq!(task.await.unwrap().unwrap_err(), "cancelled");
        assert_eq!(service.reserved_nodes(), 1);
        assert_eq!(
            service.status(&binding).await.unwrap().state,
            State::Closing
        );
        unsafe { hp_ts_fixture_control(2) };
        until(|| service.reserved_nodes() == 0).await;
        assert_eq!(
            service.status(&binding).await.unwrap().state,
            State::Stopped
        );
        assert_eq!(source.loaded.load(Ordering::SeqCst), 1);
        assert_eq!(metric(1), 1);
    }
}
