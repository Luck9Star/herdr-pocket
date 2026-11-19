//! Ephemeral ordinary SSH terminals, independent of herdr pairing and helpers.
use herdr_readonly_transport::direct_shell::{
    self, HostKey, ShellConfig, ShellControl, ShellEvent,
};
use serde::Serialize;
use std::{
    collections::{HashMap, VecDeque},
    sync::{Arc, Mutex, Weak},
    time::Duration,
};
use tauri::{Manager, State, WebviewWindow, Window, WindowEvent, ipc::Channel};
use tokio::sync::watch;

type CloseResult = Result<(), &'static str>;

#[derive(PartialEq, Eq)]
enum SessionState {
    Active,
    Closing,
    WindowDestroyed,
}

struct Session {
    owner: String,
    control: ShellControl,
    state: SessionState,
    retired: watch::Receiver<Option<CloseResult>>,
}
impl Session {
    fn request_close(&mut self) {
        if self.state == SessionState::Active {
            self.state = SessionState::Closing;
        }
        self.control.close();
    }
}

struct Retired {
    id: String,
    owner: String,
    result: CloseResult,
}

#[derive(Default)]
struct Registry {
    next: u64,
    sessions: HashMap<String, Session>,
    retired: VecDeque<Retired>,
}
#[derive(Default)]
pub struct Shells(Arc<Mutex<Registry>>);
impl Drop for Registry {
    fn drop(&mut self) {
        for session in self.sessions.values_mut() {
            session.request_close();
        }
    }
}
impl Shells {
    fn reserve(&self, owner: &str, control: ShellControl) -> Result<Worker, &'static str> {
        let mut registry = self.0.lock().map_err(|_| "state_unavailable")?;
        if registry.sessions.len() >= 8 {
            return Err("shell_limit");
        }
        registry.next = registry.next.checked_add(1).ok_or("shell_limit")?;
        let id = format!("ssh-{}", registry.next);
        let (finished, retired) = watch::channel(None);
        registry.sessions.insert(
            id.clone(),
            Session {
                owner: owner.to_owned(),
                control,
                state: SessionState::Active,
                retired,
            },
        );
        Ok(Worker {
            registry: Arc::downgrade(&self.0),
            id,
            finished,
            result: Err("close_failed"),
        })
    }

    async fn close(&self, owner: &str, id: &str) -> CloseResult {
        let mut retired = {
            let mut registry = self.0.lock().map_err(|_| "state_unavailable")?;
            if let Some(session) = registry.sessions.get_mut(id).filter(|s| s.owner == owner) {
                session.request_close();
                session.retired.clone()
            } else {
                return registry
                    .retired
                    .iter()
                    .find(|session| session.id == id && session.owner == owner)
                    .ok_or("shell_stale")?
                    .result;
            }
        };
        let result =
            *tokio::time::timeout(Duration::from_secs(5), retired.wait_for(Option::is_some))
                .await
                .map_err(|_| "close_timeout")?
                .map_err(|_| "close_failed")?;
        result.ok_or("close_failed")?
    }

    fn close_window(&self, owner: &str) {
        if let Ok(mut registry) = self.0.lock() {
            for session in registry.sessions.values_mut().filter(|s| s.owner == owner) {
                session.state = SessionState::WindowDestroyed;
                session.request_close();
            }
        }
    }
}

// The worker owns the retirement notification. Dropping an interrupted worker
// rejects waiters and frees its slot rather than acknowledging a normal close.
struct Worker {
    registry: Weak<Mutex<Registry>>,
    id: String,
    finished: watch::Sender<Option<CloseResult>>,
    result: CloseResult,
}
impl Worker {
    fn send_event(
        &self,
        on_event: &Channel<Event>,
        event: ShellEvent,
        error: Option<&'static str>,
    ) -> CloseResult {
        let registry = self.registry.upgrade().ok_or("cancelled")?;
        let registry = registry.lock().map_err(|_| "cancelled")?;
        let session = registry.sessions.get(&self.id).ok_or("cancelled")?;
        // Serialize dispatch with close and window destruction. A retired SSH
        // transport can still deliver a report to its closing window.
        if session.state != SessionState::Active
            && !(session.state == SessionState::Closing && event.has_exit_report())
        {
            return Err("cancelled");
        }
        on_event
            .send(Event {
                session_id: self.id.clone(),
                event,
                error,
            })
            .map_err(|_| "cancelled")
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        if let Some(registry) = self.registry.upgrade()
            && let Ok(mut registry) = registry.lock()
            && let Some(mut session) = registry.sessions.remove(&self.id)
        {
            session.request_close();
            // Bound idempotent responses to recent, known sessions.
            if registry.retired.len() == 16 {
                registry.retired.pop_front();
            }
            registry.retired.push_back(Retired {
                id: self.id.clone(),
                owner: session.owner,
                result: self.result,
            });
        }
        self.finished.send_replace(Some(self.result));
    }
}

