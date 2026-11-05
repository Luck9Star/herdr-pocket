use std::{collections::HashMap, sync::{Arc, Mutex, atomic::{AtomicBool,Ordering}}};
use herdr_probe_core::{Binding, CreditStream};
use herdr_readonly_transport::{AttemptGate, Audit, FullSnapshot, RemoteConfig};
use serde::Serialize;
use herdr_readonly_transport::pairing::{KeyStore, Pairing, ReferenceStatus};
use tauri::{ipc::{Channel, Response}, Manager, State};

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
async fn remote_read_once(config:RemoteConfig,on_event:Channel<RemoteProgress>,state:State<'_,Mutex<AttemptGate>>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,pairing:State<'_,PairingState>)->Result<RemoteReply,String> {
    const LEGACY_OWNER:u64=u64::MAX;
    let (generation,cancel)={let mut f=flow.lock().map_err(|_|"state_unavailable")?; if f.owner.is_some() || pairing.restore_required.load(Ordering::SeqCst) {return Err("host_restore_required".into());} let mut g=state.lock().map_err(|_|"state_unavailable")?;let attempt=g.begin().map_err(str::to_string)?;f.owner=Some(LEGACY_OWNER);attempt};
    let progress_cancel=cancel.clone();
    let result=herdr_readonly_transport::read_once(config,cancel,Arc::new(Audit::default()),|stage| {
        if on_event.send(RemoteProgress{generation,stage}).is_err(){progress_cancel.cancel();}
    }).await;
    let accepted={let mut f=flow.lock().map_err(|_|"state_unavailable")?;let mut g=state.lock().map_err(|_|"state_unavailable")?;f.finish(LEGACY_OWNER,generation,&mut g)};
    if !accepted{return Err("cancelled".into());}
    result.map(|snapshot|RemoteReply{generation,snapshot}).map_err(str::to_string)
}
mod hosts;
use hosts::{Hosts, Target};
#[tauri::command]
async fn host_init(app:tauri::AppHandle,hosts:State<'_,Hosts>)->Result<(),String> {
    #[cfg(target_os="android")]
    let root=android_keys::no_backup_directory(&app).map_err(str::to_string)?;
    #[cfg(not(target_os="android"))]
    let root=app.path().app_local_data_dir().map_err(|_|"host_storage_unavailable")?;
    hosts.init(root.join("host-records-v1"))
}
#[tauri::command]
fn host_list(hosts:State<'_,Hosts>)->Result<Vec<hosts::View>,String>{hosts.list()}
#[tauri::command]
fn host_save(id:Option<String>,name:String,config:RemoteConfig,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<hosts::View,String>{
    let _lease=pairing.enter()?; let f=flow.lock().map_err(|_|"state_unavailable")?;
    if f.owner.is_some(){return Err("connection_active".into());}
    config.validate_pair_target().map_err(str::to_string)?;
    let current=pairing.current.lock().map_err(|_|"state_unavailable")?;
    let reference=match current.as_ref() {Some(p) if p.authorization=="authorized"=>Some(p.persistable(&config).map_err(str::to_string)?),_=>None};
    hosts.save(id.as_deref(),&name,Target::from_config(&config),reference)
}
#[tauri::command]
fn host_new(hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String>{
    let _lease=pairing.enter()?;let f=flow.lock().map_err(|_|"state_unavailable")?;if f.owner.is_some(){return Err("connection_active".into());}
    let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?;
    if let Some(p)=current.as_ref(){if !hosts.contains_handle(p.local_handle())? {return Err("unsaved_pairing".into());}}
    *current=None;pairing.restore_required.store(false,Ordering::SeqCst);Ok(())
}
#[tauri::command]
fn host_select(id:String,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<hosts::View,String>{
    let _lease=pairing.enter()?;let f=flow.lock().map_err(|_|"state_unavailable")?;if f.owner.is_some(){return Err("connection_active".into());}
    let host=hosts.get(&id)?;if !host.enabled{return Err("host_disabled".into());}
    let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?;
    if let Some(p)=current.as_ref(){if !hosts.contains_handle(p.local_handle())? {return Err("unsaved_pairing".into());}}
    *current=None;pairing.restore_required.store(host.pairing.is_some(),Ordering::SeqCst);host.view()
}
#[tauri::command]
async fn host_restore(id:String,reviewed:bool,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<PairingView,String>{
    let _lease=pairing.enter()?;let f=flow.lock().map_err(|_|"state_unavailable")?;if f.owner.is_some(){return Err("connection_active".into());}
    let host=hosts.get(&id)?;if !host.enabled{return Err("host_disabled".into());}
    let reference=host.pairing.as_ref().ok_or("host_has_no_device_key")?;
    let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?;
    if let Some(p)=current.as_ref(){if !hosts.contains_handle(p.local_handle())? {return Err("unsaved_pairing".into());}}
    let p=if reference.status==ReferenceStatus::Authorized {Pairing::restore(pairing.store.clone(),reference,&host.target.config(),reviewed)} else {Pairing::restore_pending(pairing.store.clone(),reference,&host.target.config(),reviewed,now()?)}.map_err(str::to_string)?;
    let view=pairing_view(&p)?;*current=Some(p);pairing.restore_required.store(false,Ordering::SeqCst);Ok(view)
}
#[tauri::command]
fn host_update(id:String,name:Option<String>,enabled:Option<bool>,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String>{
    let _lease=pairing.enter()?;let f=flow.lock().map_err(|_|"state_unavailable")?;if f.owner.is_some(){return Err("connection_active".into());}
    let host=hosts.get(&id)?; let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?; hosts.update(&id,name.as_deref(),enabled)?;
    if enabled==Some(false) && current.as_ref().zip(host.pairing.as_ref()).is_some_and(|(p,r)|p.local_handle()==r.handle) {*current=None;}
    Ok(())
}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
struct RemoveHostReply {key_deleted:bool}
#[tauri::command]
async fn host_remove(id:String,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<RemoveHostReply,String>{
    let _lease=pairing.enter()?;let f=flow.lock().map_err(|_|"state_unavailable")?;if f.owner.is_some(){return Err("connection_active".into());}
    let host=hosts.remove(&id)?;let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?;
    if current.as_ref().zip(host.pairing.as_ref()).is_some_and(|(p,r)|p.local_handle()==r.handle){*current=None;}
    let key_deleted=host.pairing.as_ref().is_none_or(|r|pairing.store.delete(&r.handle).is_ok());
    Ok(RemoveHostReply{key_deleted})
}
struct PairingState { store: Arc<dyn KeyStore>, current: Arc<Mutex<Option<Pairing>>>, busy: AtomicBool, restore_required: AtomicBool }
struct PairingLease<'a>(&'a AtomicBool);
impl Drop for PairingLease<'_> { fn drop(&mut self) { self.0.store(false,Ordering::Release); } }
impl PairingState {
    fn new(store: Arc<dyn KeyStore>) -> Self { Self { store, current: Arc::new(Mutex::new(None)), busy:AtomicBool::new(false), restore_required:AtomicBool::new(false) } }
    fn enter(&self)->Result<PairingLease<'_>,String> {
        self.busy.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|"pairing_busy")?;
        Ok(PairingLease(&self.busy))
    }
}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
struct PairingView { request: String, fingerprint: String, state: &'static str, authorization: &'static str, stored: bool }
fn pairing_view(p: &Pairing) -> Result<PairingView,String> { Ok(PairingView {request:p.request_json().map_err(str::to_string)?,fingerprint:p.public_fingerprint().map_err(str::to_string)?,state:p.state,authorization:p.authorization,stored:true}) }
fn now() -> Result<u64,String> { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|x|x.as_secs()).map_err(|_|"invalid_time".into()) }
#[tauri::command]
async fn pair_create(config:RemoteConfig,device:String,host_id:String,state:State<'_,PairingState>,hosts:State<'_,Hosts>) -> Result<PairingView,String> {
    let _lease=state.enter()?;
    if state.restore_required.load(Ordering::SeqCst) {return Err("host_restore_required".into());}
    let mut current=state.current.lock().map_err(|_|"state_unavailable")?;
    if current.is_some() { return Err("pairing_already_exists".into()); }
    config.validate_pair_target().map_err(str::to_string)?;
    let host=hosts.get(&host_id)?; if !host.enabled || host.target!=Target::from_config(&config) || host.pairing.is_some() {return Err("host_pairing_exists".into());}
    let mut p=Pairing::create(state.store.clone(),&config.username,&config.expected_host_key,&device,now()?).map_err(str::to_string)?;
    if let Err(e)=p.bind_target(&config) { let _=p.delete_local(); return Err(e.into()); }
    let stored=p.pending_reference(&config).map_err(str::to_string).and_then(|reference|hosts.attach_pending(&host_id,&host.target,reference)).is_ok();
    let mut view=pairing_view(&p)?; if !stored {view.request.clear();view.state="storage-failed";view.stored=false;} *current=Some(p); Ok(view)
}
#[tauri::command]
fn pair_accept(response:String,reviewed:bool,state:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,hosts:State<'_,Hosts>) -> Result<PairingView,String> {
    let _lease=state.enter()?;
    let f=flow.lock().map_err(|_|"state_unavailable")?;
    if f.owner.is_some() { return Err("connection_active".into()); }
    let mut current=state.current.lock().map_err(|_|"state_unavailable")?;
    let p=current.as_mut().ok_or("pairing_missing")?;
    let mut proposed=p.clone(); proposed.accept(&response,now()?,reviewed).map_err(str::to_string)?;
    if proposed.authorization=="revoked" {hosts.clear_handle(p.local_handle())?;} else if proposed.authorization=="authorized" {hosts.set_status(p.local_handle(),ReferenceStatus::Authorized)?;}
    *p=proposed; pairing_view(p)
}
#[tauri::command]
fn pair_cancel(state:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,gate:State<'_,Mutex<AttemptGate>>,hosts:State<'_,Hosts>) -> Result<(),String> {
    let _lease=state.enter()?;
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    let mut g=gate.lock().map_err(|_|"state_unavailable")?;
    if let Some(owner)=f.owner { f.cancel(owner,&mut g); }
    if let Some(p)=state.current.lock().map_err(|_|"state_unavailable")?.as_mut() { hosts.set_status(p.local_handle(),ReferenceStatus::Cancelled)?; p.cancel(); }
    Ok(())
}
#[tauri::command]
async fn pair_reset(state:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,hosts:State<'_,Hosts>) -> Result<(),String> {
    let _lease=state.enter()?;
    let f=flow.lock().map_err(|_|"state_unavailable")?;
    if f.owner.is_some() { return Err("connection_active".into()); }
    let mut current=state.current.lock().map_err(|_|"state_unavailable")?;
    if let Some(p)=current.as_ref() { if hosts.initialized()? {hosts.clear_handle(p.local_handle())?;} p.delete_local().map_err(str::to_string)?; }
    current.take();
    Ok(())
}
#[derive(Default)]
struct RemoteFlow {
    owner: Option<u64>,
    cancelled_through: u64,
    select: Option<(u64, tokio::sync::oneshot::Sender<String>)>,
    ack: Option<(u64, u64, tokio::sync::oneshot::Sender<()>)>,
    input: Option<(u64, Arc<herdr_readonly_transport::input::LiveInput>)>,
    recovery: Option<herdr_readonly_transport::input::Recovery>,
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
        if self.owner==Some(client_generation) { if let Some((_,input))=self.input.take() {input.invalidate();} gate.cancel(); }
    }
    fn finish(&mut self, client_generation:u64, generation:u64, gate:&mut AttemptGate)->bool {
        if self.owner!=Some(client_generation) { return false; }
        self.select=None; self.ack=None; self.owner=None; if let Some((_,input))=self.input.take() {input.invalidate();}
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
    InputReady { generation:u64, unknown:bool, recovery_status:&'static str },
}
#[tauri::command]
async fn remote_observe(config:RemoteConfig,device:bool,client_generation:u64,on_event:Channel<ObserveEvent>,state:State<'_,Mutex<AttemptGate>>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,pairing:State<'_,PairingState>)->Result<(),String> {
    let (generation,cancel)={ let mut f=flow.lock().map_err(|_|"state_unavailable")?; if pairing.restore_required.load(Ordering::SeqCst) {return Err("host_restore_required".into());} let mut g=state.lock().map_err(|_|"state_unavailable")?; f.begin(client_generation,&mut g).map_err(str::to_string)? };
    let device_auth=if device {
        let lease=pairing.enter();
        if let Err(e)=lease { let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.finish(client_generation,generation,&mut g); return Err(e); }
        let _lease=lease.unwrap();
        let result=pairing.current.lock().map_err(|_|"state_unavailable")?.as_mut().ok_or("pairing_missing").and_then(|p| p.begin(&config));
        match result { Ok(v)=>Some(v), Err(e)=> { let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.finish(client_generation,generation,&mut g); return Err(e.into()); } }
    } else { None };
    let pair_progress=pairing.current.clone();
    let progress_cancel=cancel.clone();
    let progress_channel=on_event.clone();
    let select_channel=on_event.clone();
    let frame_channel=on_event.clone();
    let select_flow=flow.inner().clone();
    let frame_flow=flow.inner().clone();
    let progress=move |stage| { if device && stage=="authenticated" { if let Ok(mut p)=pair_progress.lock() { if let Some(p)=p.as_mut() { p.finish(true); } } } if progress_channel.send(ObserveEvent::Stage{generation,stage}).is_err(){progress_cancel.cancel();} };
    let select=
        move |panes| { let flow=select_flow.clone(); let channel=select_channel.clone(); async move {
            let (tx,rx)=tokio::sync::oneshot::channel();
            flow.lock().map_err(|_|"state_unavailable")?.select=Some((generation,tx));
            channel.send(ObserveEvent::Dashboard{generation,panes}).map_err(|_|"client_closed")?;
            rx.await.map_err(|_|"cancelled")
        }};
    let frame=move |frame:herdr_readonly_transport::StreamFrame| { let flow=frame_flow.clone(); let channel=frame_channel.clone(); async move {
            let seq=frame.seq; let (tx,rx)=tokio::sync::oneshot::channel();
            flow.lock().map_err(|_|"state_unavailable")?.ack=Some((generation,seq,tx));
            channel.send(ObserveEvent::Frame{generation,frame}).map_err(|_|"client_closed")?;
            rx.await.map_err(|_|"cancelled")
        }};
    let input_flow=flow.inner().clone(); let input_channel=on_event.clone(); let input_cancel=cancel.clone();
    let recovery=flow.lock().map_err(|_|"state_unavailable")?.recovery.clone().unwrap_or_else(herdr_readonly_transport::recovery::Recovery::disabled);
    let hooks=herdr_readonly_transport::InputHooks { recovery, ready:Arc::new(move |input| {
        if input_cancel.is_cancelled() {input.invalidate();return;}
        let unknown=input.unknown(); let recovery_status=input.recovery_status();
        if let Ok(mut f)=input_flow.lock() {
            if f.owner!=Some(client_generation) || input_cancel.is_cancelled() {input.invalidate();return;}
            f.input=Some((generation,input));
            if input_channel.send(ObserveEvent::InputReady {generation,unknown,recovery_status}).is_err() {if let Some((_,input))=f.input.take(){input.invalidate();} input_cancel.cancel();}
        } else { input.invalidate(); input_cancel.cancel(); }
    }) };
    let result=herdr_readonly_transport::observe_interactive(config,device_auth,cancel,Arc::new(Audit::default()),progress,select,frame,hooks).await;
    if device { if let Ok(mut p)=pairing.current.lock() { if let Some(p)=p.as_mut() { p.finish(false); } } }
    let accepted={ let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.finish(client_generation,generation,&mut g) };
    if !accepted {return Err("cancelled".into());}
    result.map_err(str::to_string)
}
fn current_input(flow:&Mutex<RemoteFlow>,generation:u64)->Result<Arc<herdr_readonly_transport::input::LiveInput>,String> {
    let f=flow.lock().map_err(|_|"state_unavailable")?;
    f.input.as_ref().filter(|(g,_)|*g==generation).map(|(_,i)|i.clone()).ok_or("input_stale".into())
}
#[tauri::command]
fn remote_input_mode(generation:u64,mode:String,focused:bool,flow:State<'_,Arc<Mutex<RemoteFlow>>>) -> Result<u64,String> {
    current_input(&flow,generation)?.set_mode(&mode,focused).map_err(str::to_string)
}
#[tauri::command]
fn remote_input_recover(generation:u64,epoch:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>) -> Result<(),String> {
    current_input(&flow,generation)?.acknowledge_unknown(epoch).map_err(str::to_string)
}
#[tauri::command]
async fn remote_input_send(generation:u64,epoch:u64,bytes:Vec<u8>,draft:bool,flow:State<'_,Arc<Mutex<RemoteFlow>>>) -> Result<&'static str,String> {
    use herdr_readonly_transport::input::SendOutcome;
    let input=current_input(&flow,generation)?;
    input.send(epoch,bytes,draft).await.map(|outcome|match outcome {SendOutcome::Accepted=>"accepted",SendOutcome::Rejected=>"rejected",SendOutcome::Unknown=>"unknown"}).map_err(str::to_string)
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
fn remote_cancel(client_generation:u64,state:State<'_,Mutex<AttemptGate>>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,pairing:State<'_,PairingState>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; if f.owner==Some(client_generation) { if let Some(p)=pairing.current.lock().map_err(|_|"state_unavailable")?.as_mut() { if p.state=="connecting" {p.cancel();} } } f.cancel(client_generation,&mut g); Ok(())
}
#[cfg(any(target_os="ios",target_os="windows"))]
struct UnavailableKeyStore;
#[cfg(any(target_os="ios",target_os="windows"))]
impl KeyStore for UnavailableKeyStore {
    fn create(&self)->herdr_readonly_transport::Result<(String,String)> {Err("key_unavailable")}
    fn public(&self,_:&str)->herdr_readonly_transport::Result<String> {Err("key_unavailable")}
    fn sign(&self,_:&str,_:&[u8])->herdr_readonly_transport::Result<Vec<u8>> {Err("key_unavailable")}
    fn delete(&self,_:&str)->herdr_readonly_transport::Result<()> {Err("key_unavailable")}
}
mod camera;
use camera::pair_scan_response;
#[cfg(target_os="android")]
mod android_keys;
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder=tauri::Builder::default();
    #[cfg(any(target_os="linux",target_os="macos"))]
    let builder=builder.manage(PairingState::new(Arc::new(herdr_readonly_transport::pairing::VolatileKeyStore::default())));
    #[cfg(any(target_os="ios",target_os="windows"))]
    let builder=builder.manage(PairingState::new(Arc::new(UnavailableKeyStore)));
    #[cfg(target_os="android")]
    let builder=builder.plugin(android_keys::init()).plugin(camera::android_plugin());
    builder
        .manage(Mutex::new(Streams::default()))
        .manage(Mutex::new(AttemptGate::default()))
        .manage(Hosts::default())
        .setup(|app| {
            let recovery=app.path().app_local_data_dir().ok().map(|p|herdr_readonly_transport::recovery::Recovery::open(p.join("remote-input-v1"))).unwrap_or_else(herdr_readonly_transport::recovery::Recovery::disabled);
            let flow=RemoteFlow {recovery:Some(recovery),..Default::default()};
            app.manage(Arc::new(Mutex::new(flow))); Ok(())
        })
        .invoke_handler(tauri::generate_handler![fixture_begin,fixture_next,fixture_ack,fixture_cancel,remote_read_once,remote_observe,remote_select,remote_ack,remote_cancel,remote_input_mode,remote_input_recover,remote_input_send,pair_create,pair_accept,pair_cancel,pair_reset,pair_scan_response,host_init,host_list,host_save,host_new,host_select,host_restore,host_update,host_remove])
        .run(tauri::generate_context!())
        .expect("Tauri probe startup failed");
}
