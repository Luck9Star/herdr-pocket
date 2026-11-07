//! Explicit local deletion. Preserve the original handle and narrow intent through errors and restart.
use crate::{
    PairingState, RemoteFlow, RemoveHostReply,
    hosts::{Hosts, KeyCleanupMode},
};
use std::sync::{Mutex, atomic::Ordering};

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CleanupReply {
    pub host_id: String,
    pub host_removed: bool,
    pub key_deleted: bool,
    pub mode: KeyCleanupMode,
}

pub fn remove_host(
    state: &PairingState,
    hosts: &Hosts,
    flow: &Mutex<RemoteFlow>,
    id: &str,
) -> Result<RemoveHostReply, String> {
    cleanup_record(state, hosts, flow, id, Some(KeyCleanupMode::Host))?;
    Ok(RemoveHostReply { key_deleted: true })
}

pub fn retry_cleanup(
    state: &PairingState,
    hosts: &Hosts,
    flow: &Mutex<RemoteFlow>,
    id: &str,
) -> Result<CleanupReply, String> {
    // Retry has no caller-controlled mode: only the durable original intent applies.
    cleanup_record(state, hosts, flow, id, None)
}

fn cleanup_record(
    state: &PairingState,
    hosts: &Hosts,
    flow: &Mutex<RemoteFlow>,
    id: &str,
    requested: Option<KeyCleanupMode>,
) -> Result<CleanupReply, String> {
    let _lease = state.enter()?;
    let mut flow = flow.lock().map_err(|_| "state_unavailable")?;
    if flow.owner.is_some() {
        return Err("connection_active".into());
    }
    let record = hosts.get(id)?;
    let mode = match (record.key_cleanup_mode, requested) {
        (Some(original), Some(requested)) if original != requested => {
            return Err("host_key_cleanup_intent_changed".into());
        }
        (Some(original), _) => original,
        (None, Some(requested)) => requested,
        (None, None) => return Err("host_key_cleanup_missing".into()),
    };
    flow.tabs.cancel_hosts(&[id.to_owned()]);
    let mut current = state.current.lock().map_err(|_| "state_unavailable")?;
    if let Some(reference) = &record.pairing {
        let ticket = hosts.prepare_key_cleanup(id, &reference.handle, mode)?;
        let is_current = current
            .as_ref()
            .is_some_and(|p| p.local_handle() == reference.handle);
        if is_current {
            current.as_mut().unwrap().cancel();
            state.restore_required.store(true, Ordering::SeqCst);
        }
        // Exactly one call per new explicit confirmation. Absence is acknowledged for this immutable handle.
        state
            .store
            .delete(&reference.handle)
            .map_err(|_| "device_key_delete_unconfirmed")?;
        hosts
            .finish_key_cleanup(&ticket)
            .map_err(|_| "key_cleanup_commit_unconfirmed")?;
        if is_current {
            current.take();
            state.restore_required.store(false, Ordering::SeqCst);
        }
    } else if mode == KeyCleanupMode::Host {
        hosts.remove(id)?;
    } else {
        return Err("host_key_cleanup_changed".into());
    }
    Ok(CleanupReply {
        host_id: id.to_owned(),
        host_removed: mode == KeyCleanupMode::Host,
        key_deleted: true,
        mode,
    })
}

