use std::{collections::HashMap, sync::Mutex};
use herdr_probe_core::{Binding, CreditStream};
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
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Mutex::new(Streams::default()))
        .invoke_handler(tauri::generate_handler![fixture_begin,fixture_next,fixture_ack,fixture_cancel])
        .run(tauri::generate_context!())
        .expect("Tauri probe startup failed");
}
