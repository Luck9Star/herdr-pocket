//! Tab-scoped bridge; no target or signer is taken from the pairing editor.
use super::*;
use herdr_readonly_transport::{Cancellation, Pane, StreamFrame, ControlledInputHooks, ObservationSnapshot};

#[derive(Serialize,Clone)]
#[serde(tag="kind",rename_all="snake_case")]
pub enum TabEvent {
    Stage {generation:u64,stage:&'static str},
    Frame {generation:u64,epoch:u64,frame:StreamFrame},
    Observation {generation:u64,snapshot:ObservationSnapshot},
    Dashboard {generation:u64,panes:Vec<Pane>},
    InputReady {generation:u64,epoch:u64,unknown:bool,recovery_status:&'static str},
}

struct TabCleanup {flow:Arc<Mutex<RemoteFlow>>,tab:String,owner:u64,generation:u64}
impl Drop for TabCleanup {fn drop(&mut self) {if let Ok(mut f)=self.flow.lock(){f.tabs.finish(&self.tab,self.owner,self.generation);}}}

#[tauri::command]
pub async fn remote_tab_observe(tab_id:String,client_generation:u64,generation:u64,pane_id:String,terminal_id:String,on_event:Channel<TabEvent>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,pairing:State<'_,PairingState>,hosts:State<'_,Hosts>,nodes:State<'_,network_nodes::Nodes>,ops:State<'_,network_identity::Operations>,app:tauri::AppHandle)->Result<(),String> {
    let cancel={let mut f=flow.lock().map_err(|_|"state_unavailable")?;if f.tabs.visible.as_ref()!=Some(&(tab_id.clone(),client_generation,generation)){f.tabs.cancel(&tab_id,client_generation,generation);return Err("tab_stale".into());}f.tabs.claim(&tab_id,client_generation,generation).map_err(str::to_string)?};
    let _cleanup=TabCleanup {flow:flow.inner().clone(),tab:tab_id.clone(),owner:client_generation,generation};
    let result=tab_observe_inner(&tab_id,client_generation,generation,&pane_id,&terminal_id,on_event,cancel,&flow,&pairing,&hosts,&nodes,&ops,&app).await;
    let accepted=flow.lock().map_err(|_|"state_unavailable")?.tabs.finish(&tab_id,client_generation,generation);
    if !accepted {return Err("cancelled".into());} result
}

#[allow(clippy::too_many_arguments)]
async fn tab_observe_inner(tab:&str,owner:u64,generation:u64,pane:&str,terminal:&str,on_event:Channel<TabEvent>,cancel:Cancellation,flow:&Arc<Mutex<RemoteFlow>>,pairing:&PairingState,hosts:&Hosts,nodes:&network_nodes::Nodes,ops:&network_identity::Operations,app:&tauri::AppHandle)->Result<(),String> {
    let _lease=ops.enter()?;
    let record={let f=flow.lock().map_err(|_|"state_unavailable")?;f.tabs.get(tab).filter(|s|s.owner==owner && s.generation==generation).and_then(|s|s.record.clone()).ok_or("tab_stale")?};
    let current=hosts.get(&record.id)?;
    if serde_json::to_value(&current).map_err(|_|"state_unavailable")? != serde_json::to_value(&record).map_err(|_|"state_unavailable")? {return Err("host_selection_changed".into());}
    let profile=hosts.route(&record)?;
    let (dialer,binding):(Box<dyn herdr_readonly_transport::transport::Dialer>,Option<herdr_readonly_transport::mobile_nodes::Binding>)=match network_nodes::select_route(profile.as_ref())? {
        network_nodes::RouteKind::System=>(Box::new(herdr_readonly_transport::transport::SystemDialer),None),
        network_nodes::RouteKind::Overlay=>{let (dialer,b)=nodes.route(app,profile.as_ref().ok_or("network_profile_missing")?).await?;(dialer,Some(b))}
    };
    if cancel.is_cancelled(){return Err("cancelled".into());}
    let config=record.target.config();
    let device={
        let mut f=flow.lock().map_err(|_|"state_unavailable")?;
        let s=f.tabs.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation && !cancel.is_cancelled()).ok_or("tab_stale")?;
        let current=hosts.get(&record.id)?;
        let selected=hosts.route(&current)?;
        if serde_json::to_value(&current).map_err(|_|"state_unavailable")? != serde_json::to_value(&record).map_err(|_|"state_unavailable")? || selected.as_ref().map(|p|(p.id.as_str(),p.revision))!=binding.as_ref().map(|b|(b.profile_id(),b.profile_revision())) {return Err("host_selection_changed".into());}
        let reference=record.pairing.as_ref().ok_or("pairing_missing")?;
        let mut identity=restore_offline_pair(pairing.store.clone(),reference,&config,true,now()?)?;
        let device=identity.begin(&config).map_err(str::to_string)?;
        s.node_binding=binding;device
    };
    drop(_lease);
    let control={let f=flow.lock().map_err(|_|"state_unavailable")?;f.tabs.get(tab).filter(|s|s.owner==owner && s.generation==generation).and_then(|s|s.control.clone()).ok_or("tab_stale")?};
    let pane=pane.to_owned();let terminal=terminal.to_owned();
    let select_flow=flow.clone();let select_tab=tab.to_owned();let select_event=on_event.clone();
    let select=move |panes:Vec<Pane>| {let pane=pane.clone();let terminal=terminal.clone();let flow=select_flow.clone();let tab=select_tab.clone();let event=select_event.clone();async move {
        if !pane.is_empty() {
            if !panes.iter().any(|p|p.pane_id==pane && p.terminal_id==terminal) {return Err("pane_missing");}
            event.send(TabEvent::Dashboard{generation,panes:panes.clone()}).map_err(|_|"client_closed")?;
            return Ok(pane);
        }
        if !terminal.is_empty() {return Err("pane_missing");}
        let (tx,rx)=tokio::sync::oneshot::channel();
        {let mut f=flow.lock().map_err(|_|"state_unavailable")?;let s=f.tabs.get_mut(&tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;s.select=Some((generation,tx));}
        event.send(TabEvent::Dashboard{generation,panes:panes.clone()}).map_err(|_|"client_closed")?;
        let selected=rx.await.map_err(|_|"cancelled")?;
        if panes.iter().any(|p|p.pane_id==selected){Ok(selected)} else {Err("pane_missing")}
    }};
    let event=on_event.clone();let progress_cancel=cancel.clone();
    let progress=move |stage| {if event.send(TabEvent::Stage{generation,stage}).is_err(){progress_cancel.cancel();}};
    let event=on_event.clone();let tab_id=tab.to_owned();let frame_flow=flow.clone();
    let frame=move |epoch:u64,frame:StreamFrame| {let tab=tab_id.clone();let flow=frame_flow.clone();let event=event.clone();async move {
        let (tx,rx)=tokio::sync::oneshot::channel();let seq=frame.seq;
        {let mut f=flow.lock().map_err(|_|"state_unavailable")?;let s=f.tabs.get_mut(&tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;if s.control.as_ref().is_none_or(|c|c.snapshot().epoch!=epoch){return Err("cancelled");}s.ack=Some((generation,epoch,seq,tx));}
        event.send(TabEvent::Frame{generation,epoch,frame}).map_err(|_|"client_closed")?;rx.await.map_err(|_|"cancelled")
    }};
    let tab_id=tab.to_owned();let input_flow=flow.clone();let event=on_event;let input_cancel=cancel.clone();
    let recovery=flow.lock().map_err(|_|"state_unavailable")?.recovery.clone().unwrap_or_else(herdr_readonly_transport::recovery::Recovery::disabled);
    let state_event=event.clone();let state_flow=flow.clone();let state_tab=tab.to_owned();
    let hooks=ControlledInputHooks {recovery,state:Arc::new(move |snapshot| {
        let current=state_flow.lock().ok().and_then(|f|f.tabs.get(&state_tab).and_then(|s|s.control.as_ref()).map(|c|c.snapshot().epoch));
        if current==Some(snapshot.epoch) {let _=state_event.send(TabEvent::Observation{generation,snapshot});}
    }),ready:Arc::new(move |epoch,input| {
        let Ok(mut f)=input_flow.lock() else {input.invalidate();return};
        let Some(s)=f.tabs.get_mut(&tab_id).filter(|s|s.owner==owner && s.generation==generation && !input_cancel.is_cancelled() && s.control.as_ref().is_some_and(|c|c.snapshot().epoch==epoch)) else {input.invalidate();return};
        let unknown=input.unknown();let recovery_status=input.recovery_status();s.input=Some((generation,epoch,input));
        if event.send(TabEvent::InputReady{generation,epoch,unknown,recovery_status}).is_err(){if let Some((_,_,input))=s.input.take(){input.invalidate();}input_cancel.cancel();}
    })};
    herdr_readonly_transport::observe_interactive_controlled_with_dialer(config,Some(device),cancel,Arc::new(Audit::default()),progress,select,frame,Some(hooks),control,dialer.as_ref()).await.map_err(str::to_string)
}

#[tauri::command]
pub fn remote_tab_ack(tab_id:String,client_generation:u64,generation:u64,epoch:u64,seq:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if f.tabs.visible.as_ref()!=Some(&(tab_id.clone(),client_generation,generation)){return Err("tab_stale".into());}
    let session=f.tabs.get_mut(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
    if session.control.as_ref().is_none_or(|c|c.snapshot().epoch!=epoch) || !session.ack.as_ref().is_some_and(|(g,e,n,_)|*g==generation && *e==epoch && *n==seq){return Err("stale_ack".into());}
    session.ack.take().unwrap().3.send(()).map_err(|_|"cancelled".into())
}

#[tauri::command]
pub async fn remote_tab_control(tab_id:String,client_generation:u64,generation:u64,action:String,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<ObservationSnapshot,String> {
    let control={let f=flow.lock().map_err(|_|"state_unavailable")?;if action=="resume" && f.tabs.visible.as_ref()!=Some(&(tab_id.clone(),client_generation,generation)){return Err("tab_stale".into());}f.tabs.get(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).and_then(|s|s.control.clone()).ok_or("tab_stale")?};
    // Pause retires the input inside the shared control before local handles are dropped.
    let ack=match action.as_str() {"pause"=>control.pause(),"resume"=>control.resume(),_=>return Err("invalid_control".into())};
    let ack=match ack {Ok(ack)=>ack,Err(error)=>{flow.lock().map_err(|_|"state_unavailable")?.tabs.cancel(&tab_id,client_generation,generation);return Err(error.into());}};
    if action=="pause" {let mut f=flow.lock().map_err(|_|"state_unavailable")?;if f.tabs.visible.as_ref().is_some_and(|(id,o,g)|id==&tab_id && *o==client_generation && *g==generation){f.tabs.visible=None;}if f.tabs.focus.as_ref().is_some_and(|(id,o,g,_)|id==&tab_id && *o==client_generation && *g==generation){f.tabs.focus=None;}if let Some(s)=f.tabs.get_mut(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation) {s.input.take();s.ack.take();}}
    ack.await.map_err(str::to_string)
}

#[tauri::command]
pub fn remote_tab_input_mode(tab_id:String,client_generation:u64,generation:u64,epoch:u64,mode:String,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<u64,String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if mode!="draft" && mode!="direct" && mode!="observe" {return Err("invalid_mode".into());}
    let key=(tab_id.clone(),client_generation,generation,epoch);
    if f.tabs.visible.as_ref()!=Some(&(tab_id.clone(),client_generation,generation)){return Err("input_stale".into());}
    if mode!="observe" && f.tabs.focus.as_ref().is_some_and(|active|active!=&key){return Err("focus_busy".into());}
    let s=f.tabs.get(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
    if s.control.as_ref().is_none_or(|c| {let v=c.snapshot();v.epoch!=epoch || v.phase!=herdr_readonly_transport::ObservationPhase::Active}) {return Err("input_stale".into());}
    let input=s.input.as_ref().filter(|(g,e,_)|*g==generation && *e==epoch).map(|(_,_,v)|v.clone()).ok_or("input_stale")?;
    let result=input.set_mode(&mode,mode!="observe").map_err(str::to_string)?;
    if mode!="observe" {f.tabs.focus=Some(key);} else if f.tabs.focus.as_ref()==Some(&key) {f.tabs.focus=None;}
    Ok(result)
}
#[tauri::command]
pub async fn remote_tab_input_send(tab_id:String,client_generation:u64,generation:u64,epoch:u64,input_epoch:u64,bytes:Vec<u8>,draft:bool,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<serde_json::Value,String> {
    let input={let f=flow.lock().map_err(|_|"state_unavailable")?;
        if f.tabs.visible.as_ref()!=Some(&(tab_id.clone(),client_generation,generation)) || f.tabs.focus.as_ref()!=Some(&(tab_id.clone(),client_generation,generation,epoch)){return Err("input_stale".into());}
        let s=f.tabs.get(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
        if s.control.as_ref().is_none_or(|c| {let v=c.snapshot();v.epoch!=epoch || v.phase!=herdr_readonly_transport::ObservationPhase::Active}) {return Err("input_stale".into());}
        s.input.as_ref().filter(|(g,e,_)|*g==generation && *e==epoch).map(|(_,_,v)|v.clone()).ok_or("input_stale")?
    };
    use herdr_readonly_transport::input::SendOutcome;
    Ok(match input.send(input_epoch,bytes,draft).await.map_err(str::to_string)? {
        SendOutcome::Accepted(receipt)=>serde_json::json!({"status":"accepted","receipt":receipt}),
        SendOutcome::Rejected=>serde_json::json!({"status":"rejected"}),
        SendOutcome::RecoveryLocked{receipt:Some(receipt)}=>serde_json::json!({"status":"accepted","receipt":receipt,"recoveryRequired":true}),
        SendOutcome::RecoveryLocked{receipt:None}=>serde_json::json!({"status":"rejected","recoveryRequired":true}),
        SendOutcome::Unknown=>serde_json::json!({"status":"unknown"}),
    })
}

#[tauri::command]
pub fn remote_tab_visible(tab_id:String,client_generation:u64,generation:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;let key=(tab_id.clone(),client_generation,generation);
    if f.tabs.visible.as_ref().is_some_and(|v|v!=&key){return Err("focus_busy".into());}
    if f.tabs.get(&tab_id).is_none_or(|s|s.owner!=client_generation || s.generation!=generation){return Err("tab_stale".into());}
    f.tabs.visible=Some(key);Ok(())
}

#[tauri::command]
pub fn remote_tab_select(tab_id:String,client_generation:u64,generation:u64,pane_id:String,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if f.tabs.visible.as_ref()!=Some(&(tab_id.clone(),client_generation,generation)){return Err("tab_stale".into());}
    let s=f.tabs.get_mut(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
    if !s.select.as_ref().is_some_and(|(g,_)|*g==generation){return Err("stale_selection".into());}
    s.select.take().unwrap().1.send(pane_id).map_err(|_|"cancelled".into())
}
#[tauri::command]
pub fn remote_tab_input_recover(tab_id:String,client_generation:u64,generation:u64,epoch:u64,input_epoch:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let input={let f=flow.lock().map_err(|_|"state_unavailable")?;
        if f.tabs.visible.as_ref()!=Some(&(tab_id.clone(),client_generation,generation)){return Err("input_stale".into());}
        let s=f.tabs.get(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
        if s.control.as_ref().is_none_or(|c| {let v=c.snapshot();v.epoch!=epoch || v.phase!=herdr_readonly_transport::ObservationPhase::Active}) {return Err("input_stale".into());}
        s.input.as_ref().filter(|(g,e,_)|*g==generation && *e==epoch).map(|(_,_,v)|v.clone()).ok_or("input_stale")?
    };
    input.acknowledge_unknown(input_epoch).map_err(str::to_string)
}
