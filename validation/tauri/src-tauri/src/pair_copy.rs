//! Explicit public-request copy. JavaScript supplies identifiers, never clipboard text.
use crate::{PairingState, RemoteFlow, hosts::Hosts};
use serde::Serialize;
use std::sync::{Arc, Mutex};
use tauri::State;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CopyResult {
    host_id: String,
    request_id: String,
    copied: bool,
}

#[cfg(any(target_os = "android", test))]
struct CopyPayload {
    text: String,
    request_id: String,
    issued_at: u64,
    expires_at: u64,
}

#[cfg(any(target_os = "android", test))]
fn review_request(
    pairing: &herdr_readonly_transport::pairing::Pairing,
    host: &crate::hosts::Record,
    request_id: &str,
    time: u64,
) -> Result<CopyPayload, String> {
    use herdr_readonly_transport::pairing::ReferenceStatus;
    #[derive(serde::Deserialize)]
    struct RequestTime {
        request_id: String,
        issued_at: u64,
        expires_at: u64,
    }
    let text = pairing.request_json().map_err(str::to_string)?;
    if text.is_empty() || text.len() > 2048 {
        return Err("clipboard_too_large".into());
    }
    let request: RequestTime = serde_json::from_str(&text).map_err(|_| "pairing_copy_changed")?;
    if request_id != request.request_id {
        return Err("pairing_copy_changed".into());
    }
    if request.issued_at > time || time >= request.expires_at {
        return Err("pairing_copy_expired".into());
    }
    if pairing.state != "awaiting-host" || pairing.authorization != "unknown" {
        return Err("pairing_copy_unavailable".into());
    }
    let reference = host.pairing.as_ref().ok_or("pairing_copy_changed")?;
    if !host.enabled
        || host.retired
        || reference.status != ReferenceStatus::AwaitingHost
        || reference.handle != pairing.local_handle()
        || reference.request_json != text
    {
        return Err("pairing_copy_changed".into());
    }
    // This also verifies the complete frozen target and the original device key.
    let expected = pairing
        .pending_reference(&host.target.config())
        .map_err(|_| "pairing_copy_changed")?;
    if expected.handle != reference.handle || expected.request_json != reference.request_json {
        return Err("pairing_copy_changed".into());
    }
    Ok(CopyPayload {
        text,
        request_id: request.request_id,
        issued_at: request.issued_at,
        expires_at: request.expires_at,
    })
}

#[cfg(any(target_os = "android", test))]
fn snapshot(
    state: &PairingState,
    hosts: &Hosts,
    flow: &Mutex<RemoteFlow>,
    host_id: &str,
    request_id: &str,
    time: u64,
) -> Result<CopyPayload, String> {
    if state
        .restore_required
        .load(std::sync::atomic::Ordering::SeqCst)
    {
        return Err("host_restore_required".into());
    }
    let flow = flow.lock().map_err(|_| "state_unavailable")?;
    if flow.owner.is_some() {
        return Err("connection_active".into());
    }
    let current = state.current.lock().map_err(|_| "state_unavailable")?;
    let pairing = current.as_ref().ok_or("pairing_missing")?;
    let host = hosts.get(host_id).map_err(|_| "pairing_copy_changed")?;
    review_request(pairing, &host, request_id, time)
}

#[cfg(any(target_os = "android", test))]
async fn copy_with<F, Fut>(
    state: &PairingState,
    hosts: &Hosts,
    flow: &Mutex<RemoteFlow>,
    host_id: String,
    request_id: String,
    time: u64,
    write: F,
) -> Result<CopyResult, String>
where
    F: FnOnce(CopyPayload) -> Fut,
    Fut: std::future::Future<Output = Result<(), String>>,
{
    // The atomic operation lease is Send; all std::MutexGuards die in snapshot.
    // It prevents select/reset/accept/import from replacing this identity in flight.
    let _lease = state.enter()?;
    let payload = snapshot(state, hosts, flow, &host_id, &request_id, time)?;
    let result = CopyResult {
        host_id,
        request_id: payload.request_id.clone(),
        copied: true,
    };
    write(payload).await?;
    Ok(result)
}