pub fn on_window_event(window: &Window, event: &WindowEvent) {
    if matches!(event, WindowEvent::Destroyed)
        && let Some(shells) = window.try_state::<Shells>()
    {
        shells.close_window(window.label());
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
    window: WebviewWindow,
) -> Result<String, String> {
    config.validate().map_err(str::to_string)?;
    let (control, commands) = direct_shell::shell_commands();
    let mut worker = state.reserve(window.label(), control)?;
    if window.get_webview_window(window.label()).is_none() {
        return Err("shell_stale".into());
    }
    let session_id = worker.id.clone();
    tauri::async_runtime::spawn(async move {
        let mut last_seq = 0;
        let mut exit_delivered = false;
        let result = direct_shell::run_shell(config, commands, |event| {
            last_seq = event.seq;
            let is_exit = event.kind == "exit";
            worker.send_event(&on_event, event, None)?;
            exit_delivered |= is_exit;
            Ok(())
        })
        .await;
        worker.result = match result {
            Err(error @ ("close_failed" | "close_timeout")) => Err(error),
            // Open/session errors do not prevent a confirmed local retirement.
            _ => Ok(()),
        };
        if let Err(error) = result
            && !exit_delivered
        {
            let _ = worker.send_event(
                &on_event,
                ShellEvent {
                    seq: last_seq + 1,
                    kind: "error",
                    data: None,
                    exit_status: None,
                    exit_signal: None,
                    presented_fingerprint: None,
                },
                Some(error),
            );
        }
    });
    // Reserved before spawning, so close can cancel even the first network dial.
    Ok(session_id)
}
fn control(state: &Shells, owner: &str, id: &str) -> Result<ShellControl, String> {
    state
        .0
        .lock()
        .map_err(|_| "state_unavailable")?
        .sessions
        .get(id)
        .filter(|session| session.owner == owner && session.state == SessionState::Active)
        .map(|session| session.control.clone())
        .ok_or_else(|| "shell_stale".into())
}
#[tauri::command]
pub async fn ssh_shell_write(
    session_id: String,
    bytes: Vec<u8>,
    state: State<'_, Shells>,
    window: WebviewWindow,
) -> Result<(), String> {
    control(&state, window.label(), &session_id)?
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
    window: WebviewWindow,
) -> Result<(), String> {
    control(&state, window.label(), &session_id)?
        .resize(cols, rows)
        .await
        .map_err(str::to_string)
}
#[tauri::command]
pub async fn ssh_shell_close(
    session_id: String,
    state: State<'_, Shells>,
    window: WebviewWindow,
) -> Result<(), String> {
    state
        .close(window.label(), &session_id)
        .await
        .map_err(str::to_string)
}

#[tauri::command]
pub fn ssh_shell_ack(
    session_id: String,
    seq: u64,
    state: State<'_, Shells>,
    window: WebviewWindow,
) -> Result<(), String> {
    control(&state, window.label(), &session_id)?
        .acknowledge(seq)
        .map_err(str::to_string)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        future::{Future, poll_fn},
        pin::pin,
        task::Poll,
    };

    fn shell_event(seq: u64, kind: &'static str, exit_status: Option<u32>) -> ShellEvent {
        ShellEvent {
            seq,
            kind,
            data: None,
            exit_status,
            exit_signal: None,
            presented_fingerprint: None,
        }
    }

    #[tokio::test]
    async fn closing_owner_receives_only_its_remote_exit_report_before_close_ack() {
        use tauri::ipc::InvokeResponseBody;

        let shells = Shells::default();
        let (input, commands) = direct_shell::shell_commands();
        let mut worker = shells.reserve("main", input).unwrap();
        let id = worker.id.clone();
        let (send, mut received) = tokio::sync::mpsc::unbounded_channel();
        let channel = Channel::new(move |body| {
            let InvokeResponseBody::Json(json) = body else {
                panic!("expected shell event JSON");
            };
            send.send(serde_json::from_str::<serde_json::Value>(&json).unwrap())
                .unwrap();
            Ok(())
        });
        let mut closing = pin!(shells.close("main", &id));
        assert!(
            poll_fn(|cx| Poll::Ready(closing.as_mut().poll(cx)))
                .await
                .is_pending()
        );
        assert_eq!(shells.close("other", &id).await, Err("shell_stale"));
        for kind in ["ready", "data", "exit", "host_key_change", "error"] {
            assert_eq!(
                worker.send_event(&channel, shell_event(1, kind, None), None),
                Err("cancelled"),
                "unexpected event while closing: {kind}"
            );
        }

        drop(commands);
        worker
            .send_event(&channel, shell_event(2, "exit", Some(0)), None)
            .unwrap();
        assert_eq!(
            received.try_recv().unwrap(),
            serde_json::json!({"sessionId": id, "seq": 2, "kind": "exit", "exitStatus": 0})
        );
        assert!(received.try_recv().is_err());
        assert!(
            poll_fn(|cx| Poll::Ready(closing.as_mut().poll(cx)))
                .await
                .is_pending()
        );
        worker.result = Ok(());
        drop(worker);
        assert_eq!(closing.await, Ok(()));
        assert_eq!(shells.close("main", &id).await, Ok(()));
        assert!(received.try_recv().is_err());
    }

    #[tokio::test]
    async fn concurrent_close_waits_for_one_worker_and_reuses_its_result() {
        let shells = Shells::default();
        let (input, commands) = direct_shell::shell_commands();
        let mut worker = shells.reserve("main", input.clone()).unwrap();
        let id = worker.id.clone();
        let mut first = pin!(shells.close("main", &id));
        let mut second = pin!(shells.close("main", &id));
        assert!(
            poll_fn(|cx| Poll::Ready(first.as_mut().poll(cx)))
                .await
                .is_pending()
        );
        assert!(
            poll_fn(|cx| Poll::Ready(second.as_mut().poll(cx)))
                .await
                .is_pending()
        );
        assert_eq!(input.acknowledge(1), Err("cancelled"));
        assert!(control(&shells, "main", &id).is_err());
        assert_eq!(shells.0.lock().unwrap().sessions.len(), 1);

        drop(commands);
        worker.result = Ok(());
        drop(worker);
        assert_eq!(first.await, Ok(()));
        assert_eq!(second.await, Ok(()));
        assert_eq!(shells.close("main", &id).await, Ok(()));
        assert!(shells.0.lock().unwrap().sessions.is_empty());
        assert_eq!(shells.close("main", "unknown").await, Err("shell_stale"));
    }

    #[tokio::test]
    async fn waiting_is_bounded_and_worker_failure_is_reported_to_retries() {
        let shells = Shells::default();
        let (input, _commands) = direct_shell::shell_commands();
        let worker = shells.reserve("main", input.clone()).unwrap();
        let id = worker.id.clone();
        assert_eq!(shells.close("main", &id).await, Err("close_timeout"));
        assert_eq!(input.acknowledge(1), Err("cancelled"));
        assert_eq!(shells.0.lock().unwrap().sessions.len(), 1);

        let mut retry = pin!(shells.close("main", &id));
        assert!(
            poll_fn(|cx| Poll::Ready(retry.as_mut().poll(cx)))
                .await
                .is_pending()
        );
        drop(worker); // The task ended without reporting retirement.
        assert_eq!(retry.await, Err("close_failed"));
        assert_eq!(shells.close("main", &id).await, Err("close_failed"));
        assert!(shells.0.lock().unwrap().sessions.is_empty());
    }

    #[tokio::test]
    async fn window_close_and_late_completion_are_scoped_to_their_session_owner() {
        let shells = Shells::default();
        let (input, _commands) = direct_shell::shell_commands();
        let (other_input, _other_commands) = direct_shell::shell_commands();
        let mut worker = shells.reserve("main", input.clone()).unwrap();
        let other = shells.reserve("other", other_input.clone()).unwrap();
        let id = worker.id.clone();
        assert_eq!(shells.close("other", &id).await, Err("shell_stale"));
        assert!(control(&shells, "other", &id).is_err());

        shells.close_window("main");
        assert_eq!(input.acknowledge(1), Err("cancelled"));
        assert_eq!(other_input.acknowledge(1), Err("stale_ack"));
        let (new_input, _new_commands) = direct_shell::shell_commands();
        let newer = shells.reserve("main", new_input.clone()).unwrap();
        {
            let channel = Channel::new(|_| panic!("report sent to destroyed window"));
            let mut closing = pin!(shells.close("main", &id));
            assert!(
                poll_fn(|cx| Poll::Ready(closing.as_mut().poll(cx)))
                    .await
                    .is_pending()
            );
            assert_eq!(
                worker.send_event(&channel, shell_event(2, "exit", Some(0)), None),
                Err("cancelled")
            );
            worker.result = Ok(());
            drop(worker);
            assert_eq!(closing.await, Ok(()));
        }

        assert_eq!(shells.close("main", &id).await, Ok(()));
        assert_eq!(shells.close("other", &id).await, Err("shell_stale"));
        assert!(control(&shells, "main", &newer.id).is_ok());
        assert!(control(&shells, "other", &other.id).is_ok());
        drop(shells);
        assert_eq!(new_input.acknowledge(1), Err("cancelled"));
        assert_eq!(other_input.acknowledge(1), Err("cancelled"));
    }
}
