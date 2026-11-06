//! Explicit node lifecycle. No default provider, no join claim, no fallback.
use serde::Serialize;
use herdr_readonly_transport::mobile_nodes::Binding;
use herdr_readonly_transport::mobile_nodes::State;
#[cfg(all(target_os="android",feature="network-easytier"))]
use herdr_readonly_transport::mobile_nodes::MobileNodeService;
#[cfg(all(target_os="android",feature="network-easytier"))]
use std::{sync::Arc,time::Duration};
#[derive(Default)]
pub struct Nodes {
    #[cfg(all(target_os="android",feature="network-easytier"))]
    service:MobileNodeService,
}
#[derive(Serialize)]
pub struct View {state:&'static str,binding:Option<Binding>}
#[cfg_attr(not(any(test,all(target_os="android",feature="network-easytier"))),allow(dead_code))]
fn view(s:herdr_readonly_transport::mobile_nodes::Snapshot)->View {
    View {state:match s.state {
        State::Starting=>"starting",
        State::EngineStarted=>"engine-started",
        State::NeedsLogin=>"needs-login",
        State::NeedsMachineAuth=>"needs-machine-auth",
        State::Running=>"running",
        State::Closing=>"closing",
        State::Stopped=>"stopped",
    },binding:Some(s.binding)}
}
#[cfg_attr(not(any(test,all(target_os="android",feature="network-easytier"))),allow(dead_code))]
fn ready_view(current:Option<herdr_readonly_transport::mobile_nodes::Snapshot>,initialized:bool)->View {
    if current.as_ref().is_some_and(|s|s.state!=State::Stopped) {return view(current.unwrap());}
    if !initialized {return View{state:"unavailable",binding:None};}
    match current {Some(s)=>view(s),None=>View{state:"stopped",binding:None}}
}
pub async fn commit_after_stop<T>(stop:impl std::future::Future<Output=Result<(),String>>,commit:impl FnOnce()->Result<T,String>)->Result<T,String>{stop.await?;commit()}
#[derive(Debug,PartialEq,Eq)]
pub enum RouteKind {System,Overlay}
/// A bound profile can only take the overlay branch; never select System.
pub fn select_route(profile:Option<&crate::networks::NetworkProfile>)->Result<RouteKind,String>{
    let Some(profile)=profile else{return Ok(RouteKind::System)};
    if profile.provider!=crate::networks::Provider::Easytier || !cfg!(all(target_os="android",feature="network-easytier")) {return Err("overlay_provider_unavailable".into());}
    Ok(RouteKind::Overlay)
}
impl Nodes {
 pub async fn status(&self,app:&tauri::AppHandle,id:&str)->Result<View,String> {
    #[cfg(all(target_os="android",feature="network-easytier"))]
    {let _=app;let current=self.service.status_profile(id).await.map_err(str::to_string)?;
     Ok(ready_view(current,herdr_android_network_source::is_initialized()))}
    #[cfg(not(all(target_os="android",feature="network-easytier")))]
    {let _=(app,id);Ok(View{state:"unavailable",binding:None})}
 }
 /// Caller revokes affected SSH first. Cleanup errors leave the mutation blocked.
 pub async fn stop_profile(&self,id:&str)->Result<(),String>{
    #[cfg(all(target_os="android",feature="network-easytier"))]
    {if let Some(s)=self.service.status_profile(id).await.map_err(str::to_string)? {if s.state!=State::Stopped {let stopped=self.service.stop(&s.binding,Duration::from_secs(10)).await.map_err(str::to_string)?;if stopped.state!=State::Stopped{return Err("mobile_node_cleanup_pending".into());}}}Ok(())}
    #[cfg(not(all(target_os="android",feature="network-easytier")))]
    {let _=id;Ok(())}
 }
 pub async fn stop_exact(&self,id:&str,binding:Binding)->Result<(),String>{
    if binding.profile_id()!=id {return Err("mobile_node_binding_mismatch".into());}
    #[cfg(all(target_os="android",feature="network-easytier"))]
    {let stopped=self.service.stop(&binding,Duration::from_secs(10)).await.map_err(str::to_string)?;if stopped.state!=State::Stopped {return Err("mobile_node_cleanup_pending".into());}Ok(())}
    #[cfg(not(all(target_os="android",feature="network-easytier")))]
    {let _=binding;Err("overlay_provider_unavailable".into())}
 }
 #[cfg(all(target_os="android",feature="network-easytier"))]
 pub async fn start(&self,profile:&crate::networks::NetworkProfile,handle:String)->Result<(),String>{
    let crate::networks::Settings::Easytier{network_name,peers}=&profile.settings else{return Err("network_identity_provider_unavailable".into())};
    let binding=Binding::new(profile.id.clone(),profile.revision,network_name.clone(),handle.clone()).map_err(str::to_string)?;
    let source=herdr_android_network_source::AndroidSecureConfigSource::new(profile.id.clone(),profile.revision,network_name.clone(),handle,peers.clone()).map_err(str::to_string)?;
    self.service.start(binding,Arc::new(source),Duration::from_secs(10),herdr_readonly_transport::Cancellation::default()).await.map_err(str::to_string)?;Ok(())
 }
 pub async fn route(&self,app:&tauri::AppHandle,profile:&crate::networks::NetworkProfile)->Result<(Box<dyn herdr_readonly_transport::transport::Dialer>,Binding),String>{
    if profile.provider!=crate::networks::Provider::Easytier {return Err("overlay_provider_unavailable".into());}
    #[cfg(all(target_os="android",feature="network-easytier"))]
    {let app=app.clone();let id=profile.id.clone();let identity=tauri::async_runtime::spawn_blocking(move||crate::android_keys::network_identity(&app,"networkIdentityStatus",&id,"","")).await.map_err(|_|"network_identity_unavailable")??.ok_or("network_identity_missing")?;
     if identity.mode!="PRIVATE"{return Err("network_public_mode_unsupported".into());}
     let crate::networks::Settings::Easytier{network_name,..}=&profile.settings else{return Err("overlay_provider_unavailable".into())};
     let binding=Binding::new(profile.id.clone(),profile.revision,network_name.clone(),identity.handle.clone()).map_err(str::to_string)?;
     let dialer=self.dialer(profile,identity.handle)?;Ok((Box::new(dialer),binding))}
    #[cfg(not(all(target_os="android",feature="network-easytier")))]
    {let _=(app,profile);Err("overlay_provider_unavailable".into())}
 }
 #[cfg(all(target_os="android",feature="network-easytier"))]
 pub fn dialer(&self,profile:&crate::networks::NetworkProfile,handle:String)->Result<herdr_readonly_transport::overlay::OverlayDialer,String>{
    let crate::networks::Settings::Easytier{network_name,..}=&profile.settings else{return Err("network_identity_provider_unavailable".into())};
    let binding=Binding::new(profile.id.clone(),profile.revision,network_name.clone(),handle).map_err(str::to_string)?;
    self.service.dialer(&binding,Duration::from_secs(10)).map_err(str::to_string)
 }
}

#[cfg(test)]
mod tests {
 use super::*;
 #[test] fn default_route_never_falls_back_for_bound_profiles() {
   use crate::networks::{NetworkProfile,Provider,Settings};
   assert_eq!(select_route(None),Ok(RouteKind::System));
   let mut p=NetworkProfile{id:"a".repeat(32),label:"team".into(),provider:Provider::Easytier,enabled:true,revision:1,settings:Settings::Easytier{network_name:"team".into(),peers:vec!["tcp://x:1".into()]}};
   if !cfg!(all(target_os="android",feature="network-easytier")){assert_eq!(select_route(Some(&p)),Err("overlay_provider_unavailable".into()));}
   p.provider=Provider::Tailscale;assert_eq!(select_route(Some(&p)),Err("overlay_provider_unavailable".into()));
 }
 #[test] fn managed_state_wire_preserves_login_and_running_states() {
   use herdr_readonly_transport::mobile_nodes::{BindingProvider,Snapshot};
   let binding=Binding::with_provider(BindingProvider::Tailscale,"a".repeat(32),1,"team".into(),"native-store-ref".into()).unwrap();
   for (state,expected) in [
      (State::Starting,"starting"),(State::EngineStarted,"engine-started"),
      (State::NeedsLogin,"needs-login"),(State::NeedsMachineAuth,"needs-machine-auth"),
      (State::Running,"running"),(State::Closing,"closing"),(State::Stopped,"stopped"),
   ] {
      let wire=serde_json::to_value(view(Snapshot{binding:binding.clone(),state})).unwrap();
      assert_eq!(wire["state"],expected);
      assert_eq!(wire["binding"]["provider"],"tailscale");
      assert_ne!(wire["state"],"ready");
   }
 }
 #[test] fn unavailable_source_does_not_hide_active_old_binding() {
   let b=Binding::new("a".repeat(32),1,"team".into(),"11111111-1111-4111-8111-111111111111".into()).unwrap();
   let active=herdr_readonly_transport::mobile_nodes::Snapshot{binding:b.clone(),state:State::EngineStarted};
   let visible=ready_view(Some(active),false);assert_eq!(visible.state,"engine-started");assert_eq!(visible.binding.unwrap(),b);
   assert_eq!(ready_view(None,false).state,"unavailable");assert_eq!(ready_view(None,true).state,"stopped");
 }
 #[tokio::test] async fn failed_or_unknown_stop_never_commits_profile() {
   let mut committed=false;let result=commit_after_stop(async{Err("mobile_node_cleanup_pending".into())},||{committed=true;Ok(())}).await;
   assert!(result.is_err());assert!(!committed);
   commit_after_stop(async{Ok(())},||{committed=true;Ok(())}).await.unwrap();assert!(committed);
 }
}
