use super::*;

fn binding(id: char) -> Binding {
    Binding::new(
        id.to_string().repeat(32),
        7,
        "synthetic-network".into(),
        "11111111-1111-4111-8111-111111111111".into(),
    )
    .unwrap()
}
#[cfg(not(any(feature = "network-easytier", feature = "native-fixture")))]
fn args(value: Value) -> String {
    value.to_string()
}

#[test]
fn scope_and_open_admission_are_bounded_monotonic_and_cancel_ahead_is_exact() {
    let bridge = Bridge::new(Arc::new(AndroidSource)).unwrap();
    let scopes = (0..MAX_SCOPES)
        .map(|_| bridge.new_scope().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(bridge.new_scope().unwrap_err(), "network_scope_capacity");
    let scope = scopes[0];
    for id in ["0", "01", "-1", "1x", "18446744073709551616"] {
        assert!(bridge.reserve_open(scope, id).is_err());
    }
    bridge.cancel_open(scope, "2").unwrap();
    bridge.reserve_open(scope, "1").unwrap();
    assert_eq!(bridge.reserve_open(scope, "2").unwrap_err(), "cancelled");
    bridge.reserve_open(scope, "3").unwrap();
    assert_eq!(
        bridge.reserve_open(scope, "3").unwrap_err(),
        "network_open_id_reused"
    );
    assert_eq!(
        bridge.reserve_open(scope, "1").unwrap_err(),
        "network_open_id_reused"
    );
    for id in 10..10 + MAX_TOMBSTONES {
        bridge.cancel_open(scope, &id.to_string()).unwrap();
    }
    assert_eq!(
        bridge.cancel_open(scope, "99999").err(),
        Some("network_cancel_capacity")
    );
    bridge.close_scope(scope).unwrap();
    let fresh = bridge.new_scope().unwrap();
    assert!(fresh > *scopes.last().unwrap());
    assert_eq!(
        bridge.reserve_open(scope, "4").unwrap_err(),
        "network_scope_unavailable"
    );
    for scope in scopes.into_iter().skip(1).chain([fresh]) {
        bridge.close_scope(scope).unwrap();
    }
}

#[cfg(not(any(feature = "network-easytier", feature = "native-fixture")))]
#[test]
fn default_build_is_unavailable_without_vault_or_network_fallback() {
    let bridge = Bridge::new(Arc::new(AndroidSource)).unwrap();
    let scope = bridge.new_scope().unwrap();
    bridge.executor.block_on(async {
        let reply = bridge
            .call(scope, "available", "{}", Vec::new())
            .await
            .unwrap();
        assert_eq!(
            reply.value,
            json!({"available":false,"reason":"overlay_provider_unavailable"})
        );
        let reply = bridge
            .call(
                scope,
                "nodeStatus",
                &args(json!({"profileId":"a".repeat(32)})),
                Vec::new(),
            )
            .await
            .unwrap();
        assert_eq!(reply.value, json!({"state":"unavailable","binding":null}));
        assert_eq!(
            bridge
                .call(
                    scope,
                    "nodeStart",
                    &args(json!({"binding":binding('a'),"peers":["tcp://synthetic.invalid:1"]})),
                    Vec::new()
                )
                .await
                .err(),
            Some("overlay_provider_unavailable")
        );
        assert_eq!(bridge.service.reserved_nodes(), 0);
        assert_eq!(bridge.service.reserved_streams(), 0);
    });
    bridge.close_scope(scope).unwrap();
}

#[test]
fn queued_open_reservations_share_one_thirty_two_slot_budget() {
    let bridge = Bridge::new(Arc::new(AndroidSource)).unwrap();
    let a = bridge.new_scope().unwrap();
    let b = bridge.new_scope().unwrap();
    for id in 1..=MAX_STREAMS / 2 {
        bridge.reserve_open(a, &id.to_string()).unwrap();
        bridge.reserve_open(b, &id.to_string()).unwrap();
    }
    assert_eq!(bridge.reserve_open(a, "17").err(), Some("network_capacity"));
    bridge.close_scope(b).unwrap();
    assert_eq!(
        bridge.reserve_open(a, "17").err(),
        Some("network_open_id_reused")
    );
    bridge.reserve_open(a, "18").unwrap();
    bridge.close_scope(a).unwrap();
    assert!(lock(&bridge.registry).opens.is_empty());
}

#[cfg(feature = "native-fixture")]
mod fixture {
    use super::*;
    use herdr_readonly_transport::mobile_nodes::SecretConfig;
    use std::time::Instant;
    unsafe extern "C" {
        fn fixture_reset();
        fn fixture_control(operation: i32);
        fn fixture_metric(metric: i32) -> i32;
    }
    static SERIAL: Mutex<()> = Mutex::new(());
    fn metric(id: i32) -> i32 {
        unsafe { fixture_metric(id) }
    }
    fn control(id: i32) {
        unsafe { fixture_control(id) }
    }
    fn isolated() -> MutexGuard<'static, ()> {
        let guard = lock(&SERIAL);
        let until = Instant::now() + Duration::from_secs(5);
        while metric(0) != 0 || metric(5) != 0 || metric(7) != 0 {
            assert!(
                Instant::now() < until,
                "prior synthetic fixture did not drain"
            );
            std::thread::sleep(Duration::from_millis(1));
        }
        unsafe {
            fixture_reset();
        }
        guard
    }
    struct SyntheticFactory {
        mode: &'static str,
    }
    struct SyntheticSource {
        mode: &'static str,
    }
    impl SecureConfigSource for SyntheticSource {
        fn load(
            &self,
            spec: &herdr_readonly_transport::mobile_nodes::NodeSpec,
        ) -> overlay_runtime::Result<SecretConfig> {
            assert_eq!(spec.profile_revision, 7);
            SecretConfig::from_bytes(format!("{};{}", spec.network, self.mode).into_bytes())
        }
    }
    impl SourceFactory for SyntheticFactory {
        fn available(&self) -> Result<()> {
            Ok(())
        }
        fn create(&self, _: &Binding, _: Vec<String>) -> Result<Arc<dyn SecureConfigSource>> {
            Ok(Arc::new(SyntheticSource { mode: self.mode }))
        }
    }
    fn bridge(mode: &'static str) -> Arc<Bridge> {
        Bridge::new(Arc::new(SyntheticFactory { mode })).unwrap()
    }
    async fn until(predicate: impl Fn() -> bool) {
        tokio::time::timeout(Duration::from_secs(5), async {
            while !predicate() {
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
        })
        .await
        .unwrap();
    }
    async fn start(bridge: &Bridge, scope: u64, saved: &Binding) {
        assert_eq!(
            bridge
                .start_node(
                    scope,
                    StartArgs {
                        binding: saved.clone(),
                        peers: vec!["fixture://explicit".into()]
                    }
                )
                .await
                .unwrap()
                .value["state"],
            "engine-started"
        );
    }
    async fn stop(bridge: &Bridge, scope: u64, saved: &Binding) {
        loop {
            match bridge.stop_node(scope, saved.clone()).await {
                Ok(reply) => {
                    assert_eq!(reply.value["state"], "stopped");
                    break;
                }
                Err("mobile_node_busy") => tokio::task::yield_now().await,
                other => panic!("unexpected explicit stop: {:?}", other.err()),
            }
        }
    }
    async fn open(bridge: &Arc<Bridge>, scope: u64, saved: &Binding, id: u64, host: &str) -> Reply {
        bridge.reserve_open(scope, &id.to_string()).unwrap();
        bridge
            .open_stream(
                scope,
                OpenArgs {
                    binding: saved.clone(),
                    host: host.into(),
                    port: 22,
                    open_id: id.to_string(),
                },
            )
            .await
            .unwrap()
    }
    async fn read(bridge: &Bridge, scope: u64, token: &str, max: usize) -> Reply {
        bridge
            .read_stream(
                scope,
                ReadArgs {
                    stream_id: token.into(),
                    max_bytes: max,
                },
            )
            .await
            .unwrap()
    }
    fn token(reply: &Reply) -> String {
        reply.value["streamId"].as_str().unwrap().into()
    }

    #[test]
    fn actual_overlay_stream_route_and_engine_scopes_do_not_cross_or_reuse_tokens() {
        let _serial = isolated();
        let bridge = bridge("");
        let a = bridge.new_scope().unwrap();
        let b = bridge.new_scope().unwrap();
        bridge.executor.block_on(async {
            let saved_a=binding('a');let saved_b=binding('b');start(&bridge,a,&saved_a).await;start(&bridge,b,&saved_b).await;
            let first=open(&bridge,a,&saved_a,1,"read-block").await;let first_token=token(&first);
            assert_eq!(first.value["route"],json!({"provider":"easy-tier","profile_id":"a".repeat(32),"profile_revision":7,"identity_ref":saved_a.identity_ref()}));
            assert_eq!(bridge.read_stream(b,ReadArgs{stream_id:first_token.clone(),max_bytes:8}).await.err(),Some("network_scope_mismatch"));
            let task_bridge=bridge.clone();let task_token=first_token.clone();
            let pending_read=tokio::spawn(async move {task_bridge.read_stream(a,ReadArgs{stream_id:task_token,max_bytes:8}).await});
            until(||bridge.stream(a,&first_token,false).unwrap().read_busy.load(Ordering::Acquire)).await;
            bridge.close_scope(a).unwrap();
            assert_eq!(tokio::time::timeout(Duration::from_millis(200),pending_read).await.unwrap().unwrap().err(),Some("overlay_transport_failed"));
            until(||bridge.service.reserved_nodes()==1).await;
            let second=open(&bridge,b,&saved_b,1,"read-block").await;let second_token=token(&second);
            assert_ne!(first_token,second_token);
            assert_eq!(bridge.write_stream(b,&second_token,b"other engine remains live".to_vec()).await.unwrap().value["accepted"],25);
            assert_eq!(read(&bridge,b,&second_token,64).await.bytes.unwrap(),b"other engine remains live");
            assert!(bridge.stream(b,&first_token,false).is_err());
            stop(&bridge,b,&saved_b).await;bridge.close_scope(b).unwrap();
            until(||bridge.service.reserved_nodes()==0&&bridge.service.reserved_streams()==0).await;
        });
    }

    #[test]
    fn idle_reads_resume_original_operation_and_never_block_write_or_control() {
        let _serial = isolated();
        let bridge = bridge("");
        let scope = bridge.new_scope().unwrap();
        bridge.executor.block_on(async {
            let saved = binding('a');
            start(&bridge, scope, &saved).await;
            let stream = token(&open(&bridge, scope, &saved, 1, "read-block").await);
            for _ in 0..2 {
                let start = Instant::now();
                let idle = read(&bridge, scope, &stream, 2).await;
                assert_eq!(idle.value, json!({"eof":false}));
                assert!(idle.bytes.unwrap().is_empty());
                assert!(start.elapsed() >= READ_WAIT);
                assert_eq!(metric(5), 1);
            }
            let task_bridge = bridge.clone();
            let task_stream = stream.clone();
            let pending =
                tokio::spawn(async move { read(&task_bridge, scope, &task_stream, 1).await });
            until(|| {
                bridge
                    .stream(scope, &stream, false)
                    .unwrap()
                    .read_busy
                    .load(Ordering::Acquire)
            })
            .await;
            assert_eq!(
                bridge
                    .read_stream(
                        scope,
                        ReadArgs {
                            stream_id: stream.clone(),
                            max_bytes: 1
                        }
                    )
                    .await
                    .err(),
                Some("network_stream_busy")
            );
            assert_eq!(
                bridge
                    .write_stream(scope, &stream, b"abc".to_vec())
                    .await
                    .unwrap()
                    .value["accepted"],
                3
            );
            assert_eq!(pending.await.unwrap().bytes.unwrap(), b"a");
            assert_eq!(read(&bridge, scope, &stream, 1).await.bytes.unwrap(), b"b");
            assert_eq!(read(&bridge, scope, &stream, 8).await.bytes.unwrap(), b"c");
            bridge.write_control(scope, &stream, false).await.unwrap();
            bridge.write_control(scope, &stream, true).await.unwrap();
            let eof = read(&bridge, scope, &stream, 8).await;
            assert_eq!(eof.value, json!({"eof":true}));
            assert!(eof.bytes.unwrap().is_empty());
            stop(&bridge, scope, &saved).await;
            bridge.close_scope(scope).unwrap();
        });
    }

    #[test]
    fn partial_writes_advance_only_prefix_and_unknown_is_sticky_without_replay() {
        let _serial = isolated();
        let bridge = bridge("");
        let scope = bridge.new_scope().unwrap();
        bridge.executor.block_on(async {
            let saved = binding('a');
            start(&bridge, scope, &saved).await;
            let short = token(&open(&bridge, scope, &saved, 1, "short").await);
            let bytes = b"abcdef";
            let mut accepted = 0;
            while accepted < bytes.len() {
                accepted += bridge
                    .write_stream(scope, &short, bytes[accepted..].to_vec())
                    .await
                    .unwrap()
                    .value["accepted"]
                    .as_u64()
                    .unwrap() as usize;
            }
            assert_eq!(metric(6), 6);
            assert_eq!(metric(2), 3);
            let unknown = token(&open(&bridge, scope, &saved, 2, "unknown").await);
            assert_eq!(
                bridge
                    .write_stream(scope, &unknown, b"do not replay".to_vec())
                    .await
                    .err(),
                Some("overlay_unknown_write")
            );
            assert_eq!(
                bridge
                    .write_stream(scope, &unknown, b"do not replay".to_vec())
                    .await
                    .err(),
                Some("network_stream_closed")
            );
            assert_eq!(metric(2), 4);
            assert_eq!(metric(6), 7);
            stop(&bridge, scope, &saved).await;
            bridge.close_scope(scope).unwrap();
        });
    }

    #[test]
    fn cancellation_before_reserve_and_late_open_never_leak_or_attach() {
        let _serial = isolated();
        let bridge = bridge("");
        let scope = bridge.new_scope().unwrap();
        bridge.executor.block_on(async {
            let saved = binding('a');
            start(&bridge, scope, &saved).await;
            bridge.cancel_open(scope, "1").unwrap();
            assert_eq!(bridge.reserve_open(scope, "1").err(), Some("cancelled"));
            assert_eq!(metric(1), 0);
            bridge.reserve_open(scope, "2").unwrap();
            let task_bridge = bridge.clone();
            let task_saved = saved.clone();
            let pending = tokio::spawn(async move {
                task_bridge
                    .open_stream(
                        scope,
                        OpenArgs {
                            binding: task_saved,
                            host: "late".into(),
                            port: 22,
                            open_id: "2".into(),
                        },
                    )
                    .await
            });
            until(|| metric(1) == 1).await;
            bridge.cancel_open(scope, "2").unwrap();
            assert_eq!(
                tokio::time::timeout(Duration::from_millis(200), pending)
                    .await
                    .unwrap()
                    .unwrap()
                    .err(),
                Some("cancelled")
            );
            assert_eq!(bridge.service.reserved_streams(), 1);
            assert_eq!(lock(&bridge.registry).opens.len(), 1);
            control(1);
            until(|| bridge.service.reserved_streams() == 0).await;
            bridge.reserve_open(scope, "3").unwrap();
            assert_eq!(lock(&bridge.registry).opens.len(), 1);
            bridge.cancel_open(scope, "3").unwrap();
            stop(&bridge, scope, &saved).await;
            bridge.close_scope(scope).unwrap();
            assert_eq!(metric(4), 1);
            assert_eq!(metric(1), 1);
        });
    }

    #[test]
    fn thirty_two_closed_but_failed_cleanup_streams_keep_budget_until_node_stop() {
        let _serial = isolated();
        let bridge = bridge("");
        let scope = bridge.new_scope().unwrap();
        bridge.executor.block_on(async {
            let saved = binding('a');
            start(&bridge, scope, &saved).await;
            let mut tokens = Vec::new();
            for id in 1..=MAX_STREAMS {
                tokens.push(token(
                    &open(&bridge, scope, &saved, id as u64, "close-fail").await,
                ));
            }
            for token in &tokens {
                bridge.stream(scope, token, false).unwrap().retire();
            }
            until(|| metric(3) == MAX_STREAMS as i32).await;
            assert_eq!(bridge.service.reserved_streams(), MAX_STREAMS);
            assert_eq!(
                bridge.reserve_open(scope, "33").err(),
                Some("network_capacity")
            );
            assert_eq!(metric(1), MAX_STREAMS as i32);
            stop(&bridge, scope, &saved).await;
            assert_eq!(bridge.service.reserved_streams(), 0);
            bridge.reserve_open(scope, "34").unwrap();
            assert_eq!(lock(&bridge.registry).streams.len(), 0);
            bridge.close_scope(scope).unwrap();
        });
    }

    #[test]
    fn failed_cleanup_retains_retired_engine_capacity_until_explicit_retry() {
        let _serial = isolated();
        let bridge = bridge("stop-fail");
        let mut scopes = Vec::new();
        bridge.executor.block_on(async {
            for id in ['a', 'b', 'c', 'd'] {
                let scope = bridge.new_scope().unwrap();
                let saved = binding(id);
                start(&bridge, scope, &saved).await;
                bridge.close_scope(scope).unwrap();
                scopes.push(scope);
            }
            until(|| metric(9) == 4).await;
            assert_eq!(bridge.service.reserved_nodes(), 4);
            assert_eq!(bridge.new_scope().err(), Some("network_scope_capacity"));
            for scope in &scopes {
                bridge.close_scope(*scope).unwrap();
            }
            until(|| {
                bridge.service.reserved_nodes() == 0 && lock(&bridge.registry).nodes.is_empty()
            })
            .await;
            let fresh = bridge.new_scope().unwrap();
            assert!(fresh > *scopes.last().unwrap());
            bridge.close_scope(fresh).unwrap();
        });
    }

    #[test]
    fn detach_during_late_start_cancels_caller_but_holds_scope_and_node_budget() {
        let _serial = isolated();
        let bridge = bridge("late-start");
        let scope = bridge.new_scope().unwrap();
        bridge.executor.block_on(async {
            let saved = binding('a');
            let task_bridge = bridge.clone();
            let task_saved = saved.clone();
            let pending = tokio::spawn(async move {
                task_bridge
                    .start_node(
                        scope,
                        StartArgs {
                            binding: task_saved,
                            peers: vec!["fixture://explicit".into()],
                        },
                    )
                    .await
            });
            until(|| metric(8) == 1 && metric(5) == 1).await;
            bridge.close_scope(scope).unwrap();
            assert!(
                tokio::time::timeout(Duration::from_millis(200), pending)
                    .await
                    .unwrap()
                    .unwrap()
                    .is_err()
            );
            assert_eq!(bridge.service.reserved_nodes(), 1);
            assert!(lock(&bridge.registry).scopes.contains_key(&scope));
            assert_eq!(
                bridge.reserve_open(scope, "1").err(),
                Some("network_scope_unavailable")
            );
            control(3);
            until(|| {
                bridge.service.reserved_nodes() == 0 && lock(&bridge.registry).nodes.is_empty()
            })
            .await;
            assert_eq!(metric(8), 1);
            assert_eq!(metric(9), 1);
        });
    }

    #[test]
    fn delayed_detach_cleanup_cannot_stop_new_scope_with_the_same_durable_binding() {
        let _serial = isolated();
        let mut bridge = bridge("");
        // Park the real detach cleanup queue while all other production entry
        // points execute on a separate driver. No sleeps choose the ordering.
        let parked = Box::leak(Box::new(
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap(),
        ));
        Arc::get_mut(&mut bridge).unwrap().executor = parked;
        let driver = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let a = bridge.new_scope().unwrap();
        let b = bridge.new_scope().unwrap();
        let saved = binding('a');
        driver.block_on(async {
            start(&bridge, a, &saved).await;
            bridge.reserve_open(a, "1").unwrap();
            let opening_bridge = bridge.clone();
            let opening_saved = saved.clone();
            let opening = tokio::spawn(async move {
                opening_bridge
                    .open_stream(
                        a,
                        OpenArgs {
                            binding: opening_saved,
                            host: "late".into(),
                            port: 22,
                            open_id: "1".into(),
                        },
                    )
                    .await
            });
            until(|| metric(1) == 1).await;
            let stopping_bridge = bridge.clone();
            let stopping_saved = saved.clone();
            let stopping =
                tokio::spawn(async move { stopping_bridge.stop_node(a, stopping_saved).await });
            until(|| {
                lock(&bridge.registry)
                    .nodes
                    .get(saved.profile_id())
                    .unwrap()
                    .cancel
                    .is_cancelled()
            })
            .await;
            assert!(!stopping.is_finished());
            bridge.close_scope(a).unwrap();
            control(1);
            assert!(opening.await.unwrap().is_err());
            assert_eq!(stopping.await.unwrap().unwrap().value["state"], "stopped");
            assert!(
                !lock(&bridge.registry)
                    .nodes
                    .contains_key(saved.profile_id())
            );
            start(&bridge, b, &saved).await;
            assert_eq!(metric(8), 2);
            assert_eq!(metric(9), 1);
        });
        parked.block_on(async {
            // A yielding task queued after detach drives its earlier cleanup
            // through the stale-attempt decision, without waiting for a bug.
            tokio::spawn(async {
                tokio::task::yield_now().await;
            })
            .await
            .unwrap();
            assert_eq!(
                bridge.service.status(&saved).await.unwrap().state,
                State::EngineStarted
            );
            assert_eq!(
                lock(&bridge.registry)
                    .nodes
                    .get(saved.profile_id())
                    .unwrap()
                    .scope,
                b
            );
            assert_eq!(
                metric(9),
                1,
                "old scope cleanup must not call native stop on its replacement"
            );
            let live = token(&open(&bridge, b, &saved, 1, "read-block").await);
            bridge
                .write_stream(b, &live, b"replacement remains live".to_vec())
                .await
                .unwrap();
            assert_eq!(
                read(&bridge, b, &live, 64).await.bytes.unwrap(),
                b"replacement remains live"
            );
            stop(&bridge, b, &saved).await;
            bridge.close_scope(b).unwrap();
        });
    }

    #[test]
    fn status_keeps_reserved_owner_before_admission_with_or_without_stopped_history() {
        let _serial = isolated();
        let bridge = bridge("");
        bridge.executor.block_on(async {
            for (id, history, changed) in [
                ('a', true, 0),
                ('b', false, 0),
                ('c', true, 1),
                ('d', true, 2),
            ] {
                let scope = bridge.new_scope().unwrap();
                let other = bridge.new_scope().unwrap();
                let mut saved = binding(id);
                if history {
                    start(&bridge, scope, &saved).await;
                    stop(&bridge, scope, &saved).await;
                }
                if changed == 1 {
                    saved = Binding::new(
                        saved.profile_id().into(),
                        8,
                        "new-network".into(),
                        saved.identity_ref().into(),
                    )
                    .unwrap();
                } else if changed == 2 {
                    saved = Binding::new(
                        saved.profile_id().into(),
                        7,
                        saved.network_name().into(),
                        "22222222-2222-4222-8222-222222222222".into(),
                    )
                    .unwrap();
                }
                // This is the actual host state between ownership reservation
                // and service.start admission; pause that boundary explicitly.
                let cancel = Cancellation::default();
                let generation = {
                    let mut registry = lock(&bridge.registry);
                    let generation = registry.next_token;
                    registry.next_token += 1;
                    registry.nodes.insert(
                        saved.profile_id().into(),
                        NodeOwner {
                            scope,
                            generation,
                            binding: saved.clone(),
                            cancel: cancel.clone(),
                            start_pending: true,
                        },
                    );
                    generation
                };
                assert_eq!(
                    bridge
                        .status_node(scope, saved.profile_id())
                        .await
                        .unwrap()
                        .value["state"],
                    "starting"
                );
                assert_eq!(
                    lock(&bridge.registry)
                        .nodes
                        .get(saved.profile_id())
                        .unwrap()
                        .generation,
                    generation
                );
                assert_eq!(
                    bridge
                        .start_node(
                            other,
                            StartArgs {
                                binding: saved.clone(),
                                peers: vec!["fixture://explicit".into()]
                            }
                        )
                        .await
                        .err(),
                    Some("mobile_node_busy")
                );
                bridge.close_scope(scope).unwrap();
                assert!(cancel.is_cancelled());
                assert_eq!(
                    bridge
                        .service
                        .start(
                            saved.clone(),
                            Arc::new(SyntheticSource { mode: "" }),
                            DEADLINE,
                            cancel
                        )
                        .await
                        .unwrap_err(),
                    "cancelled"
                );
                until(|| {
                    !lock(&bridge.registry)
                        .nodes
                        .contains_key(saved.profile_id())
                })
                .await;
                bridge.close_scope(other).unwrap();
            }
            assert_eq!(metric(8), 3);
            assert_eq!(metric(9), 3);
            assert_eq!(bridge.service.reserved_nodes(), 0);
        });
    }
}