#[tauri::command]
pub async fn pair_copy_request(
    app: tauri::AppHandle,
    host_id: String,
    request_id: String,
    state: State<'_, PairingState>,
    hosts: State<'_, Hosts>,
    flow: State<'_, Arc<Mutex<RemoteFlow>>>,
) -> Result<CopyResult, String> {
    #[cfg(target_os = "android")]
    {
        copy_with(
            &state,
            &hosts,
            &flow,
            host_id,
            request_id,
            crate::now()?,
            |payload| async move {
                crate::clipboard::write_pairing_request(
                    app,
                    payload.text,
                    payload.issued_at,
                    payload.expires_at,
                )
                .await
            },
        )
        .await
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = (app, host_id, request_id, state, hosts, flow);
        Err("clipboard_unsupported".into())
    }
}

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
mod tests {
    use super::*;
    use crate::hosts::Target;
    use herdr_readonly_transport::pairing::{
        KeyStore, Pairing, ReferenceStatus, VolatileKeyStore, random_public_id,
    };
    use std::{
        path::PathBuf,
        sync::atomic::{AtomicUsize, Ordering},
    };

    struct Fixture {
        dir: PathBuf,
        keys: Arc<VolatileKeyStore>,
        state: PairingState,
        hosts: Hosts,
        flow: Mutex<RemoteFlow>,
        host_id: String,
        request_id: String,
    }
    impl Fixture {
        fn new() -> Self {
            let dir =
                std::env::temp_dir().join(format!("pair-copy-{}", random_public_id().unwrap()));
            let keys = Arc::new(VolatileKeyStore::default());
            let (_, host_key) = VolatileKeyStore::default().create().unwrap();
            let target = Target {
                host: "host.invalid".into(),
                port: 22,
                username: "fixture".into(),
                expected_host_key: host_key,
                socket_path: "/tmp/root/herdr/sessions/work/herdr.sock".into(),
                herdr_path: "/usr/bin/herdr".into(),
                session: "work".into(),
            };
            let p =
                crate::create_offline_pair(keys.clone(), &target.config(), "Fixture phone", 100)
                    .unwrap();
            let request_id = serde_json::from_str::<serde_json::Value>(&p.request_json().unwrap())
                .unwrap()["request_id"]
                .as_str()
                .unwrap()
                .to_string();
            let hosts = Hosts::default();
            hosts.init(dir.clone()).unwrap();
            let host = hosts.save(None, "fixture", target.clone(), None).unwrap();
            hosts
                .attach_pending(
                    &host.id,
                    &target,
                    p.pending_reference(&target.config()).unwrap(),
                )
                .unwrap();
            let state = PairingState::new(keys.clone());
            *state.current.lock().unwrap() = Some(p);
            Self {
                dir,
                keys,
                state,
                hosts,
                flow: Mutex::new(RemoteFlow::default()),
                host_id: host.id,
                request_id,
            }
        }
        fn current(&self) -> Pairing {
            self.state.current.lock().unwrap().as_ref().unwrap().clone()
        }
        fn payload(&self, time: u64) -> Result<CopyPayload, String> {
            snapshot(
                &self.state,
                &self.hosts,
                &self.flow,
                &self.host_id,
                &self.request_id,
                time,
            )
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }

