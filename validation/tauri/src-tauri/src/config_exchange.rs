use super::{PairingState, RemoteFlow};
use crate::hosts::{Hosts, ImportChoice, ImportPlanV2, ImportResult, Record};
use herdr_readonly_transport::{
    AttemptGate,
    config_transfer::{self, ArchiveV2, PortableArchive},
    pairing::random_public_id,
};
use serde::Serialize;
use std::{
    sync::{Arc, Mutex, atomic::Ordering},
    time::{Duration, Instant},
};
use tauri::{State, ipc::Channel};
use tokio::sync::Semaphore;

struct Pending {
    ticket: String,
    revision: String,
    archive: ArchiveV2,
    created: Instant,
    active: Option<(u64, u64, String)>,
    active_tabs: Vec<(String,u64,u64,Option<String>)>,
}

impl Pending {
    fn apply(
        &self,
        hosts: &Hosts,
        pairing: &PairingState,
        choices: &[ImportChoice],
        selected_networks: &[String],
        apply_preferences: bool,
        before_commit: impl FnOnce(&[Record]) -> Result<(), String>,
    ) -> Result<ImportResult, String> {
        hosts.apply_v2(&self.archive, &self.revision, choices, selected_networks, apply_preferences, |replaced| {
            for record in replaced {
                if pairing.store.pending_create_handle(&record.id)?.is_some() {
                    return Err("host_key_creation_pending".into());
                }
            }
            before_commit(replaced)
        })
    }
}

pub struct Transfers {
    pending: Mutex<Option<Pending>>,
    work: Arc<Semaphore>,
}

