//! Ephemeral ordinary SSH terminals, independent of herdr pairing and helpers.
use herdr_readonly_transport::direct_shell::{
    self, HostKey, ShellConfig, ShellControl, ShellEvent,
};
use serde::Serialize;
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};
use tauri::{State, ipc::Channel};

#[derive(Default)]
struct Registry {
    next: u64,
    sessions: HashMap<String, ShellControl>,
}
#[derive(Default)]
pub struct Shells(Arc<Mutex<Registry>>);
impl Drop for Registry {
    fn drop(&mut self) {
        for control in self.sessions.values() {
            control.close();
        }
    }
}
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct Event {
    session_id: String,
    #[serde(flatten)]
    event: ShellEvent,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<&'static str>,
}
#[tauri::command]
pub async fn ssh_host_key_probe(host: String, port: u16) -> Result<HostKey, String> {
    direct_shell::probe_host_key(host, port)
        .await
        .map_err(str::to_string)
}
#[tauri::command]
pub fn ssh_shell_open(
    config: ShellConfig,
    on_event: Channel<Event>,
    state: State<'_, Shells>,
) -> Result<String, String> {
    config.validate().map_err(str::to_string)?;
    let (control, commands) = direct_shell::shell_commands();
    let session_id = {
        let mut registry = state.0.lock().map_err(|_| "state_unavailable")?;
        if registry.sessions.len() >= 8 {
            return Err("shell_limit".into());
        }
        registry.next = registry.next.checked_add(1).ok_or("shell_limit")?;
        let id = format!("ssh-{}", registry.next);
        registry.sessions.insert(id.clone(), control.clone());
        id
    };
    let registry = state.0.clone();
    let id = session_id.clone();
    tauri::async_runtime::spawn(async move {
        let mut last_seq = 0;
        let result = direct_shell::run_shell(config, commands, |event| {
            last_seq = event.seq;
            if control_is_current(&registry, &id) {
                on_event
                    .send(Event {
                        session_id: id.clone(),
                        event,
                        error: None,
                    })
                    .map_err(|_| "cancelled")
            } else {
                Err("cancelled")
            }
        })
        .await;
        let current = registry
            .lock()
            .ok()
            .and_then(|mut r| r.sessions.remove(&id));
        if current.is_some() {
            if let Err(error) = result {
                let _ = on_event.send(Event {
                    session_id: id,
                    event: ShellEvent {
                        seq: last_seq + 1,
                        kind: "error",
                        data: None,
                        exit_status: None,
                    },
                    error: Some(error),
                });
            }
        }
        control.close();
    });
    // Reserved before spawning, so close can cancel even the first network dial.
    Ok(session_id)
}
fn control_is_current(registry: &Mutex<Registry>, id: &str) -> bool {
    registry.lock().is_ok_and(|r| r.sessions.contains_key(id))
}
fn control(state: &Shells, id: &str) -> Result<ShellControl, String> {
    state
        .0
        .lock()
        .map_err(|_| "state_unavailable")?
        .sessions
        .get(id)
        .cloned()
        .ok_or_else(|| "shell_stale".into())
}
#[tauri::command]
pub async fn ssh_shell_write(
    session_id: String,
    bytes: Vec<u8>,
    state: State<'_, Shells>,
) -> Result<(), String> {
    control(&state, &session_id)?
        .write(bytes)
        .await
        .map_err(str::to_string)
}
#[tauri::command]
pub async fn ssh_shell_resize(
    session_id: String,
    cols: u16,
    rows: u16,
    state: State<'_, Shells>,
) -> Result<(), String> {
    control(&state, &session_id)?
        .resize(cols, rows)
        .await
        .map_err(str::to_string)
}
#[tauri::command]
pub fn ssh_shell_close(session_id: String, state: State<'_, Shells>) -> Result<(), String> {
    if let Some(control) = state
        .0
        .lock()
        .map_err(|_| "state_unavailable")?
        .sessions
        .remove(&session_id)
    {
        control.close();
    }
    Ok(())
}

#[tauri::command]
pub fn ssh_shell_ack(session_id: String, seq: u64, state: State<'_, Shells>) -> Result<(), String> {
    control(&state, &session_id)?
        .acknowledge(seq)
        .map_err(str::to_string)
}