    #[test]
    fn copy_is_native_original_only_and_has_exact_success_contract_without_mutex_guards_across_await()
     {
        let fixture = Fixture::new();
        let expected = fixture.current().request_json().unwrap();
        let calls = AtomicUsize::new(0);
        let owned_fixture = &fixture;
        let observed_calls = &calls;
        let future = copy_with(
            &fixture.state,
            &fixture.hosts,
            &fixture.flow,
            fixture.host_id.clone(),
            fixture.request_id.clone(),
            101,
            |payload| async move {
                assert_eq!(payload.text, expected);
                assert_eq!((payload.issued_at, payload.expires_at), (100, 700));
                assert!(owned_fixture.state.current.try_lock().is_ok());
                assert!(owned_fixture.flow.try_lock().is_ok());
                assert!(owned_fixture.state.enter().is_err());
                observed_calls.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        );
        fn require_send<T: Send>(_: &T) {}
        require_send(&future);
        let result = tauri::async_runtime::block_on(future).unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            serde_json::to_value(result).unwrap(),
            serde_json::json!({"hostId":fixture.host_id,"requestId":fixture.request_id,"copied":true})
        );
        assert!(fixture.state.enter().is_ok());
    }
    #[test]
    fn request_expiration_state_original_target_handle_and_directory_bytes_are_required() {
        let fixture = Fixture::new();
        let pairing = fixture.current();
        let host = fixture.hosts.get(&fixture.host_id).unwrap();
        assert!(fixture.payload(699).is_ok());
        for now in [99, 700, 1000] {
            assert!(matches!(fixture.payload(now),Err(e) if e=="pairing_copy_expired"));
        }
        assert!(review_request(&pairing, &host, &"b".repeat(32), 101).is_err());
        for state in [
            "cancelled",
            "expired",
            "revoked",
            "authorized-unverified",
            "connecting",
            "paired",
        ] {
            let mut changed = pairing.clone();
            changed.state = state;
            assert!(
                matches!(review_request(&changed,&host,&fixture.request_id,101),Err(e) if e=="pairing_copy_unavailable")
            );
        }
        let mut revoked = pairing.clone();
        revoked.authorization = "revoked";
        assert!(review_request(&revoked, &host, &fixture.request_id, 101).is_err());
        for change in 0..6 {
            let mut record = host.clone();
            match change {
                0 => record.target.host = "other.invalid".into(),
                1 => record.pairing.as_mut().unwrap().handle = "another-handle".into(),
                2 => record.pairing.as_mut().unwrap().request_json.push(' '),
                3 => record.pairing.as_mut().unwrap().status = ReferenceStatus::Revoked,
                4 => record.enabled = false,
                _ => {
                    record.retired = true;
                    record.enabled = false;
                }
            }
            assert!(review_request(&pairing, &record, &fixture.request_id, 101).is_err());
        }
        fixture.keys.delete(pairing.local_handle()).unwrap();
        assert!(fixture.payload(101).is_err());
    }
    #[test]
    fn changed_selected_host_restore_and_write_failures_never_retry() {
        let fixture = Fixture::new();
        assert!(
            snapshot(
                &fixture.state,
                &fixture.hosts,
                &fixture.flow,
                &"b".repeat(32),
                &fixture.request_id,
                101
            )
            .is_err()
        );
        fixture.state.restore_required.store(true, Ordering::SeqCst);
        assert!(matches!(fixture.payload(101),Err(e) if e=="host_restore_required"));
        fixture
            .state
            .restore_required
            .store(false, Ordering::SeqCst);
        fixture.flow.lock().unwrap().owner = Some(1);
        assert!(matches!(fixture.payload(101),Err(e) if e=="connection_active"));
        fixture.flow.lock().unwrap().owner = None;
        let calls = AtomicUsize::new(0);
        let result = tauri::async_runtime::block_on(copy_with(
            &fixture.state,
            &fixture.hosts,
            &fixture.flow,
            fixture.host_id.clone(),
            fixture.request_id.clone(),
            101,
            |_| async {
                calls.fetch_add(1, Ordering::SeqCst);
                Err("clipboard_unfocused".into())
            },
        ));
        assert!(matches!(result,Err(e) if e=="clipboard_unfocused"));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let result = tauri::async_runtime::block_on(copy_with(
            &fixture.state,
            &fixture.hosts,
            &fixture.flow,
            fixture.host_id.clone(),
            fixture.request_id.clone(),
            700,
            |_| async {
                calls.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        ));
        assert!(result.is_err());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}