pub fn reset_current(
    state: &PairingState,
    hosts: &Hosts,
    flow: &Mutex<RemoteFlow>,
) -> Result<(), String> {
    let _lease = state.enter()?;
    let mut flow = flow.lock().map_err(|_| "state_unavailable")?;
    if flow.owner.is_some() {
        return Err("connection_active".into());
    }
    let mut current = state.current.lock().map_err(|_| "state_unavailable")?;
    let Some(pairing) = current.as_mut() else {
        return Ok(());
    };
    let handle = pairing.local_handle().to_string();
    let ticket = if hosts.initialized()? {
        hosts
            .find_handle(&handle)?
            .map(|host| hosts.prepare_key_cleanup(&host.id, &handle, KeyCleanupMode::Identity))
            .transpose()?
    } else {
        None
    };
    flow.tabs.cancel_handle(&handle);
    pairing.cancel();
    state.restore_required.store(true, Ordering::SeqCst);
    state
        .store
        .delete(&handle)
        .map_err(|_| "device_key_delete_unconfirmed")?;
    if let Some(ticket) = ticket {
        hosts
            .finish_key_cleanup(&ticket)
            .map_err(|_| "key_cleanup_commit_unconfirmed")?;
    }
    current.take();
    state.restore_required.store(false, Ordering::SeqCst);
    Ok(())
}

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
mod tests {
    use super::*;
    use crate::hosts::{ImportAction, ImportChoice, Target};
    use herdr_readonly_transport::{
        Result,
        config_transfer::{
            Archive, ArchiveV2, PortableHost, PortableHostV2, PortableTarget, Provider,
        },
        pairing::{KeyStore, VolatileKeyStore, random_public_id},
    };
    use std::{
        path::PathBuf,
        sync::{
            Arc, Barrier,
            atomic::{AtomicBool, AtomicUsize},
        },
    };
    struct FailingStore {
        inner: VolatileKeyStore,
        fail_before: AtomicBool,
        fail_after: AtomicBool,
        calls: AtomicUsize,
        barrier: Mutex<Option<Arc<Barrier>>>,
    }
    impl Default for FailingStore {
        fn default() -> Self {
            Self {
                inner: VolatileKeyStore::default(),
                fail_before: AtomicBool::new(false),
                fail_after: AtomicBool::new(false),
                calls: AtomicUsize::new(0),
                barrier: Mutex::new(None),
            }
        }
    }
    impl KeyStore for FailingStore {
        fn create(&self) -> Result<(String, String)> {
            self.inner.create()
        }
        fn public(&self, handle: &str) -> Result<String> {
            self.inner.public(handle)
        }
        fn sign(&self, handle: &str, data: &[u8]) -> Result<Vec<u8>> {
            self.inner.sign(handle, data)
        }
        fn delete(&self, handle: &str) -> Result<()> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            if let Some(barrier) = self.barrier.lock().unwrap().clone() {
                barrier.wait();
                barrier.wait();
            }
            if self.fail_before.swap(false, Ordering::SeqCst) {
                return Err("key_unavailable");
            }
            self.inner.delete(handle)?;
            if self.fail_after.swap(false, Ordering::SeqCst) {
                return Err("reply_lost_after_delete");
            }
            Ok(())
        }
    }
    struct Fixture {
        dir: PathBuf,
        hosts: Arc<Hosts>,
        state: Arc<PairingState>,
        flow: Arc<Mutex<RemoteFlow>>,
        keys: Arc<FailingStore>,
        id: String,
        handle: String,
        target: Target,
    }
    impl Fixture {
        fn new() -> Self {
            let dir =
                std::env::temp_dir().join(format!("key-cleanup-{}", random_public_id().unwrap()));
            let hosts = Arc::new(Hosts::default());
            hosts.init(dir.clone()).unwrap();
            let keys = Arc::new(FailingStore::default());
            let (_, host_key) = VolatileKeyStore::default().create().unwrap();
            let target = Target {
                host: "fixture.invalid".into(),
                port: 22,
                username: "fixture".into(),
                expected_host_key: host_key,
                socket_path: "/tmp/root/herdr/sessions/work/herdr.sock".into(),
                herdr_path: "/usr/bin/herdr".into(),
                session: "work".into(),
            };
            let pairing =
                crate::create_offline_pair(keys.clone(), &target.config(), "Fixture phone", 100)
                    .unwrap();
            let handle = pairing.local_handle().to_string();
            let host = hosts.save(None, "fixture", target.clone(), None).unwrap();
            hosts
                .attach_pending(
                    &host.id,
                    &target,
                    pairing.pending_reference(&target.config()).unwrap(),
                )
                .unwrap();
            let state = Arc::new(PairingState::new(keys.clone()));
            *state.current.lock().unwrap() = Some(pairing);
            Self {
                dir,
                hosts,
                state,
                flow: Arc::new(Mutex::new(RemoteFlow::default())),
                keys,
                id: host.id,
                handle,
                target,
            }
        }
        fn pending(&self) {
            let record = self.hosts.get(&self.id).unwrap();
            assert!(record.key_deletion_pending);
            assert!(!record.enabled);
            assert_eq!(record.pairing.unwrap().handle, self.handle);
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }
    #[test]
    fn failed_remove_keeps_exact_disabled_reference_and_explicit_retry_after_reopen_finishes() {
        let fixture = Fixture::new();
        fixture.keys.fail_before.store(true, Ordering::SeqCst);
        assert!(
            matches!(remove_host(&fixture.state,&fixture.hosts,&fixture.flow,&fixture.id),Err(e)if e=="device_key_delete_unconfirmed")
        );
        fixture.pending();
        assert!(fixture.keys.public(&fixture.handle).is_ok());
        let raw = std::fs::read(fixture.dir.join("hosts.json")).unwrap();
        assert!(
            String::from_utf8(raw.clone())
                .unwrap()
                .contains("keyDeletionPending")
        );
        let reopened_dir = fixture.dir.with_extension("reopen");
        std::fs::create_dir(&reopened_dir).unwrap();
        std::fs::write(reopened_dir.join("hosts.json"), raw).unwrap();
        let reopened = Hosts::default();
        reopened.init(reopened_dir.clone()).unwrap();
        let state = PairingState::new(fixture.keys.clone());
        let flow = Mutex::new(RemoteFlow::default());
        assert!(reopened.get(&fixture.id).unwrap().key_deletion_pending);
        remove_host(&state, &reopened, &flow, &fixture.id).unwrap();
        assert!(reopened.get(&fixture.id).is_err());
        assert!(fixture.keys.public(&fixture.handle).is_err());
        assert_eq!(fixture.keys.calls.load(Ordering::SeqCst), 2);
        drop(reopened);
        std::fs::remove_dir_all(reopened_dir).unwrap();
    }
    #[test]
    fn reset_failure_preserves_current_and_durable_reference_and_unknown_delete_is_not_replayed() {
        let fixture = Fixture::new();
        fixture.keys.fail_after.store(true, Ordering::SeqCst);
        assert!(reset_current(&fixture.state, &fixture.hosts, &fixture.flow).is_err());
        fixture.pending();
        assert!(fixture.state.current.lock().unwrap().is_some());
        assert!(fixture.keys.public(&fixture.handle).is_err());
        assert_eq!(fixture.keys.calls.load(Ordering::SeqCst), 1);
        reset_current(&fixture.state, &fixture.hosts, &fixture.flow).unwrap();
        let host = fixture.hosts.get(&fixture.id).unwrap();
        assert!(!host.key_deletion_pending);
        assert!(!host.enabled);
        assert!(host.pairing.is_none());
        assert!(fixture.state.current.lock().unwrap().is_none());
        assert_eq!(fixture.keys.calls.load(Ordering::SeqCst), 2);
    }
    #[test]
    fn reset_failure_reopens_with_identity_only_intent_and_retry_keeps_public_host() {
        let fixture = Fixture::new();
        fixture.keys.fail_before.store(true, Ordering::SeqCst);
        assert!(reset_current(&fixture.state, &fixture.hosts, &fixture.flow).is_err());
        let before = fixture.hosts.get(&fixture.id).unwrap();
        assert!(before.key_cleanup_mode == Some(KeyCleanupMode::Identity));
        let calls = fixture.keys.calls.load(Ordering::SeqCst);
        assert!(
            matches!(remove_host(&fixture.state,&fixture.hosts,&fixture.flow,&fixture.id),Err(e)if e=="host_key_cleanup_intent_changed")
        );
        assert_eq!(fixture.keys.calls.load(Ordering::SeqCst), calls);
        let directory = fixture.dir.with_extension("identity-reopen");
        std::fs::create_dir(&directory).unwrap();
        std::fs::copy(fixture.dir.join("hosts.json"), directory.join("hosts.json")).unwrap();
        let reopened = Hosts::default();
        reopened.init(directory.clone()).unwrap();
        let state = PairingState::new(fixture.keys.clone());
        let flow = Mutex::new(RemoteFlow::default());
        let reply = retry_cleanup(&state, &reopened, &flow, &fixture.id).unwrap();
        assert!(!reply.host_removed);
        assert!(reply.mode == KeyCleanupMode::Identity);
        let after = reopened.get(&fixture.id).unwrap();
        assert!(after.pairing.is_none());
        assert!(!after.enabled);
        assert!(!after.key_deletion_pending);
        assert!(after.key_cleanup_mode.is_none());
        assert!(before.target == after.target);
        assert_eq!(before.name, after.name);
        assert_eq!(before.network_profile_id, after.network_profile_id);
        drop(reopened);
        std::fs::remove_dir_all(directory).unwrap();
    }
    #[test]
    fn pending_cleanup_denies_connection_restore_reenable_creation_and_migration() {
        let fixture = Fixture::new();
        let old = fixture.hosts.get(&fixture.id).unwrap();
        let ticket = fixture
            .hosts
            .prepare_key_cleanup(&fixture.id, &fixture.handle, KeyCleanupMode::Host)
            .unwrap();
        assert!(fixture.hosts.route(&old).is_err());
        assert!(fixture.hosts.route(&ticket).is_err());
        assert!(fixture.hosts.update(&fixture.id, None, Some(true)).is_err());
        assert!(
            fixture
                .hosts
                .save(None, "replacement", fixture.target.clone(), None)
                .is_err()
        );
        assert!(
            fixture
                .hosts
                .save(Some(&fixture.id), "overwrite", fixture.target.clone(), None)
                .is_err()
        );
        assert!(fixture.hosts.clear_handle(&fixture.handle).is_err());
        assert!(fixture.hosts.remove(&fixture.id).is_err());
        assert!(
            fixture
                .hosts
                .export_portable(&[fixture.id.clone()])
                .is_err()
        );
        assert!(
            fixture
                .hosts
                .export_v2(&[fixture.id.clone()], &[], false)
                .is_err()
        );
        let portable = PortableTarget::from(&fixture.target);
        let archive = Archive {
            version: 1,
            hosts: vec![PortableHost {
                label: "replacement".into(),
                provider: Provider::Direct,
                target: portable.clone(),
            }],
        };
        let plan = fixture.hosts.preview_import(&archive).unwrap();
        let choice = ImportChoice {
            index: 0,
            action: ImportAction::Replace,
            replace_ids: vec![fixture.id.clone()],
        };
        assert!(
            fixture
                .hosts
                .apply_import_with(&archive, &plan.revision, &[choice], |_| panic!(
                    "must not stop before rejection"
                ))
                .is_err()
        );
        let archive = ArchiveV2 {
            version: 2,
            hosts: vec![PortableHostV2 {
                label: "replacement".into(),
                provider: Provider::Direct,
                target: portable,
                network_key: None,
                requires_network_binding: false,
            }],
            networks: vec![],
            preferences: None,
        };
        let plan = fixture.hosts.preview_v2(&archive).unwrap();
        let choice = ImportChoice {
            index: 0,
            action: ImportAction::Replace,
            replace_ids: vec![fixture.id.clone()],
        };
        assert!(
            fixture
                .hosts
                .apply_v2(&archive, &plan.revision, &[choice], &[], false, |_| panic!(
                    "must not stop before rejection"
                ))
                .is_err()
        );
        fixture.pending();
    }
    #[test]
    fn cleanup_ticket_cas_retains_reference_after_native_success_and_concurrent_catalog_edit() {
        let fixture = Fixture::new();
        let ticket = fixture
            .hosts
            .prepare_key_cleanup(&fixture.id, &fixture.handle, KeyCleanupMode::Host)
            .unwrap();
        fixture.keys.delete(&fixture.handle).unwrap();
        fixture
            .hosts
            .update(&fixture.id, Some("renamed"), None)
            .unwrap();
        assert!(fixture.hosts.finish_key_cleanup(&ticket).is_err());
        fixture.pending();
        remove_host(&fixture.state, &fixture.hosts, &fixture.flow, &fixture.id).unwrap();
        assert!(fixture.hosts.get(&fixture.id).is_err());
    }
    #[test]
    fn native_success_then_storage_failure_keeps_ticket_until_explicit_retry() {
        let fixture = Fixture::new();
        let ticket = fixture
            .hosts
            .prepare_key_cleanup(&fixture.id, &fixture.handle, KeyCleanupMode::Host)
            .unwrap();
        fixture.keys.delete(&fixture.handle).unwrap();
        let path = fixture.dir.join("hosts.json");
        let saved = fixture.dir.join("pending-hosts.json");
        std::fs::rename(&path, &saved).unwrap();
        std::fs::create_dir(&path).unwrap();
        assert!(fixture.hosts.finish_key_cleanup(&ticket).is_err());
        fixture.pending();
        assert_eq!(fixture.keys.calls.load(Ordering::SeqCst), 1);
        std::fs::remove_dir(&path).unwrap();
        std::fs::rename(&saved, &path).unwrap();
        let persisted: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        assert_eq!(persisted["hosts"][0]["keyDeletionPending"], true);
        remove_host(&fixture.state, &fixture.hosts, &fixture.flow, &fixture.id).unwrap();
        assert_eq!(fixture.keys.calls.load(Ordering::SeqCst), 2);
        assert!(fixture.hosts.get(&fixture.id).is_err());
    }
    #[test]
    fn legacy_records_default_to_no_cleanup_and_invalid_pending_record_is_rejected() {
        let fixture = Fixture::new();
        let path = fixture.dir.join("hosts.json");
        let mut disk: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        assert!(disk["hosts"][0].get("keyDeletionPending").is_none());
        assert!(!fixture.hosts.get(&fixture.id).unwrap().key_deletion_pending);
        let bad_dir = fixture.dir.with_extension("bad");
        std::fs::create_dir(&bad_dir).unwrap();
        disk["hosts"][0]["keyDeletionPending"] = serde_json::json!(true);
        disk["hosts"][0]["keyCleanupMode"] = serde_json::json!("identity");
        std::fs::write(
            bad_dir.join("hosts.json"),
            serde_json::to_vec(&disk).unwrap(),
        )
        .unwrap();
        assert!(Hosts::default().init(bad_dir.clone()).is_err());
        std::fs::remove_dir_all(bad_dir).unwrap();
    }
    #[test]
    fn concurrent_explicit_delete_is_busy_and_does_not_call_native_twice() {
        let fixture = Fixture::new();
        let barrier = Arc::new(Barrier::new(2));
        *fixture.keys.barrier.lock().unwrap() = Some(barrier.clone());
        let (state, hosts, flow, id) = (
            fixture.state.clone(),
            fixture.hosts.clone(),
            fixture.flow.clone(),
            fixture.id.clone(),
        );
        let worker = std::thread::spawn(move || {
            remove_host(&state, &hosts, &flow, &id).map(|r| r.key_deleted)
        });
        barrier.wait();
        assert!(
            matches!(remove_host(&fixture.state,&fixture.hosts,&fixture.flow,&fixture.id),Err(e)if e=="pairing_busy")
        );
        assert_eq!(fixture.keys.calls.load(Ordering::SeqCst), 1);
        barrier.wait();
        assert!(worker.join().unwrap().unwrap());
    }
}
