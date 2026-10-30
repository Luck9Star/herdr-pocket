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
#[derive(Default)]
struct RemoteFlow {
    owner: Option<u64>,
    cancelled_through: u64,
    select: Option<(u64, tokio::sync::oneshot::Sender<String>)>,
    ack: Option<(u64, u64, tokio::sync::oneshot::Sender<()>)>,
}
impl RemoteFlow {
    fn begin(&mut self, client_generation:u64, gate:&mut AttemptGate)->Result<(u64,herdr_readonly_transport::Cancellation), &'static str> {
        if client_generation == 0 || client_generation <= self.cancelled_through { return Err("cancelled"); }
        let attempt=gate.begin()?;
        self.owner=Some(client_generation);
        Ok(attempt)
    }
    fn cancel(&mut self, client_generation:u64, gate:&mut AttemptGate) {
        self.cancelled_through=self.cancelled_through.max(client_generation);
        if self.owner==Some(client_generation) { gate.cancel(); }
    }
    fn finish(&mut self, client_generation:u64, generation:u64, gate:&mut AttemptGate)->bool {
        if self.owner!=Some(client_generation) { return false; }
        self.select=None; self.ack=None; self.owner=None;
        gate.finish(generation)
    }
}
#[cfg(test)]
mod remote_flow_tests {
    use super::*;
    #[test]
    fn delayed_cancel_and_precancel_cannot_affect_another_attempt() {
        let mut f=RemoteFlow::default(); let mut gate=AttemptGate::default();
        f.cancel(1,&mut gate); assert!(f.begin(1,&mut gate).is_err());
        let (g2,c2)=f.begin(2,&mut gate).unwrap(); f.cancel(1,&mut gate);
        assert!(!c2.is_cancelled()); assert!(f.finish(2,g2,&mut gate));
        let (g3,c3)=f.begin(3,&mut gate).unwrap(); f.cancel(2,&mut gate);
        assert!(!c3.is_cancelled()); f.cancel(3,&mut gate);
        assert!(c3.is_cancelled()); assert!(!f.finish(3,g3,&mut gate));
    }
}
#[derive(Serialize, Clone)]
#[serde(tag="kind", rename_all="snake_case")]
enum ObserveEvent {
    Stage { generation:u64, stage:&'static str },
    Dashboard { generation:u64, panes:Vec<herdr_readonly_transport::Pane> },
    Frame { generation:u64, frame:herdr_readonly_transport::StreamFrame },
}
#[tauri::command]
async fn remote_observe(config:RemoteConfig,client_generation:u64,on_event:Channel<ObserveEvent>,state:State<'_,Mutex<AttemptGate>>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let (generation,cancel)={ let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.begin(client_generation,&mut g).map_err(str::to_string)? };
    let progress_cancel=cancel.clone();
    let progress_channel=on_event.clone();
    let select_channel=on_event.clone();
    let frame_channel=on_event.clone();
    let select_flow=flow.inner().clone();
    let frame_flow=flow.inner().clone();
    let result=herdr_readonly_transport::observe(config,cancel,Arc::new(Audit::default()),
        move |stage| { if progress_channel.send(ObserveEvent::Stage{generation,stage}).is_err(){progress_cancel.cancel();} },
        move |panes| { let flow=select_flow.clone(); let channel=select_channel.clone(); async move {
            let (tx,rx)=tokio::sync::oneshot::channel();
            flow.lock().map_err(|_|"state_unavailable")?.select=Some((generation,tx));
            channel.send(ObserveEvent::Dashboard{generation,panes}).map_err(|_|"client_closed")?;
            rx.await.map_err(|_|"cancelled")
        }},
        move |frame| { let flow=frame_flow.clone(); let channel=frame_channel.clone(); async move {
            let seq=frame.seq; let (tx,rx)=tokio::sync::oneshot::channel();
            flow.lock().map_err(|_|"state_unavailable")?.ack=Some((generation,seq,tx));
            channel.send(ObserveEvent::Frame{generation,frame}).map_err(|_|"client_closed")?;
            rx.await.map_err(|_|"cancelled")
        }}).await;
    let accepted={ let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.finish(client_generation,generation,&mut g) };
    if !accepted {return Err("cancelled".into());}
    result.map_err(str::to_string)
}
#[tauri::command]
fn remote_select(generation:u64,pane_id:String,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if !f.select.as_ref().is_some_and(|(g,_)|*g==generation) { return Err("stale_selection".into()); }
    f.select.take().unwrap().1.send(pane_id).map_err(|_|"cancelled".into())
}
#[tauri::command]
fn remote_ack(generation:u64,seq:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if !f.ack.as_ref().is_some_and(|(g,s,_)|*g==generation && *s==seq) {return Err("stale_ack".into());}
    f.ack.take().unwrap().2.send(()).map_err(|_|"cancelled".into())
}
#[tauri::command]
fn remote_cancel(client_generation:u64,state:State<'_,Mutex<AttemptGate>>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.cancel(client_generation,&mut g); Ok(())
}
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Mutex::new(Streams::default()))
        .manage(Mutex::new(AttemptGate::default()))
        .manage(Arc::new(Mutex::new(RemoteFlow::default())))
        .invoke_handler(tauri::generate_handler![fixture_begin,fixture_next,fixture_ack,fixture_cancel,remote_read_once,remote_observe,remote_select,remote_ack,remote_cancel])
        .run(tauri::generate_context!())
        .expect("Tauri probe startup failed");
}