impl Default for Transfers {
    fn default() -> Self {
        Self {
            pending: Mutex::new(None),
            work: Arc::new(Semaphore::new(1)),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Preview {
    ticket: String,
    plan: ImportPlanV2,
    active_host_id: Option<String>,
    active_host_ids: Vec<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Revoked { host_ids: Vec<String>, tabs: Vec<(String,u64,u64,Option<String>)>, legacy: Option<(u64,u64,String)> }

fn reviewed_owners(flow: &RemoteFlow, reviewed: &Option<(u64,u64,String)>, reviewed_tabs: &[(String,u64,u64,Option<String>)], ids: &[String]) -> Result<Revoked,String> {
    let affected = |entry: &&(String,u64,u64,Option<String>)| entry.3.as_ref().is_some_and(|id| ids.contains(id));
    let current = flow.tabs.owners();
    if current.iter().filter(affected).ne(reviewed_tabs.iter().filter(affected)) {return Err("transfer_active_changed".into());}
    let affected_legacy=flow.owner.zip(flow.host_id.clone()).filter(|(_,id)|ids.contains(id));
    let legacy=affected_legacy.map(|(owner,id)|flow.attempt.map(|attempt|(owner,attempt,id)).ok_or("transfer_active_changed")).transpose()?;
    if legacy.is_some() && legacy.as_ref()!=reviewed.as_ref() {return Err("transfer_active_changed".into());}
    Ok(Revoked {host_ids:ids.to_vec(), tabs:current.into_iter().filter(|entry|entry.3.as_ref().is_some_and(|id|ids.contains(id))).collect(), legacy})
}
fn stop_replaced_host(flow: &mut RemoteFlow, gate: &mut AttemptGate, reviewed: &Option<(u64,u64,String)>, reviewed_tabs: &[(String,u64,u64,Option<String>)], ids: &[String]) -> Result<Revoked,String> {
    let captured=reviewed_owners(flow,reviewed,reviewed_tabs,ids)?;
    for (tab,owner,generation,_) in &captured.tabs {flow.tabs.cancel(tab,*owner,*generation);}
    if let Some((owner,_,_))=&captured.legacy {flow.cancel(*owner,gate);}
    Ok(captured)
}
async fn wait_retired(flow:&Arc<Mutex<RemoteFlow>>, targets:&[(String,u64,u64)], legacy:Option<(u64,u64)>, timeout:Duration)->Result<(),String> {
    let deadline=Instant::now()+timeout;
    loop {
        let settled={let f=flow.lock().map_err(|_|"state_unavailable")?;f.tabs.stop_settled(targets) && legacy.is_none_or(|slot|f.owner.zip(f.attempt)!=Some(slot))};
        if settled {return Ok(());}
        if Instant::now()>=deadline {return Err("transfer_retirement_pending".into());}
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

async fn commit_after_retirement<T>(flow:&Arc<Mutex<RemoteFlow>>,targets:&[(String,u64,u64)],legacy:Option<(u64,u64)>,timeout:Duration,commit:impl FnOnce()->Result<T,String>)->Result<T,String> {
    wait_retired(flow,targets,legacy,timeout).await?;
    commit()
}

#[tauri::command]
pub async fn config_export(
    ids: Vec<String>,
    network_ids: Vec<String>,
    include_preferences: bool,
    password: String,
    transfers: State<'_, Transfers>,
    hosts: State<'_, Hosts>,
) -> Result<Vec<u8>, String> {
    let permit = transfers
        .work
        .clone()
        .try_acquire_owned()
        .map_err(|_| "transfer_busy")?;
    let archive = hosts.export_v2(&ids, &network_ids, include_preferences)?;
    tauri::async_runtime::spawn_blocking(move || {
        let _permit = permit;
        let bytes = serde_json::to_vec(&archive).map_err(|_| "transfer_invalid_schema")?;
        config_transfer::encrypt(&password, &bytes).map_err(str::to_string)
    })
    .await
    .map_err(|_| "transfer_unavailable")?
}

#[tauri::command]
pub async fn config_preview(
    bytes: Vec<u8>,
    password: String,
    transfers: State<'_, Transfers>,
    hosts: State<'_, Hosts>,
    flow: State<'_, Arc<Mutex<RemoteFlow>>>,
) -> Result<Preview, String> {
    let permit = transfers
        .work
        .clone()
        .try_acquire_owned()
        .map_err(|_| "transfer_busy")?;
    // A failed second file must not leave the previous preview available for application.
    transfers
        .pending
        .lock()
        .map_err(|_| "transfer_unavailable")?
        .take();
    let (archive, _permit) = tauri::async_runtime::spawn_blocking(move || {
        let result =
            config_transfer::decrypt(&password, &bytes).and_then(|plain| PortableArchive::parse(&plain).map(PortableArchive::into_v2));
        (result, permit)
    })
    .await
    .map_err(|_| "transfer_unavailable")?;
    let archive = archive?;
    let ticket = random_public_id().map_err(str::to_string)?;
    let flow = flow.lock().map_err(|_| "state_unavailable")?;
    let active = flow.owner.zip(flow.attempt).zip(flow.host_id.clone()).map(|((owner,attempt),id)|(owner,attempt,id));
    let active_tabs = flow.tabs.owners();
    let mut active_host_ids:Vec<String>=active_tabs.iter().filter_map(|t|t.3.clone()).collect();
    if let Some((_,_,id))=&active {active_host_ids.push(id.clone());}
    active_host_ids.sort();active_host_ids.dedup();
    let plan = hosts.preview_v2(&archive)?;
    *transfers
        .pending
        .lock()
        .map_err(|_| "transfer_unavailable")? = Some(Pending {
        ticket: ticket.clone(),
        revision: plan.revision.clone(),
        archive,
        created: Instant::now(),
        active: active.clone(),
        active_tabs,
    });
    Ok(Preview {
        ticket,
        plan,
        active_host_id: active.map(|(_, _, id)| id),
        active_host_ids,
    })
}

#[tauri::command]
pub fn config_discard(ticket: String, transfers: State<'_, Transfers>) -> Result<(), String> {
    let mut slot = transfers
        .pending
        .lock()
        .map_err(|_| "transfer_unavailable")?;
    if slot.as_ref().is_some_and(|p| p.ticket == ticket) {
        slot.take();
    }
    Ok(())
}

#[tauri::command]
pub async fn config_apply(
    ticket: String, choices: Vec<ImportChoice>, selected_networks: Vec<String>, apply_preferences: bool,
    on_revoke: Channel<Revoked>, transfers: State<'_, Transfers>, hosts: State<'_, Hosts>,
    flow: State<'_, Arc<Mutex<RemoteFlow>>>, gate: State<'_, Mutex<AttemptGate>>,
    pairing: State<'_, PairingState>, network_ops: State<'_, crate::network_identity::Operations>,
) -> Result<ImportResult, String> {
    let _network_lease = network_ops.enter()?;
    let _lease = pairing.enter()?;
    let pending = {
        let mut slot=transfers.pending.lock().map_err(|_|"transfer_unavailable")?;
        if slot.as_ref().is_none_or(|p|p.ticket!=ticket) {return Err("transfer_stale_plan".into());}
        slot.take().ok_or("transfer_stale_plan")?
    };
    if pending.created.elapsed()>Duration::from_secs(900) {return Err("transfer_stale_plan".into());}
    apply_pending(
        pending, &choices, &selected_networks, apply_preferences, &hosts, flow.inner(), &gate,
        &pairing, |reviewed| on_revoke.send(reviewed).map_err(|_| "transfer_revoke_unavailable".into()),
    ).await
}

async fn apply_pending(
    pending: Pending,
    choices: &[ImportChoice],
    selected_networks: &[String],
    apply_preferences: bool,
    hosts: &Hosts,
    flow: &Arc<Mutex<RemoteFlow>>,
    gate: &Mutex<AttemptGate>,
    pairing: &PairingState,
    on_revoke: impl FnOnce(Revoked) -> Result<(), String>,
) -> Result<ImportResult, String> {
    // Validate the entire plan and its CAS under the repository lock before revoking
    // anything. The sentinel exits before commit; no mutex is held while awaiting I/O.
    let mut captured=None;
    let result={
        let mut f=flow.lock().map_err(|_|"state_unavailable")?;
        let mut g=gate.lock().map_err(|_|"state_unavailable")?;
        pending.apply(hosts,pairing,choices,selected_networks,apply_preferences,|replaced| {
            let ids:Vec<_>=replaced.iter().map(|r|r.id.clone()).collect();
            let reviewed=reviewed_owners(&f,&pending.active,&pending.active_tabs,&ids)?;
            on_revoke(reviewed)?;
            let owners=stop_replaced_host(&mut f,&mut g,&pending.active,&pending.active_tabs,&ids)?;
            let legacy=owners.legacy.as_ref().map(|(owner,attempt,_)|(*owner,*attempt));
            captured=Some((owners,legacy));
            Err("transfer_preflight_complete".into())
        })
    };
    if !matches!(result,Err(ref error) if error=="transfer_preflight_complete") {return result;}
    let (owners,legacy)=captured.ok_or("transfer_unavailable")?;
    let targets:Vec<_>=owners.tabs.iter().map(|(id,owner,generation,_)|(id.clone(),*owner,*generation)).collect();
    commit_after_retirement(flow,&targets,legacy,Duration::from_secs(12),|| {
        // Revalidate the CAS after waiting. Reservations remain blocked by the network lease.
        let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?;
        pending.apply(hosts,pairing,choices,selected_networks,apply_preferences,|replaced| {
            if current.as_ref().is_some_and(|identity|replaced.iter().any(|r|r.pairing.as_ref().is_some_and(|p|p.handle==identity.local_handle()))) {
                *current=None;pairing.restore_required.store(true,Ordering::SeqCst);
            }
            Ok(())
        })
    }).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hosts::{ImportAction, Target};
    use herdr_readonly_transport::{
        config_transfer::{PortableHostV2, PortableTarget, Provider},
        pairing::{KeyStore, VolatileKeyStore},
    };

    #[derive(Default)]
    struct JournalKeys {
        keys: VolatileKeyStore,
        pending: Mutex<Option<(String, String, String)>>,
    }
    impl KeyStore for JournalKeys {
        fn pending_create(&self, host: &str, target: &str) -> herdr_readonly_transport::Result<Option<String>> {
            match self.pending.lock().unwrap().as_ref() {
                Some((id, expected, handle)) if id == host && expected == target => Ok(Some(handle.clone())),
                Some(_) => Err("key_creation_pending"),
                None => Ok(None),
            }
        }
        fn pending_create_handle(&self, host: &str) -> herdr_readonly_transport::Result<Option<String>> {
            Ok(self.pending.lock().unwrap().as_ref().filter(|(id, _, _)| id == host).map(|(_, _, handle)| handle.clone()))
        }
        fn clear_deleted_create(&self, handle: &str) -> herdr_readonly_transport::Result<()> {
            let mut pending = self.pending.lock().unwrap();
            if pending.as_ref().is_some_and(|(_, _, reserved)| reserved == handle) {
                pending.take();
            }
            Ok(())
        }
        fn create(&self) -> herdr_readonly_transport::Result<(String, String)> {
            self.keys.create()
        }
        fn public(&self, handle: &str) -> herdr_readonly_transport::Result<String> {
            self.keys.public(handle)
        }
        fn sign(&self, handle: &str, bytes: &[u8]) -> herdr_readonly_transport::Result<Vec<u8>> {
            self.keys.sign(handle, bytes)
        }
        fn delete(&self, handle: &str) -> herdr_readonly_transport::Result<()> {
            self.keys.delete(handle)
        }
    }

    struct RecoveryFixture {
        dir: std::path::PathBuf,
        hosts: Hosts,
        pairing: PairingState,
        keys: Arc<JournalKeys>,
        flow: Arc<Mutex<RemoteFlow>>,
        gate: Mutex<AttemptGate>,
        target: Target,
        host_id: String,
        handle: String,
    }
    impl RecoveryFixture {
        fn new() -> Self {
            let dir = std::env::temp_dir().join(random_public_id().unwrap());
            let hosts = Hosts::default();
            hosts.init(dir.clone()).unwrap();
            let keys = Arc::new(JournalKeys::default());
            let (handle, pin) = keys.create().unwrap();
            let target = Target {
                host: "fixture.invalid".into(),
                port: 22,
                username: "fixture".into(),
                expected_host_key: pin,
                socket_path: "/tmp/root/herdr/sessions/work/herdr.sock".into(),
                herdr_path: "/usr/bin/herdr".into(),
                session: "work".into(),
            };
            let host = hosts.save(None, "original", target.clone(), None).unwrap();
            *keys.pending.lock().unwrap() = Some((host.id.clone(), serde_json::to_string(&target).unwrap(), handle.clone()));
            Self {
                dir, hosts, pairing: PairingState::new(keys.clone()), keys,
                flow: Arc::default(), gate: Mutex::default(), target, host_id: host.id, handle,
            }
        }

        fn replacement(&self, host_id: &str) -> (Pending, [ImportChoice; 1]) {
            let record = self.hosts.get(host_id).unwrap();
            let archive = ArchiveV2 {
                version: 2,
                hosts: vec![PortableHostV2 {
                    label: record.name,
                    provider: Provider::Direct,
                    target: PortableTarget::from(&record.target),
                    network_key: None,
                    requires_network_binding: false,
                }],
                networks: vec![],
                preferences: None,
            };
            let revision = self.hosts.preview_v2(&archive).unwrap().revision;
            let flow = self.flow.lock().unwrap();
            let pending = Pending {
                ticket: random_public_id().unwrap(), revision, archive, created: Instant::now(),
                active: flow.owner.zip(flow.attempt).zip(flow.host_id.clone()).map(|((owner, attempt), id)| (owner, attempt, id)),
                active_tabs: flow.tabs.owners(),
            };
            (pending, [ImportChoice {index: 0, action: ImportAction::Replace, replace_ids: vec![host_id.into()]}])
        }

        async fn apply(
            &self, pending: Pending, choices: &[ImportChoice], on_revoke: impl FnOnce(Revoked) -> Result<(), String>,
        ) -> Result<ImportResult, String> {
            let _lease = self.pairing.enter()?;
            apply_pending(
                pending, choices, &[], false, &self.hosts, &self.flow, &self.gate, &self.pairing, on_revoke,
            ).await
        }
    }
    impl Drop for RecoveryFixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }

    #[tokio::test]
    async fn unattached_creation_preserves_original_until_explicit_discard() {
        for replace_after_discard in [false, true] {
            let f = RecoveryFixture::new();
            let id = &f.host_id;
            let before = std::fs::read(f.dir.join("hosts.json")).unwrap();
            let cancellation = {
                let mut flow = f.flow.lock().unwrap();
                let (generation, cancel) = flow.tabs.begin("pending", 1, Some(id.clone()), None).unwrap();
                flow.tabs.claim("pending", 1, generation).unwrap();
                cancel
            };
            let (pending, choices) = f.replacement(id);
            assert!(matches!(
                f.apply(pending, &choices, |_| panic!("must reject before notifying or stopping tabs")).await,
                Err(e) if e == "host_key_creation_pending"
            ));
            assert!(matches!(
                crate::key_cleanup::remove_host(&f.pairing, &f.hosts, &f.flow, &f.gate, id).await,
                Err(e) if e == "host_key_creation_pending"
            ));
            assert!(!cancellation.is_cancelled());
            assert_eq!(std::fs::read(f.dir.join("hosts.json")).unwrap(), before);
            assert_eq!(f.keys.pending_create_handle(id).unwrap(), Some(f.handle.clone()));
            assert!(f.keys.public(&f.handle).is_ok());

            let mut other_target = f.target.clone();
            other_target.host = "other.invalid".into();
            let other = f.hosts.save(None, "other", other_target.clone(), None).unwrap();
            let (pending, choices) = f.replacement(&other.id);
            let replaced = f.apply(pending, &choices, |revoke| {
                assert_eq!(revoke.host_ids, [other.id.clone()]);
                assert!(revoke.tabs.is_empty());
                Ok(())
            }).await.unwrap();
            let other = &replaced.added[0].id;
            let paired = crate::create_offline_pair(f.keys.clone(), &other_target.config(), "Fixture", 100).unwrap();
            let paired_handle = paired.local_handle().to_owned();
            f.hosts.attach_pending(other, &other_target, paired.pending_reference(&other_target.config()).unwrap()).unwrap();
            crate::key_cleanup::remove_host(&f.pairing, &f.hosts, &f.flow, &f.gate, other).await.unwrap();
            assert!(f.keys.public(&paired_handle).is_err());
            assert_eq!(f.keys.pending_create_handle(id).unwrap(), Some(f.handle.clone()));
            assert!(!cancellation.is_cancelled());

            crate::discard_pending_identity(id, &f.pairing, &f.hosts, &f.flow).unwrap();
            assert!(f.hosts.get(id).is_ok());
            assert_eq!(f.keys.pending_create_handle(id).unwrap(), None);
            assert_eq!(f.keys.public(&f.handle), Err("key_missing"));
            if replace_after_discard {
                let generation = f.flow.lock().unwrap().tabs.owners()[0].2;
                f.flow.lock().unwrap().tabs.finish("pending", 1, generation);
                let (pending, choices) = f.replacement(id);
                let result = f.apply(pending, &choices, |_| Ok(())).await.unwrap();
                assert_eq!(result.removed_ids, [id.clone()]);
            } else {
                crate::key_cleanup::remove_host(&f.pairing, &f.hosts, &f.flow, &f.gate, id).await.unwrap();
                assert!(cancellation.is_cancelled());
            }
            assert!(f.hosts.get(id).is_err());
        }
    }

    #[tokio::test]
    async fn final_import_cas_checks_a_journal_before_committing() {
        let f = RecoveryFixture::new();
        let journal = f.keys.pending.lock().unwrap().take().unwrap();
        let (pending, choices) = f.replacement(&f.host_id);
        let rejected = f.apply(pending, &choices, |_| {
            // Bypass the synthetic store transaction to simulate a journal found at commit.
            *f.keys.pending.lock().unwrap() = Some(journal);
            Ok(())
        }).await;
        assert!(matches!(rejected, Err(e) if e == "host_key_creation_pending"));
        assert!(f.hosts.get(&f.host_id).is_ok());
        assert_eq!(f.keys.pending_create_handle(&f.host_id).unwrap(), Some(f.handle.clone()));
    }

    #[tokio::test]
    async fn removal_cancels_only_the_original_legacy_observation_after_review() {
        let f = RecoveryFixture::new();
        let (attempt, cancel) = {
            let mut flow = f.flow.lock().unwrap();
            flow.host_id = Some(f.host_id.clone());
            flow.begin(1, &mut f.gate.lock().unwrap()).unwrap()
        };
        let remove = |id| crate::key_cleanup::remove_host(&f.pairing, &f.hosts, &f.flow, &f.gate, id);
        assert!(matches!(remove(&f.host_id).await, Err(e) if e == "host_key_creation_pending"));
        let mut other_target = f.target.clone();
        other_target.host = "other.invalid".into();
        let other = f.hosts.save(None, "other", other_target, None).unwrap();
        remove(&other.id).await.unwrap();
        assert!(!cancel.is_cancelled());

        // Permit ordinary removal after recovery and exercise the same async retirement path.
        *f.keys.pending.lock().unwrap() = None;
        let (result, ()) = tokio::join!(remove(&f.host_id), async {
            assert!(cancel.is_cancelled());
            let mut flow = f.flow.lock().unwrap();
            flow.finish(1, attempt, &mut f.gate.lock().unwrap());
        });
        result.unwrap();
        assert!(f.hosts.get(&f.host_id).is_err());
    }

    #[test]
    fn import_stops_only_the_reviewed_connection_and_preserves_other_hosts() {
        let mut flow = RemoteFlow::default();
        let mut gate = AttemptGate::default();
        let (generation, cancel) = flow.begin(1, &mut gate).unwrap();
        flow.host_id = Some("one".into());
        stop_replaced_host(&mut flow, &mut gate, &None, &[], &["two".into()]).unwrap();
        assert!(!cancel.is_cancelled());
        assert!(matches!(stop_replaced_host(&mut flow, &mut gate, &None, &[], &["one".into()]), Err(e) if e=="transfer_active_changed"));
        assert!(!cancel.is_cancelled());
        let reviewed = Some((1, generation, "one".into()));
        stop_replaced_host(&mut flow, &mut gate, &reviewed, &[], &["one".into()]).unwrap();
        assert!(cancel.is_cancelled());
        flow.finish(1, generation, &mut gate);
        let (_, reopened) = flow.begin(2, &mut gate).unwrap();
        flow.host_id = Some("one".into());
        assert!(stop_replaced_host(&mut flow, &mut gate, &reviewed, &[], &["one".into()]).is_err());
        assert!(!reopened.is_cancelled());
    }
    #[tokio::test]
    async fn import_waits_for_claimed_retirement_and_leaves_other_host_untouched() {
        let flow=Arc::new(Mutex::new(RemoteFlow::default()));let mut gate=AttemptGate::default();
        let (generation,other)={let mut f=flow.lock().unwrap();let (g,_)=f.tabs.begin("old",1,Some("host-a".into()),None).unwrap();f.tabs.claim("old",1,g).unwrap();let (_,other)=f.tabs.begin("other",1,Some("host-b".into()),None).unwrap();let reviewed=f.tabs.owners();stop_replaced_host(&mut f,&mut gate,&None,&reviewed,&["host-a".into()]).unwrap();(g,other)};
        let targets=vec![("old".into(),1,generation)];
        let committed=std::cell::Cell::new(false);
        assert_eq!(commit_after_retirement(&flow,&targets,None,Duration::from_millis(35),||{committed.set(true);Ok(())}).await,Err("transfer_retirement_pending".into()));
        assert!(!committed.get());assert!(!other.is_cancelled());
        let finishing=flow.clone();let task=tokio::spawn(async move {tokio::time::sleep(Duration::from_millis(30)).await;finishing.lock().unwrap().tabs.finish("old",1,generation);});
        assert_eq!(commit_after_retirement(&flow,&targets,None,Duration::from_secs(1),||{committed.set(true);Ok(())}).await,Ok(()));task.await.unwrap();assert!(committed.get());assert!(!other.is_cancelled());
    }
    #[test]
    fn import_rejects_reused_legacy_client_generation_with_new_attempt() {
        let mut flow=RemoteFlow::default();let mut gate=AttemptGate::default();
        let (old,_)=flow.begin(3,&mut gate).unwrap();flow.host_id=Some("host-a".into());
        let reviewed=Some((3,old,"host-a".into()));flow.finish(3,old,&mut gate);
        let (new,cancel)=flow.begin(3,&mut gate).unwrap();flow.host_id=Some("host-a".into());
        assert_ne!(old,new);
        assert!(matches!(stop_replaced_host(&mut flow,&mut gate,&reviewed,&[],&["host-a".into()]),Err(e) if e=="transfer_active_changed"));
        assert!(!cancel.is_cancelled());
    }
    #[test]
    fn import_rejects_missing_legacy_attempt_before_revocation() {
        let mut flow=RemoteFlow::default();flow.owner=Some(3);flow.host_id=Some("host-a".into());
        assert!(matches!(reviewed_owners(&flow,&Some((3,1,"host-a".into())),&[],&["host-a".into()]),Err(e) if e=="transfer_active_changed"));
    }
    #[tokio::test]
    async fn import_waits_for_legacy_connection_without_a_js_tab() {
        let flow=Arc::new(Mutex::new(RemoteFlow::default()));let mut gate=AttemptGate::default();
        let attempt={let mut f=flow.lock().unwrap();let (attempt,_)=f.begin(3,&mut gate).unwrap();f.host_id=Some("host-a".into());stop_replaced_host(&mut f,&mut gate,&Some((3,attempt,"host-a".into())),&[],&["host-a".into()]).unwrap();attempt};
        assert_eq!(wait_retired(&flow,&[],Some((3,attempt)),Duration::from_millis(30)).await,Err("transfer_retirement_pending".into()));
        flow.lock().unwrap().finish(3,attempt,&mut gate);
        assert_eq!(wait_retired(&flow,&[],Some((3,attempt)),Duration::from_millis(30)).await,Ok(()));
    }
    #[test]
    fn import_rechecks_all_reviewed_tabs_and_cancels_only_replaced_host() {
        let mut flow=RemoteFlow::default();let mut gate=AttemptGate::default();
        let (one,a)=flow.tabs.begin("one",1,Some("host-a".into()),None).unwrap();
        flow.tabs.claim("one",1,one).unwrap();
        let (two,b)=flow.tabs.begin("two",1,Some("host-b".into()),None).unwrap();
        flow.tabs.claim("two",1,two).unwrap();
        let preview=flow.tabs.owners();
        let (three,_)=flow.tabs.begin("three",1,Some("host-a".into()),None).unwrap();
        assert!(matches!(stop_replaced_host(&mut flow,&mut gate,&None,&preview,&["host-a".into()]),Err(e) if e=="transfer_active_changed"));
        assert!(!a.is_cancelled());flow.tabs.cancel("three",1,three);
        stop_replaced_host(&mut flow,&mut gate,&None,&preview,&["host-a".into()]).unwrap();
        assert!(a.is_cancelled());assert!(!b.is_cancelled());
    }

}
