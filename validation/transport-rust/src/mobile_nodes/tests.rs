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
        recovery.end_attempt();
        assert_eq!(
            recovery.clear_confirmed(&new_target, None),
            Err("input_original_target_required")
        );
        assert!(recovery.unknown());
        recovery.clear_confirmed(&old_target, None).unwrap();
        recovery.prepare(&new_target, request).unwrap();
        recovery.end_attempt();
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
