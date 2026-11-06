use super::{PairingState, RemoteFlow};
use crate::hosts::{Hosts, ImportChoice, ImportPlanV2, ImportResult};
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
use tauri::State;
use tokio::sync::Semaphore;

struct Pending {
    ticket: String,
    revision: String,
    archive: ArchiveV2,
    created: Instant,
    active: Option<(u64, String)>,
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
}

fn stop_replaced_host(
    flow: &mut RemoteFlow,
    gate: &mut AttemptGate,
    reviewed: &Option<(u64, String)>,
    ids: &[String],
) -> Result<(), String> {
    if let Some((owner, id)) = flow.owner.zip(flow.host_id.as_ref()) {
        if ids.contains(id) {
            if reviewed.as_ref() != Some(&(owner, id.clone())) {
                return Err("transfer_active_changed".into());
            }
            flow.cancel(owner, gate);
        }
    }
    Ok(())
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
    let active = flow.owner.zip(flow.host_id.clone());
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
    });
    Ok(Preview {
        ticket,
        plan,
        active_host_id: active.map(|(_, id)| id),
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
pub fn config_apply(
    ticket: String,
    choices: Vec<ImportChoice>,
    selected_networks: Vec<String>,
    apply_preferences: bool,
    transfers: State<'_, Transfers>,
    hosts: State<'_, Hosts>,
    flow: State<'_, Arc<Mutex<RemoteFlow>>>,
    gate: State<'_, Mutex<AttemptGate>>,
    pairing: State<'_, PairingState>,
    network_ops: State<'_, crate::network_identity::Operations>,
) -> Result<ImportResult, String> {
    let _network_lease = network_ops.enter()?;
    let _lease = pairing.enter()?;
    let mut flow = flow.lock().map_err(|_| "state_unavailable")?;
    let mut gate = gate.lock().map_err(|_| "state_unavailable")?;
    let mut current = pairing.current.lock().map_err(|_| "state_unavailable")?;
    let pending = {
        let mut slot = transfers
            .pending
            .lock()
            .map_err(|_| "transfer_unavailable")?;
        if slot.as_ref().is_none_or(|p| p.ticket != ticket) {
            return Err("transfer_stale_plan".into());
        }
        slot.take().ok_or("transfer_stale_plan")?
    };
    if pending.created.elapsed() > Duration::from_secs(900) {
        return Err("transfer_stale_plan".into());
    }
    hosts.apply_v2(&pending.archive, &pending.revision, &choices, &selected_networks, apply_preferences, |replaced| {
        let ids: Vec<_> = replaced.iter().map(|record| record.id.clone()).collect();
        stop_replaced_host(&mut flow, &mut gate, &pending.active, &ids)?;
        if current.as_ref().is_some_and(|identity| {
            replaced.iter().any(|record| {
                record
                    .pairing
                    .as_ref()
                    .is_some_and(|p| p.handle == identity.local_handle())
            })
        }) {
            *current = None;
            pairing.restore_required.store(true, Ordering::SeqCst);
        }
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn import_stops_only_the_reviewed_connection_and_preserves_other_hosts() {
        let mut flow = RemoteFlow::default();
        let mut gate = AttemptGate::default();
        let (generation, cancel) = flow.begin(1, &mut gate).unwrap();
        flow.host_id = Some("one".into());
        stop_replaced_host(&mut flow, &mut gate, &None, &["two".into()]).unwrap();
        assert!(!cancel.is_cancelled());
        assert_eq!(
            stop_replaced_host(&mut flow, &mut gate, &None, &["one".into()]),
            Err("transfer_active_changed".into())
        );
        assert!(!cancel.is_cancelled());
        let reviewed = Some((1, "one".into()));
        stop_replaced_host(&mut flow, &mut gate, &reviewed, &["one".into()]).unwrap();
        assert!(cancel.is_cancelled());
        flow.finish(1, generation, &mut gate);
        let (_, reopened) = flow.begin(2, &mut gate).unwrap();
        flow.host_id = Some("one".into());
        assert!(stop_replaced_host(&mut flow, &mut gate, &reviewed, &["one".into()]).is_err());
        assert!(!reopened.is_cancelled());
    }
}
