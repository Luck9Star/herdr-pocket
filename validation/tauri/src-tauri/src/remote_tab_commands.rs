//! Tab-scoped bridge; no target or signer is taken from the pairing editor.
use super::*;
use herdr_readonly_transport::{Cancellation, Pane, StreamFrame, ControlledInputHooks, ObservationSnapshot, DashboardTarget, session_watch::SessionWatchUpdate};

#[derive(Serialize,Clone)]
#[serde(tag="kind",rename_all="snake_case")]
pub enum TabEvent {
    Stage {generation:u64,stage:&'static str},
    Frame {generation:u64,epoch:u64,frame:StreamFrame},
    Observation {generation:u64,snapshot:ObservationSnapshot},
    DashboardWatch {generation:u64,update:SessionWatchUpdate},
    SelectionReady {generation:u64,epoch:u64},
    TargetBound {generation:u64,epoch:u64,pane_id:String,terminal_id:String},
    InputReady {generation:u64,epoch:u64,unknown:bool,recovery_status:&'static str},
}

struct TabCleanup {flow:Arc<Mutex<RemoteFlow>>,tab:String,owner:u64,generation:u64}
impl Drop for TabCleanup {fn drop(&mut self) {if let Ok(mut f)=self.flow.lock(){f.tabs.finish(&self.tab,self.owner,self.generation);}}}

#[tauri::command]
pub async fn remote_tab_observe(tab_id:String,client_generation:u64,generation:u64,pane_id:String,terminal_id:String,canvas:Option<herdr_readonly_transport::ObserveCanvas>,on_event:Channel<TabEvent>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,pairing:State<'_,PairingState>,hosts:State<'_,Hosts>,nodes:State<'_,network_nodes::Nodes>,ops:State<'_,network_identity::Operations>,app:tauri::AppHandle)->Result<(),String> {
    let canvas=canvas.unwrap_or_default().validate().map_err(str::to_string)?;
    let cancel={let mut f=flow.lock().map_err(|_|"state_unavailable")?;if !f.tabs.is_visible(&tab_id,client_generation,generation){f.tabs.cancel(&tab_id,client_generation,generation);return Err("tab_stale".into());}f.tabs.claim(&tab_id,client_generation,generation).map_err(str::to_string)?};
    let _cleanup=TabCleanup {flow:flow.inner().clone(),tab:tab_id.clone(),owner:client_generation,generation};
    let result=tab_observe_inner(&tab_id,client_generation,generation,&pane_id,&terminal_id,canvas,on_event,cancel,&flow,&pairing,&hosts,&nodes,&ops,&app).await;
    let accepted=flow.lock().map_err(|_|"state_unavailable")?.tabs.finish(&tab_id,client_generation,generation);
    if !accepted {return Err("cancelled".into());} result
}

#[allow(clippy::too_many_arguments)]
async fn tab_observe_inner(tab:&str,owner:u64,generation:u64,pane:&str,terminal:&str,canvas:herdr_readonly_transport::ObserveCanvas,on_event:Channel<TabEvent>,cancel:Cancellation,flow:&Arc<Mutex<RemoteFlow>>,pairing:&PairingState,hosts:&Hosts,nodes:&network_nodes::Nodes,ops:&network_identity::Operations,app:&tauri::AppHandle)->Result<(),String> {
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
    let mut config=record.target.config();
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
    config.observe_canvas=canvas.validate().map_err(str::to_string)?;
    let control={let f=flow.lock().map_err(|_|"state_unavailable")?;f.tabs.get(tab).filter(|s|s.owner==owner && s.generation==generation).and_then(|s|s.control.clone()).ok_or("tab_stale")?};
    let watch_flow=flow.clone();let watch_tab=tab.to_owned();let watch_event=on_event.clone();let watch_cancel=cancel.clone();
    control.set_dashboard_listener(Arc::new(move |update| {
        let accepted=watch_flow.lock().ok().is_some_and(|mut f| {
            if !f.tabs.is_visible(&watch_tab,owner,generation) || watch_cancel.is_cancelled(){return false;}
            let Some(s)=f.tabs.get_mut(&watch_tab).filter(|s|s.owner==owner && s.generation==generation)else{return false;};
            let Some(epoch)=s.control.as_ref().map(|c|c.snapshot().epoch)else{return false;};
            s.dashboard.update(epoch,&update)
        });
        if accepted && watch_event.send(TabEvent::DashboardWatch {generation,update}).is_err(){watch_cancel.cancel();}
    })).map_err(str::to_string)?;
    {let mut f=flow.lock().map_err(|_|"state_unavailable")?;let s=f.tabs.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;
     if !pane.is_empty() && !terminal.is_empty(){s.selected=Some(DashboardTarget{pane_id:pane.into(),terminal_id:terminal.into()});}}
    let pane=pane.to_owned();let terminal=terminal.to_owned();
    let select_flow=flow.clone();let select_tab=tab.to_owned();let select_event=on_event.clone();let select_control=control.clone();
    let select=move |panes:Vec<Pane>| {let pane=pane.clone();let terminal=terminal.clone();let flow=select_flow.clone();let tab=select_tab.clone();let event=select_event.clone();let control=select_control.clone();async move {
        if !pane.is_empty() {
            if !panes.iter().any(|p|p.pane_id==pane && p.terminal_id==terminal) {return Err("pane_missing");}
            return Ok(DashboardTarget {pane_id:pane,terminal_id:terminal});
        }
        if !terminal.is_empty() {return Err("pane_missing");}
        let epoch=control.snapshot().epoch;
        let (tx,rx)=tokio::sync::oneshot::channel();
        {let mut f=flow.lock().map_err(|_|"state_unavailable")?;let s=f.tabs.get_mut(&tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;s.selected=None;s.select=Some((generation,epoch,tx));}
        event.send(TabEvent::SelectionReady{generation,epoch}).map_err(|_|"client_closed")?;
        rx.await.map_err(|_|"cancelled")
    }};
    let event=on_event.clone();let progress_cancel=cancel.clone();
    let progress=move |stage| {if event.send(TabEvent::Stage{generation,stage}).is_err(){progress_cancel.cancel();}};
    let event=on_event.clone();let tab_id=tab.to_owned();let frame_flow=flow.clone();
    let frame=move |epoch:u64,frame:StreamFrame| {let tab=tab_id.clone();let flow=frame_flow.clone();let event=event.clone();async move {
        let (tx,rx)=tokio::sync::oneshot::channel();let seq=frame.seq;
        let target={let mut f=flow.lock().map_err(|_|"state_unavailable")?;let s=f.tabs.get_mut(&tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;if s.control.as_ref().is_none_or(|c|c.snapshot().epoch!=epoch){return Err("cancelled");}s.ack=Some((generation,epoch,seq,tx));s.selected.clone().ok_or("target_unavailable")?};
        if frame.full {event.send(TabEvent::TargetBound{generation,epoch,pane_id:target.pane_id,terminal_id:target.terminal_id}).map_err(|_|"client_closed")?;}
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
    herdr_readonly_transport::observe_interactive_controlled_target_with_dialer(config,Some(device),cancel,Arc::new(Audit::default()),progress,select,frame,Some(hooks),control,dialer.as_ref()).await.map_err(str::to_string)
}

#[tauri::command]
pub fn remote_tab_ack(tab_id:String,client_generation:u64,generation:u64,epoch:u64,seq:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if !f.tabs.is_visible(&tab_id,client_generation,generation){return Err("tab_stale".into());}
    let session=f.tabs.get_mut(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
    if session.control.as_ref().is_none_or(|c|c.snapshot().epoch!=epoch) || !session.ack.as_ref().is_some_and(|(g,e,n,_)|*g==generation && *e==epoch && *n==seq){return Err("stale_ack".into());}
    session.ack.take().unwrap().3.send(()).map_err(|_|"cancelled".into())
}

#[tauri::command]
pub async fn remote_tab_control(tab_id:String,client_generation:u64,generation:u64,action:String,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<ObservationSnapshot,String> {
    let control={let f=flow.lock().map_err(|_|"state_unavailable")?;if action=="resume" && !f.tabs.is_visible(&tab_id,client_generation,generation){return Err("tab_stale".into());}f.tabs.get(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).and_then(|s|s.control.clone()).ok_or("tab_stale")?};
    // Pause retires the input inside the shared control before local handles are dropped.
    let ack=match action.as_str() {"pause"=>control.pause(),"resume"=>control.resume(),_=>return Err("invalid_control".into())};
    let ack=match ack {Ok(ack)=>ack,Err(error)=>{flow.lock().map_err(|_|"state_unavailable")?.tabs.cancel(&tab_id,client_generation,generation);return Err(error.into());}};
    if action=="pause" {let mut f=flow.lock().map_err(|_|"state_unavailable")?;if f.tabs.clear_visible(&tab_id,client_generation,generation) {if let Some(s)=f.tabs.get_mut(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation) {s.input.take();s.ack.take();}}}
    ack.await.map_err(str::to_string)
}

// Review focus permits only explicit observation-mode journal confirmation.
// It never grants a direct/draft write lease or changes observation identity.
fn input_mode_focus(mode:&str,review:Option<bool>)->Result<bool,&'static str> {
    if !matches!(mode,"observe"|"direct"|"draft") {return Err("invalid_mode");}
    if review==Some(true) && mode!="observe" {return Err("invalid_review_mode");}
    Ok(mode!="observe" || review==Some(true))
}

#[tauri::command]
pub fn remote_tab_input_mode(tab_id:String,client_generation:u64,generation:u64,epoch:u64,mode:String,review:Option<bool>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<u64,String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    let focused=input_mode_focus(&mode,review).map_err(str::to_string)?;
    let key=(tab_id.clone(),client_generation,generation,epoch);
    if !f.tabs.is_visible(&tab_id,client_generation,generation){return Err("input_stale".into());}
    let s=f.tabs.get(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
    if s.control.as_ref().is_none_or(|c| {let v=c.snapshot();v.epoch!=epoch || v.phase!=herdr_readonly_transport::ObservationPhase::Active}) {return Err("input_stale".into());}
    let input=s.input.as_ref().filter(|(g,e,_)|*g==generation && *e==epoch).map(|(_,_,v)|v.clone()).ok_or("input_stale")?;
    // Focus arbitration before the transport mutation; see switch_input_mode.
    remote_sessions::switch_input_mode(&mut f.tabs,key,&mode,focused,|mode,focused|input.set_mode(mode,focused).map_err(str::to_string))
}
#[tauri::command]
pub async fn remote_tab_input_send(tab_id:String,client_generation:u64,generation:u64,epoch:u64,input_epoch:u64,bytes:Vec<u8>,draft:bool,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<serde_json::Value,String> {
    let input={let f=flow.lock().map_err(|_|"state_unavailable")?;
        f.tabs.input_guard(&tab_id,client_generation,generation,epoch).map_err(str::to_string)?;
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

// Visibility is an add-to-set operation: several tabs may observe simultaneously
// (desktop split view); only input focus stays exclusive.
#[tauri::command]
pub fn remote_tab_visible(tab_id:String,client_generation:u64,generation:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    f.tabs.set_visible(&tab_id,client_generation,generation).map_err(str::to_string)
}

#[tauri::command]
pub fn remote_tab_select(tab_id:String,client_generation:u64,generation:u64,epoch:u64,revision:u64,pane_id:String,terminal_id:String,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if !f.tabs.is_visible(&tab_id,client_generation,generation){return Err("tab_stale".into());}
    let s=f.tabs.get_mut(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
    s.select_dashboard(generation,epoch,revision,pane_id,terminal_id).map_err(str::to_string)
}
#[tauri::command]
pub fn remote_tab_input_recover(tab_id:String,client_generation:u64,generation:u64,epoch:u64,input_epoch:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let input={let f=flow.lock().map_err(|_|"state_unavailable")?;
        if !f.tabs.is_visible(&tab_id,client_generation,generation){return Err("input_stale".into());}
        let s=f.tabs.get(&tab_id).filter(|s|s.owner==client_generation && s.generation==generation).ok_or("tab_stale")?;
        if s.control.as_ref().is_none_or(|c| {let v=c.snapshot();v.epoch!=epoch || v.phase!=herdr_readonly_transport::ObservationPhase::Active}) {return Err("input_stale".into());}
        s.input.as_ref().filter(|(g,e,_)|*g==generation && *e==epoch).map(|(_,_,v)|v.clone()).ok_or("input_stale")?
    };
    input.acknowledge_unknown(input_epoch).map_err(str::to_string)
}

#[cfg(test)]
mod input_review_tests {
    use super::*;
    #[test]
    fn explicit_observe_review_has_focus_but_blur_and_write_modes_cannot_impersonate_it() {
        assert_eq!(input_mode_focus("observe",None),Ok(false));
        assert_eq!(input_mode_focus("observe",Some(false)),Ok(false));
        assert_eq!(input_mode_focus("observe",Some(true)),Ok(true));
        assert_eq!(input_mode_focus("direct",None),Ok(true));
        assert_eq!(input_mode_focus("draft",None),Ok(true));
        assert_eq!(input_mode_focus("direct",Some(true)),Err("invalid_review_mode"));
        assert_eq!(input_mode_focus("draft",Some(true)),Err("invalid_review_mode"));
        assert_eq!(input_mode_focus("unknown",Some(true)),Err("invalid_mode"));
    }
}
