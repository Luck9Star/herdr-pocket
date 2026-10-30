use std::{collections::HashMap, sync::{Arc, Mutex}};
use herdr_probe_core::{Binding, CreditStream};
use herdr_readonly_transport::{AttemptGate, Audit, FullSnapshot, RemoteConfig};
use serde::Serialize;
use tauri::{ipc::{Channel, Response}, State};

const CHUNK: &[u8] = include_bytes!("../../../shared/load-chunk.txt");
#[derive(Default)]
struct Streams { next: u64, items: HashMap<u64, CreditStream> }

#[tauri::command]
fn fixture_begin(target: String, generation: u64, epoch: u64, state: State<'_, Mutex<Streams>>) -> Result<u64, String> {
    if target != "a" && target != "b" { return Err("unknown fixture target".into()); }
    let mut state = state.lock().map_err(|_| "stream lock failed")?;
    if state.items.len() >= 2 { return Err("at most two fixture streams".into()); }
    state.next += 1;
    let lease = state.next;
    state.items.insert(lease, CreditStream::new(Binding { target, generation, epoch }, 65536));
    Ok(lease)
}
#[tauri::command]
fn fixture_next(lease: u64, on_chunk: Channel<Response>, state: State<'_, Mutex<Streams>>) -> Result<usize, String> {
    let mut state=state.lock().map_err(|_| "stream lock failed")?;
    let stream=state.items.get_mut(&lease).ok_or("stale lease")?;
    stream.reserve(CHUNK.len()).map_err(str::to_string)?;
    if let Err(e)=on_chunk.send(Response::new(CHUNK.to_vec())) { stream.cancel(); return Err(e.to_string()); }
    Ok(CHUNK.len())
}
#[tauri::command]
fn fixture_ack(lease: u64, bytes: usize, state: State<'_, Mutex<Streams>>) -> Result<(), String> {
    let mut state=state.lock().map_err(|_| "stream lock failed")?;
    state.items.get_mut(&lease).ok_or("stale lease")?.acknowledge(bytes).map_err(str::to_string)
}
#[tauri::command]
fn fixture_cancel(lease: u64, state: State<'_, Mutex<Streams>>) -> Result<(), String> {
    let mut state=state.lock().map_err(|_| "stream lock failed")?;
    if let Some(mut stream)=state.items.remove(&lease) { stream.cancel(); }
    Ok(())
}

#[derive(Serialize, Clone)]
struct RemoteProgress { generation:u64, stage:&'static str }
#[derive(Serialize)]
struct RemoteReply { generation:u64, snapshot:FullSnapshot }
#[tauri::command]
async fn remote_read_once(config:RemoteConfig,on_event:Channel<RemoteProgress>,state:State<'_,Mutex<AttemptGate>>)->Result<RemoteReply,String> {
    let (generation,cancel)=state.lock().map_err(|_|"state_unavailable")?.begin().map_err(str::to_string)?;
    let progress_cancel=cancel.clone();
    let result=herdr_readonly_transport::read_once(config,cancel,Arc::new(Audit::default()),|stage| {
        if on_event.send(RemoteProgress{generation,stage}).is_err(){progress_cancel.cancel();}
    }).await;
    if !state.lock().map_err(|_|"state_unavailable")?.finish(generation){return Err("cancelled".into());}
    result.map(|snapshot|RemoteReply{generation,snapshot}).map_err(str::to_string)
}
#[tauri::command]
fn remote_cancel(state:State<'_,Mutex<AttemptGate>>)->Result<(),String> {
    state.lock().map_err(|_|"state_unavailable")?.cancel(); Ok(())
}
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Mutex::new(Streams::default()))
        .manage(Mutex::new(AttemptGate::default()))
        .invoke_handler(tauri::generate_handler![fixture_begin,fixture_next,fixture_ack,fixture_cancel,remote_read_once,remote_cancel])
        .run(tauri::generate_context!())
        .expect("Tauri probe startup failed");
}
