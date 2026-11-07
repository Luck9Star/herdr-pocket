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
    let (generation,cancel)={let mut f=flow.lock().map_err(|_|"state_unavailable")?; if f.owner.is_some() || pairing.restore_required.load(Ordering::SeqCst) {return Err("host_restore_required".into());} if f.tabs.len()>0{return Err("connection_active".into());} let mut g=state.lock().map_err(|_|"state_unavailable")?;let attempt=g.begin().map_err(str::to_string)?;f.owner=Some(LEGACY_OWNER);attempt};
    let progress_cancel=cancel.clone();
    let result=herdr_readonly_transport::read_once(config,cancel,Arc::new(Audit::default()),|stage| {
        if on_event.send(RemoteProgress{generation,stage}).is_err(){progress_cancel.cancel();}
    }).await;
    let accepted={let mut f=flow.lock().map_err(|_|"state_unavailable")?;let mut g=state.lock().map_err(|_|"state_unavailable")?;f.finish(LEGACY_OWNER,generation,&mut g)};
    if !accepted{return Err("cancelled".into());}
    result.map(|snapshot|RemoteReply{generation,snapshot}).map_err(str::to_string)
}
#[cfg(target_os="android")]
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidEasyTierConfig_bindNative(
    mut env:herdr_android_network_source::jni::JNIEnv<'_>,class:herdr_android_network_source::jni::objects::JClass<'_>,context:herdr_android_network_source::jni::objects::JObject<'_>
)->herdr_android_network_source::jni::sys::jboolean {
    if herdr_android_network_source::bind(&mut env,class,context) {1} else {0}
}
#[cfg(target_os="android")]
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidTailscaleConfig_bindNative(
    mut env:herdr_android_network_source::jni::JNIEnv<'_>,class:herdr_android_network_source::jni::objects::JClass<'_>,context:herdr_android_network_source::jni::objects::JObject<'_>
)->herdr_android_network_source::jni::sys::jboolean {
    if herdr_android_network_source::bind_tailscale(&mut env,class,context) {1} else {0}
}
// Host unit tests compile the real Nodes methods against a deliberately rejecting
// IPC boundary. This is type/logic coverage, not an Android plugin substitute.
#[cfg(all(test,not(target_os="android")))]
mod android_keys {
 pub fn network_identity(_: &tauri::AppHandle,_:&str,_:&str,_:&str,_:&str,_:&str)->Result<Option<crate::network_identity::Metadata>,String>{Err("test_android_ipc_unavailable".into())}
 pub fn open_network_auth(_: &tauri::AppHandle,_:&str)->Result<(),String>{Err("test_android_ipc_unavailable".into())}
}
mod hosts;
mod remote_sessions;
mod dashboard_watch;
mod remote_tab_commands;
mod config_document;
mod clipboard;
mod key_cleanup;
mod pair_copy;
mod terminal_keyboard;
use clipboard::mobile_clipboard_read_text;
#[cfg(target_os = "macos")]
mod macos_documents;
mod config_exchange;
use config_document::{config_document_open, config_document_platform, config_document_save};
use config_exchange::{config_apply, config_discard, config_export, config_preview};
use hosts::{Hosts, Target};
mod networks;
mod network_identity;
mod network_nodes;
#[tauri::command]
async fn host_init(app:tauri::AppHandle,hosts:State<'_,Hosts>)->Result<(),String> {
    #[cfg(target_os="android")]
    let root=android_keys::no_backup_directory(&app).map_err(str::to_string)?;
    #[cfg(target_os="ios")]
    let root=ios_keys::private_config_root(&app).map_err(str::to_string)?;
    #[cfg(not(any(target_os="android",target_os="ios")))]
    let root=app.path().app_local_data_dir().map_err(|_|"host_storage_unavailable")?;
    hosts.init(root.join("host-records-v1"))
}
#[tauri::command]
fn preferences_save(font:u8,expected_catalog:String,hosts:State<'_,Hosts>)->Result<(),String>{hosts.save_preferences(font,&expected_catalog)}
#[tauri::command]
fn network_list(hosts:State<'_,Hosts>)->Result<hosts::NetworkCatalog,String>{hosts.networks()}
#[tauri::command]
async fn network_save(profile:networks::NetworkProfile, expected_catalog:String, expected_revision:Option<u32>, affected:Vec<String>, hosts:State<'_,Hosts>, flow:State<'_,Arc<Mutex<RemoteFlow>>>, gate:State<'_,Mutex<AttemptGate>>,ops:State<'_,network_identity::Operations>,nodes:State<'_,network_nodes::Nodes>)->Result<(),String>{
    let _op=ops.enter()?;
    let existing={let mut f=flow.lock().map_err(|_|"state_unavailable")?;
        let catalog=hosts.networks()?;let mut actual:Vec<String>=catalog.bindings.iter().filter(|b|b.profile_id==profile.id).map(|b|b.host_id.clone()).collect();actual.sort();let mut reviewed=affected.clone();reviewed.sort();
        if catalog.revision!=expected_catalog || actual!=reviewed {return Err("network_changed".into());}profile.validate()?;
        let old=catalog.profiles.iter().find(|p|p.id==profile.id);
        if let Some(old)=old {if expected_revision!=Some(old.revision) || old.provider!=profile.provider || old.revision==i32::MAX as u32 {return Err("network_changed".into());}} else if expected_revision.is_some() {return Err("network_changed".into());}
        {let mut g=gate.lock().map_err(|_|"state_unavailable")?;f.cancel_affected(&actual,&mut g);}old.is_some()
    };
    if existing {network_nodes::commit_after_stop(nodes.stop_profile(&profile.id),||hosts.save_network(profile.clone(),&expected_catalog,expected_revision,&affected).map(|_|())).await?;} else {hosts.save_network(profile,&expected_catalog,expected_revision,&affected)?;} Ok(())
}
#[tauri::command]
async fn network_delete(id:String,expected_catalog:String,expected_revision:u32,hosts:State<'_,Hosts>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,ops:State<'_,network_identity::Operations>,app:tauri::AppHandle,nodes:State<'_,network_nodes::Nodes>)->Result<(),String>{
    let _op=ops.enter()?;
    let catalog=hosts.networks()?;let profile=catalog.profiles.iter().find(|p|p.id==id).ok_or("network_profile_missing")?;
    if catalog.revision!=expected_catalog || profile.revision!=expected_revision {return Err("network_changed".into());}
    if catalog.bindings.iter().any(|b|b.profile_id==id) {return Err("network_in_use".into());}
    #[cfg(target_os="android")]
    if matches!(profile.provider,networks::Provider::Easytier|networks::Provider::Tailscale) {
        let provider=network_nodes::provider_name(profile.provider)?;
        let app=app.clone();let id=id.clone();let status=tauri::async_runtime::spawn_blocking(move||android_keys::network_identity(&app,"networkIdentityStatus",&id,provider,"","")).await.map_err(|_|"network_identity_unavailable")?;
        match status {Ok(Some(_))=>return Err("network_identity_in_use".into()),Ok(None)=>{},Err(e)=>return Err(e)}
    }
    #[cfg(not(target_os="android"))] {let _=(app,profile);}
    nodes.stop_profile(&id).await?;
    let _f=flow.lock().map_err(|_|"state_unavailable")?;hosts.delete_network(&id,&expected_catalog,expected_revision)
}
#[tauri::command]
fn network_bind(host_id:String,profile_id:Option<String>,expected_catalog:String,confirmed_direct:bool,hosts:State<'_,Hosts>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,gate:State<'_,Mutex<AttemptGate>>,ops:State<'_,network_identity::Operations>)->Result<(),String>{
    let _op=ops.enter()?;let mut f=flow.lock().map_err(|_|"state_unavailable")?;let old=hosts.get(&host_id)?; if old.network_profile_id.is_some() && profile_id.is_none() && !confirmed_direct{return Err("network_direct_confirmation_required".into());}
    let catalog=hosts.networks()?;if catalog.revision!=expected_catalog {return Err("network_changed".into());}
    if profile_id.as_ref().is_some_and(|id|!catalog.profiles.iter().any(|p|&p.id==id && p.enabled)) {return Err("network_profile_missing".into());}
    old.review_network_binding(profile_id.as_ref().and_then(|id|catalog.profiles.iter().find(|p|&p.id==id)))?;
    if old.network_profile_id!=profile_id {let mut g=gate.lock().map_err(|_|"state_unavailable")?;f.cancel_affected(std::slice::from_ref(&host_id),&mut g);}
    hosts.bind_network(&host_id,profile_id,&expected_catalog)
}
fn reviewed_identity_profile(hosts:&Hosts,id:&str,revision:u32,catalog_revision:&str,affected:&[String])->Result<networks::NetworkProfile,String>{
    let catalog=hosts.networks()?;let p=catalog.profiles.iter().find(|p|p.id==id).ok_or("network_profile_missing")?;
    let mut actual:Vec<_>=catalog.bindings.iter().filter(|b|b.profile_id==id).map(|b|b.host_id.clone()).collect();actual.sort();let mut supplied=affected.to_vec();supplied.sort();
    if catalog.revision!=catalog_revision || p.revision!=revision || actual!=supplied{return Err("network_changed".into());}
    network_nodes::provider_name(p.provider)?;Ok(p.clone())
}
#[tauri::command]
async fn network_identity_status(id:String,hosts:State<'_,Hosts>,ops:State<'_,network_identity::Operations>,app:tauri::AppHandle)->Result<network_identity::Status,String>{
    let _op=ops.enter()?;let catalog=hosts.networks()?;let p=catalog.profiles.iter().find(|p|p.id==id).ok_or("network_profile_missing")?;
    let provider=network_nodes::provider_name(p.provider)?;
    #[cfg(target_os="android")]
    {if !network_nodes::provider_available(p.provider){return Ok(network_identity::Status::unsupported());}
     let result=tauri::async_runtime::spawn_blocking(move||android_keys::network_identity(&app,"networkIdentityStatus",&id,provider,"","")).await.map_err(|_|"network_identity_unavailable")?;result.map(network_identity::Status::from_metadata)}
    #[cfg(not(target_os="android"))]
    {let _=(id,app,provider);Ok(network_identity::Status::unsupported())}
}
#[tauri::command]
async fn network_identity_write(id:String,expected_catalog:String,expected_revision:u32,affected:Vec<String>,action:String,mode:String,secret:String,expected_handle:Option<String>,hosts:State<'_,Hosts>,ops:State<'_,network_identity::Operations>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,gate:State<'_,Mutex<AttemptGate>>,app:tauri::AppHandle,nodes:State<'_,network_nodes::Nodes>)->Result<(),String>{
    let secret=zeroize::Zeroizing::new(secret);let _op=ops.enter()?;
    let profile=reviewed_identity_profile(&hosts,&id,expected_revision,&expected_catalog,&affected)?;
    let provider=network_nodes::provider_name(profile.provider)?;
    network_identity::validate_expected_handle(&action,expected_handle.as_deref())?;
    if action=="create" {network_identity::validate_provider_input(profile.provider,&mode,&secret)?;} else if action!="delete" || !mode.is_empty() || !secret.is_empty() {return Err("invalid_network_identity".into());}
    #[cfg(not(target_os="android"))]
    {let _=(flow,gate,app,secret,expected_handle,nodes,provider);Err("network_identity_unavailable".into())}
    #[cfg(target_os="android")]
    {if !network_nodes::provider_available(profile.provider){return Err("network_identity_unavailable".into());}
     {let mut f=flow.lock().map_err(|_|"state_unavailable")?;let mut g=gate.lock().map_err(|_|"state_unavailable")?;f.cancel_affected(&affected,&mut g);}
     nodes.stop_profile(&id).await?;
     reviewed_identity_profile(&hosts,&id,expected_revision,&expected_catalog,&affected)?;
     tauri::async_runtime::spawn_blocking(move|| {if action=="create" {android_keys::network_identity(&app,"networkIdentityCreate",&id,provider,&mode,&secret).and_then(|v|if v.is_some(){Ok(())}else{Err("network_identity_unavailable".into())})} else {android_keys::delete_network_identity(&app,&id,provider,expected_handle.as_deref().ok_or("invalid_network_identity")?)}}).await.map_err(|_|"network_identity_result_unknown".to_owned())?.map_err(|_|"network_identity_result_unknown".to_owned())}
}
#[tauri::command]
async fn network_node_status(id:String,hosts:State<'_,Hosts>,nodes:State<'_,network_nodes::Nodes>,app:tauri::AppHandle)->Result<network_nodes::View,String>{
    let catalog=hosts.networks()?;let p=catalog.profiles.iter().find(|p|p.id==id).ok_or("network_profile_missing")?;
    network_nodes::provider_name(p.provider)?;nodes.status(&app,p).await
}
#[tauri::command]
async fn network_node_start(id:String,expected_catalog:String,expected_revision:u32,affected:Vec<String>,expected_handle:String,hosts:State<'_,Hosts>,ops:State<'_,network_identity::Operations>,nodes:State<'_,network_nodes::Nodes>,app:tauri::AppHandle,flow:State<'_,Arc<Mutex<RemoteFlow>>>,gate:State<'_,Mutex<AttemptGate>>)->Result<(),String>{
    let _op=ops.enter()?;if !network_identity::valid_handle(&expected_handle){return Err("invalid_network_identity".into());}
    let profile=reviewed_identity_profile(&hosts,&id,expected_revision,&expected_catalog,&affected)?;if !profile.enabled{return Err("network_profile_disabled".into());}
    #[cfg(target_os="android")]
    {if !network_nodes::provider_available(profile.provider){return Err("overlay_provider_unavailable".into());}
     let provider=network_nodes::provider_name(profile.provider)?;let app=app.clone();let key=id.clone();let identity=tauri::async_runtime::spawn_blocking(move||android_keys::network_identity(&app,"networkIdentityStatus",&key,provider,"","")).await.map_err(|_|"network_identity_unavailable")??.ok_or("network_identity_missing")?;
     if identity.handle!=expected_handle{return Err("network_identity_changed".into());}network_identity::validate_runtime_mode(profile.provider,&identity.mode)?;
     reviewed_identity_profile(&hosts,&id,expected_revision,&expected_catalog,&affected)?;
     {let mut f=flow.lock().map_err(|_|"state_unavailable")?;let mut g=gate.lock().map_err(|_|"state_unavailable")?;f.cancel_affected(&affected,&mut g);}
     nodes.start(&profile,expected_handle).await}
    #[cfg(not(target_os="android"))]
    {let _=(nodes,app,profile,flow,gate);Err("overlay_provider_unavailable".into())}
}
#[tauri::command]
async fn network_node_stop(id:String,expected_catalog:String,expected_revision:u32,affected:Vec<String>,binding:herdr_readonly_transport::mobile_nodes::Binding,hosts:State<'_,Hosts>,nodes:State<'_,network_nodes::Nodes>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,gate:State<'_,Mutex<AttemptGate>>)->Result<(),String>{
    reviewed_identity_profile(&hosts,&id,expected_revision,&expected_catalog,&affected)?;
    if binding.profile_id()!=id {return Err("mobile_node_binding_mismatch".into());}
    // Stop may target an older saved binding; never silently substitute the new one.
    {let mut f=flow.lock().map_err(|_|"state_unavailable")?;f.tabs.cancel_binding(&binding);if f.node_binding.as_ref()==Some(&binding){let mut g=gate.lock().map_err(|_|"state_unavailable")?;f.cancel_affected(&affected,&mut g);}}
    nodes.stop_exact(&id,binding).await
}
fn reviewed_login_binding(hosts:&Hosts,id:&str,revision:u32,catalog:&str,affected:&[String],binding:&herdr_readonly_transport::mobile_nodes::Binding)->Result<networks::NetworkProfile,String>{
    let p=reviewed_identity_profile(hosts,id,revision,catalog,affected)?;
    if !p.enabled || p.provider!=networks::Provider::Tailscale || network_nodes::binding_for(&p,binding.identity_ref().into())?!=*binding{return Err("mobile_node_binding_mismatch".into());}Ok(p)
}
#[tauri::command]
async fn network_node_login(id:String,expected_catalog:String,expected_revision:u32,affected:Vec<String>,binding:herdr_readonly_transport::mobile_nodes::Binding,hosts:State<'_,Hosts>,ops:State<'_,network_identity::Operations>,nodes:State<'_,network_nodes::Nodes>,app:tauri::AppHandle)->Result<network_nodes::View,String>{
    let _op=ops.enter()?;let p=reviewed_login_binding(&hosts,&id,expected_revision,&expected_catalog,&affected,&binding)?;
    #[cfg(target_os="android")]
    {let key=id.clone();let identity=tauri::async_runtime::spawn_blocking(move||android_keys::network_identity(&app,"networkIdentityStatus",&key,"tailscale","","")).await.map_err(|_|"network_identity_unavailable")??.ok_or("network_identity_missing")?;
     if identity.handle!=binding.identity_ref() || identity.mode!="DEVICE_STATE"{return Err("network_identity_changed".into());}
     reviewed_login_binding(&hosts,&id,expected_revision,&expected_catalog,&affected,&binding)?;nodes.login(binding).await}
    #[cfg(not(target_os="android"))]
    {let _=(p,nodes,app);Err("overlay_provider_unavailable".into())}
}
#[tauri::command]
async fn network_node_login_status(id:String,expected_catalog:String,expected_revision:u32,affected:Vec<String>,binding:herdr_readonly_transport::mobile_nodes::Binding,hosts:State<'_,Hosts>,nodes:State<'_,network_nodes::Nodes>)->Result<network_nodes::View,String>{
    let p=reviewed_login_binding(&hosts,&id,expected_revision,&expected_catalog,&affected,&binding)?;
    let result=nodes.login_status(&p,&binding).await?;
    reviewed_login_binding(&hosts,&id,expected_revision,&expected_catalog,&affected,&binding)?;Ok(result)
}
#[tauri::command]
async fn network_node_open_auth(id:String,expected_catalog:String,expected_revision:u32,affected:Vec<String>,binding:herdr_readonly_transport::mobile_nodes::Binding,expected_auth_url:String,review_token:String,hosts:State<'_,Hosts>,ops:State<'_,network_identity::Operations>,nodes:State<'_,network_nodes::Nodes>,app:tauri::AppHandle)->Result<(),String>{
    let _op=ops.enter()?;reviewed_login_binding(&hosts,&id,expected_revision,&expected_catalog,&affected,&binding)?;
    nodes.open_auth(&app,&binding,&review_token,&expected_auth_url).await
}
#[tauri::command]
fn host_list(hosts:State<'_,Hosts>)->Result<Vec<hosts::View>,String>{hosts.list()}
#[tauri::command]
fn host_save(id:Option<String>,name:String,config:RemoteConfig,provider_hint:Option<herdr_readonly_transport::config_transfer::Provider>,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<hosts::View,String>{
    if id.is_some() && provider_hint.is_some() {return Err("host_provider_hint_existing".into());}
    let _lease=pairing.enter()?; let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if f.owner.is_some(){return Err("connection_active".into());}
    if let Some(id)=id.as_ref() {if hosts.get(id)?.target!=Target::from_config(&config){f.tabs.cancel_hosts(std::slice::from_ref(id));}}
    config.validate_pair_target().map_err(str::to_string)?;
    let current=pairing.current.lock().map_err(|_|"state_unavailable")?;
    let reference=match current.as_ref() {Some(p) if p.authorization=="authorized"=>Some(p.persistable(&config).map_err(str::to_string)?),_=>None};
    hosts.save_with_provider_hint(id.as_deref(),&name,Target::from_config(&config),reference,provider_hint)
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
    let p=restore_offline_pair(pairing.store.clone(),reference,&host.target.config(),reviewed,now()?)?;
    let view=pairing_view(&p)?;*current=Some(p);pairing.restore_required.store(false,Ordering::SeqCst);Ok(view)
}
#[tauri::command]
fn host_update(id:String,name:Option<String>,enabled:Option<bool>,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String>{
    let _lease=pairing.enter()?;let mut f=flow.lock().map_err(|_|"state_unavailable")?;if f.owner.is_some(){return Err("connection_active".into());}
    if enabled==Some(false){f.tabs.cancel_hosts(std::slice::from_ref(&id));}
    let host=hosts.get(&id)?; let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?; hosts.update(&id,name.as_deref(),enabled)?;
    if enabled==Some(false) && current.as_ref().zip(host.pairing.as_ref()).is_some_and(|(p,r)|p.local_handle()==r.handle) {*current=None;}
    Ok(())
}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
struct RemoveHostReply {key_deleted:bool}
#[tauri::command]
async fn host_remove(id:String,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,ops:State<'_,network_identity::Operations>)->Result<RemoveHostReply,String>{
    let _network_lease=ops.enter()?;
    key_cleanup::remove_host(&pairing,&hosts,&flow,&id)

}
#[tauri::command]
async fn host_cleanup_retry(id:String,hosts:State<'_,Hosts>,pairing:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,ops:State<'_,network_identity::Operations>)->Result<key_cleanup::CleanupReply,String>{
    let _network_lease=ops.enter()?;
    key_cleanup::retry_cleanup(&pairing,&hosts,&flow,&id)
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
// Offline pairing manages only the local device identity and public helper request.
fn create_offline_pair(store:Arc<dyn KeyStore>,config:&RemoteConfig,device:&str,time:u64)->Result<Pairing,String>{
    let mut p=Pairing::create(store,&config.username,&config.expected_host_key,device,time).map_err(str::to_string)?;
    if let Err(e)=p.bind_target(config) {let _=p.delete_local();return Err(e.into());}Ok(p)
}
fn restore_offline_pair(store:Arc<dyn KeyStore>,reference:&herdr_readonly_transport::pairing::PairingReference,config:&RemoteConfig,reviewed:bool,time:u64)->Result<Pairing,String>{
    if reference.status==ReferenceStatus::Authorized {Pairing::restore(store,reference,config,reviewed)} else {Pairing::restore_pending(store,reference,config,reviewed,time)}.map_err(str::to_string)
}
#[tauri::command]
async fn pair_create(config:RemoteConfig,device:String,host_id:String,state:State<'_,PairingState>,hosts:State<'_,Hosts>,flow:State<'_,Arc<Mutex<RemoteFlow>>>) -> Result<PairingView,String> {
    let _lease=state.enter()?;
    if state.restore_required.load(Ordering::SeqCst) {return Err("host_restore_required".into());}
    let f=flow.lock().map_err(|_|"state_unavailable")?;if f.owner.is_some(){return Err("connection_active".into());}
    let mut current=state.current.lock().map_err(|_|"state_unavailable")?;
    if current.is_some() { return Err("pairing_already_exists".into()); }
    config.validate_pair_target().map_err(str::to_string)?;
    let host=hosts.get(&host_id)?; if !host.enabled || host.target!=Target::from_config(&config) || host.pairing.is_some() {return Err("host_pairing_exists".into());}
    let p=create_offline_pair(state.store.clone(),&config,&device,now()?)?;
    let stored=p.pending_reference(&config).map_err(str::to_string).and_then(|reference|hosts.attach_pending(&host_id,&host.target,reference)).is_ok();
    let mut view=pairing_view(&p)?; if !stored {view.request.clear();view.state="storage-failed";view.stored=false;} *current=Some(p); Ok(view)
}
#[tauri::command]
fn pair_accept(response:String,reviewed:bool,state:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,hosts:State<'_,Hosts>) -> Result<PairingView,String> {
    let _lease=state.enter()?;
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    if f.owner.is_some() { return Err("connection_active".into()); }
    let mut current=state.current.lock().map_err(|_|"state_unavailable")?;
    let p=current.as_mut().ok_or("pairing_missing")?;
    let mut proposed=p.clone(); proposed.accept(&response,now()?,reviewed).map_err(str::to_string)?;
    if proposed.authorization=="revoked" {
        f.tabs.cancel_handle(p.local_handle());
        let saved = hosts.set_status(p.local_handle(), ReferenceStatus::Revoked);
        *p = proposed;
        let mut view = pairing_view(p)?;
        view.stored = saved.is_ok();
        return Ok(view);
    }
    if proposed.authorization=="authorized" {hosts.set_status(p.local_handle(),ReferenceStatus::Authorized)?;}
    *p=proposed; pairing_view(p)
}
#[tauri::command]
fn pair_cancel(state:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,gate:State<'_,Mutex<AttemptGate>>,hosts:State<'_,Hosts>) -> Result<(),String> {
    let _lease=state.enter()?;
    let mut f=flow.lock().map_err(|_|"state_unavailable")?;
    let mut g=gate.lock().map_err(|_|"state_unavailable")?;
    if let Some(owner)=f.owner { f.cancel(owner,&mut g); }
    if let Some(p)=state.current.lock().map_err(|_|"state_unavailable")?.as_mut() { f.tabs.cancel_handle(p.local_handle()); hosts.set_status(p.local_handle(),ReferenceStatus::Cancelled)?; p.cancel(); }
    Ok(())
}
#[tauri::command]
async fn pair_reset(state:State<'_,PairingState>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,hosts:State<'_,Hosts>) -> Result<(),String> {
    key_cleanup::reset_current(&state,&hosts,&flow)

}
#[derive(Default)]
struct RemoteFlow {
    tabs: remote_sessions::Sessions,
    owner: Option<u64>,
    host_id: Option<String>,
    node_binding: Option<herdr_readonly_transport::mobile_nodes::Binding>,
    cancelled_through: u64,
    direct: Option<Arc<herdr_readonly_transport::direct_observation::DirectObservation>>,
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
        if self.owner==Some(client_generation) { if let Some(direct)=&self.direct {direct.cancel();} gate.cancel(); }
    }
    fn cancel_affected(&mut self, ids:&[String],gate:&mut AttemptGate) {self.tabs.cancel_hosts(ids);if let Some((owner,id))=self.owner.zip(self.host_id.clone()) {if ids.contains(&id) {self.cancel(owner,gate);}}}
    fn finish(&mut self, client_generation:u64, generation:u64, gate:&mut AttemptGate)->bool {
        if self.owner!=Some(client_generation) { return false; }
        if let Some(direct)=self.direct.take() {direct.cancel();} self.owner=None; self.host_id=None; self.node_binding=None;
        gate.finish(generation)
    }
}
#[cfg(test)]
mod remote_flow_tests {
    use super::*;
    #[test]
    fn network_changes_invalidate_only_affected_owner() {
        let mut f=RemoteFlow::default();let mut gate=AttemptGate::default();let (generation,cancel)=f.begin(1,&mut gate).unwrap();f.host_id=Some("one".into());
        f.cancel_affected(&["two".into()],&mut gate);assert!(!cancel.is_cancelled());
        f.cancel_affected(&["one".into()],&mut gate);assert!(cancel.is_cancelled());assert!(!f.finish(1,generation,&mut gate));
    }
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
#[tauri::command]
fn remote_tab_reserve(tab_id:String,client_generation:u64,host_id:String,expected_target:Target,expected_device_fingerprint:String,expected_network_profile_id:Option<String>,expected_network_revision:Option<u32>,hosts:State<'_,Hosts>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,ops:State<'_,network_identity::Operations>)->Result<u64,String> {
    let _op=ops.enter()?;
    let mut flow=flow.lock().map_err(|_|"state_unavailable")?;
    let record=hosts.get(&host_id)?;
    if flow.owner.is_some() {return Err("connection_active".into());}
    if !record.enabled || record.retired || record.target!=expected_target || record.network_profile_id!=expected_network_profile_id || record.view()?.device_fingerprint.as_deref()!=Some(expected_device_fingerprint.as_str()) || hosts.route(&record)?.as_ref().map(|p|p.revision)!=expected_network_revision {return Err("host_selection_changed".into());}
    let (generation,_)=flow.tabs.begin(&tab_id,client_generation,Some(host_id),None).map_err(str::to_string)?;
    let session=flow.tabs.get_mut(&tab_id).ok_or("state_unavailable")?;session.record=Some(record);session.control=Some(herdr_readonly_transport::ObservationControl::new());
    Ok(generation)
}
#[tauri::command]
fn remote_tab_cancel(tab_id:String,client_generation:u64,generation:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    flow.lock().map_err(|_|"state_unavailable")?.tabs.cancel(&tab_id,client_generation,generation);Ok(())
}
use herdr_readonly_transport::direct_observation::{DirectObservation, ObserveEvent};
#[tauri::command]
async fn remote_observe(mut config:RemoteConfig,canvas:Option<herdr_readonly_transport::ObserveCanvas>,device:bool,host_id:Option<String>,client_generation:u64,on_event:Channel<ObserveEvent>,state:State<'_,Mutex<AttemptGate>>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,pairing:State<'_,PairingState>,hosts:State<'_,Hosts>,nodes:State<'_,network_nodes::Nodes>,ops:State<'_,network_identity::Operations>,app:tauri::AppHandle)->Result<(),String> {
    let canvas=canvas.unwrap_or_default().validate().map_err(str::to_string)?;
    let network_lease=ops.enter()?;
    if device {
        let current=pairing.current.lock().map_err(|_|"state_unavailable")?;
        let p=current.as_ref().ok_or("pairing_missing")?;
        hosts.review_device_host(host_id.as_deref(),p.local_handle(),&Target::from_config(&config))?;
    }
    let (dialer,node_binding):(Box<dyn herdr_readonly_transport::transport::Dialer>,Option<herdr_readonly_transport::mobile_nodes::Binding>)=if let Some(id)=&host_id {
        let record=hosts.get(id)?;if !record.enabled || record.retired || record.target!=Target::from_config(&config){return Err("host_selection_changed".into());}
        let profile=hosts.route(&record)?;
        match network_nodes::select_route(profile.as_ref())? {
            network_nodes::RouteKind::System=>(Box::new(herdr_readonly_transport::transport::SystemDialer),None),
            network_nodes::RouteKind::Overlay=>{let (dialer,binding)=nodes.route(&app,profile.as_ref().ok_or("network_profile_missing")?).await?;(dialer,Some(binding))}
        }
    }else{(Box::new(herdr_readonly_transport::transport::SystemDialer),None)};
    let (generation,cancel)={
        let mut f=flow.lock().map_err(|_|"state_unavailable")?;
        if let Some(id) = &host_id {
            let record = hosts.get(id)?;
            if !record.enabled || record.retired || record.target != Target::from_config(&config) {
                return Err("host_selection_changed".into());
            }
            // Recheck the selected public binding before acquiring the attempt.
            let selected=hosts.route(&record)?;
            if selected.as_ref().map(|p|(p.id.as_str(),p.revision)) != node_binding.as_ref().map(|b|(b.profile_id(),b.profile_revision())) {return Err("host_selection_changed".into());}
        }
        if f.tabs.len()>0 {return Err("connection_active".into());}
        if pairing.restore_required.load(Ordering::SeqCst) {return Err("host_restore_required".into());}
        let mut g=state.lock().map_err(|_|"state_unavailable")?;
        let attempt = f.begin(client_generation,&mut g).map_err(str::to_string)?;
        f.host_id = host_id.clone(); f.node_binding=node_binding;
        attempt
    };
    let device_auth=if device {
        let lease=pairing.enter();
        if let Err(e)=lease { let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.finish(client_generation,generation,&mut g); return Err(e); }
        let _lease=lease.unwrap();
        let result=(|| -> Result<_,String> {
            let mut current=pairing.current.lock().map_err(|_|"state_unavailable")?;
            let p=current.as_mut().ok_or("pairing_missing")?;
            hosts.review_device_host(host_id.as_deref(),p.local_handle(),&Target::from_config(&config))?;
            p.begin(&config).map_err(str::to_string)
        })();
        match result { Ok(v)=>Some(v), Err(e)=> { let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.finish(client_generation,generation,&mut g); return Err(e.into()); } }
    } else { None };
    drop(network_lease);
    config.observe_canvas=canvas;
    let pair_progress=pairing.current.clone();
    let progress=Arc::new(move |stage| { if device && stage=="authenticated" { if let Ok(mut p)=pair_progress.lock() { if let Some(p)=p.as_mut() { p.finish(true); } } } });
    let direct=DirectObservation::new(generation,cancel);
    let recovery={
        let mut f=flow.lock().map_err(|_|"state_unavailable")?;
        f.direct=Some(direct.clone());
        f.recovery.clone().unwrap_or_else(herdr_readonly_transport::recovery::Recovery::disabled)
    };
    let emit=Arc::new(move |event| on_event.send(event).map_err(|_|"client_closed"));
    let result=direct.run(config,device_auth,Arc::new(Audit::default()),progress,emit,recovery,dialer.as_ref()).await;
    if device { if let Ok(mut p)=pairing.current.lock() { if let Some(p)=p.as_mut() { p.finish(false); } } }
    let accepted={ let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; f.finish(client_generation,generation,&mut g) };
    if !accepted {return Err("cancelled".into());}
    result.map_err(str::to_string)
}
fn current_input(flow:&Mutex<RemoteFlow>,generation:u64)->Result<Arc<herdr_readonly_transport::input::LiveInput>,String> {
    let f=flow.lock().map_err(|_|"state_unavailable")?;
    f.direct.as_ref().ok_or("input_stale")?.input(generation).map_err(str::to_string)
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
async fn remote_input_send(generation:u64,epoch:u64,bytes:Vec<u8>,draft:bool,flow:State<'_,Arc<Mutex<RemoteFlow>>>) -> Result<serde_json::Value,String> {
    use herdr_readonly_transport::input::SendOutcome;
    let input=current_input(&flow,generation)?;
    let outcome = input.send(epoch, bytes, draft).await.map_err(str::to_string)?;
    Ok(match outcome {
        SendOutcome::Accepted(receipt) => serde_json::json!({"status":"accepted","receipt":receipt}),
        SendOutcome::Rejected => serde_json::json!({"status":"rejected"}),
        SendOutcome::RecoveryLocked { receipt: Some(receipt) } =>
            serde_json::json!({"status":"accepted","receipt":receipt,"recoveryRequired":true}),
        SendOutcome::RecoveryLocked { receipt: None } =>
            serde_json::json!({"status":"rejected","recoveryRequired":true}),
        SendOutcome::Unknown => serde_json::json!({"status":"unknown"}),
    })
}
#[tauri::command]
fn remote_select(generation:u64,epoch:u64,revision:u64,pane_id:String,terminal_id:String,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let f=flow.lock().map_err(|_|"state_unavailable")?;
    f.direct.as_ref().ok_or("stale_selection")?.select(generation,epoch,revision,pane_id,terminal_id).map_err(str::to_string)
}
#[tauri::command]
fn remote_ack(generation:u64,epoch:u64,seq:u64,flow:State<'_,Arc<Mutex<RemoteFlow>>>)->Result<(),String> {
    let f=flow.lock().map_err(|_|"state_unavailable")?;
    f.direct.as_ref().ok_or("stale_ack")?.ack(generation,epoch,seq).map_err(str::to_string)
}
#[tauri::command]
fn remote_cancel(client_generation:u64,state:State<'_,Mutex<AttemptGate>>,flow:State<'_,Arc<Mutex<RemoteFlow>>>,pairing:State<'_,PairingState>)->Result<(),String> {
    let mut f=flow.lock().map_err(|_|"state_unavailable")?; let mut g=state.lock().map_err(|_|"state_unavailable")?; if f.owner==Some(client_generation) { if let Some(p)=pairing.current.lock().map_err(|_|"state_unavailable")?.as_mut() { if p.state=="connecting" {p.cancel();} } } f.cancel(client_generation,&mut g); Ok(())
}
#[cfg(target_os="windows")]
struct UnavailableKeyStore;
#[cfg(target_os="windows")]
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
#[cfg(target_os="ios")]
mod ios_keys;
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder=tauri::Builder::default();
    #[cfg(any(target_os="linux",target_os="macos"))]
    let builder=builder.manage(PairingState::new(Arc::new(herdr_readonly_transport::pairing::VolatileKeyStore::default())));
    #[cfg(target_os="windows")]
    let builder=builder.manage(PairingState::new(Arc::new(UnavailableKeyStore)));
    #[cfg(target_os="android")]
    let builder=builder.plugin(android_keys::init()).plugin(camera::android_plugin()).plugin(config_document::android_plugin()).plugin(clipboard::android_plugin()).plugin(terminal_keyboard::android_plugin());
    #[cfg(target_os="ios")]
    let builder=builder.plugin(ios_keys::init());
    builder
        .manage(Mutex::new(Streams::default()))
        .manage(Mutex::new(AttemptGate::default()))
        .manage(Hosts::default())
        .manage(network_identity::Operations::default())
        .manage(network_nodes::Nodes::default())
        .manage(config_exchange::Transfers::default())
        .setup(|app| {
            let recovery=app.path().app_local_data_dir().ok().map(|p|herdr_readonly_transport::recovery::Recovery::open(p.join("remote-input-v1"))).unwrap_or_else(herdr_readonly_transport::recovery::Recovery::disabled);
            let flow=RemoteFlow {recovery:Some(recovery),..Default::default()};
            app.manage(Arc::new(Mutex::new(flow))); Ok(())
        })
        .invoke_handler(tauri::generate_handler![fixture_begin,fixture_next,fixture_ack,fixture_cancel,remote_read_once,remote_tab_reserve,remote_tab_cancel,remote_tab_commands::remote_tab_observe,remote_tab_commands::remote_tab_ack,remote_tab_commands::remote_tab_select,remote_tab_commands::remote_tab_control,remote_tab_commands::remote_tab_visible,remote_tab_commands::remote_tab_input_mode,remote_tab_commands::remote_tab_input_recover,remote_tab_commands::remote_tab_input_send,remote_observe,remote_select,remote_ack,remote_cancel,remote_input_mode,remote_input_recover,remote_input_send,pair_create,pair_copy::pair_copy_request,pair_accept,pair_cancel,pair_reset,pair_scan_response,host_init,host_list,host_save,host_new,host_select,host_restore,host_update,host_remove,host_cleanup_retry,preferences_save,network_list,network_save,network_delete,network_bind,network_identity_status,network_identity_write,network_node_status,network_node_start,network_node_stop,network_node_login,network_node_login_status,network_node_open_auth,
            mobile_clipboard_read_text,terminal_keyboard::mobile_terminal_keyboard,config_document_platform,config_document_open,config_document_save,config_export,config_preview,config_apply,config_discard])
        .run(tauri::generate_context!())
        .expect("Tauri probe startup failed");
}
