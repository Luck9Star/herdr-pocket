//! Strict public metadata and shared-device command validation.
use serde::{Deserialize, Serialize};
use crate::network_identity::valid_handle;

#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
pub struct Device { pub handle:String, pub instance_id:String }
#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(deny_unknown_fields)]
pub struct Pending { pub handle:String, pub phase:String }
#[derive(Clone,Debug,Serialize,Deserialize,PartialEq,Eq)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
pub struct Status { pub available:bool, pub device:Option<Device>, pub pending_creation:Option<Pending>, pub pending_deletion:Option<Pending> }
impl Status {
 pub fn unavailable()->Self {Self{available:false,device:None,pending_creation:None,pending_deletion:None}}
 pub fn checked(value:serde_json::Value)->Result<Self,String> {
  let obj=value.as_object().ok_or("zerotier_device_unavailable")?;
  if obj.len()!=4 || !["available","device","pendingCreation","pendingDeletion"].iter().all(|k|obj.contains_key(*k)){return Err("zerotier_device_unavailable".into());}
  let s:Self=serde_json::from_value(value).map_err(|_|"zerotier_device_unavailable")?;
  if s.device.as_ref().is_some_and(|d|!d.valid()) || s.pending_creation.as_ref().is_some_and(|p|!valid_handle(&p.handle)||!matches!(p.phase.as_str(),"record-present"|"record-pending"|"finishing")) || s.pending_deletion.as_ref().is_some_and(|p|!valid_handle(&p.handle)||!matches!(p.phase.as_str(),"record-present"|"record-removed"|"finishing")) || [s.device.is_some(),s.pending_creation.is_some(),s.pending_deletion.is_some()].into_iter().filter(|x|*x).count()>1 || (!s.available && (s.device.is_some() || s.pending_creation.is_some() || s.pending_deletion.is_some())) {return Err("zerotier_device_unavailable".into());} Ok(s)
 }
}
impl Device {fn valid(&self)->bool{valid_handle(&self.handle)&&valid_handle(&self.instance_id)}}
#[derive(Deserialize)]
#[serde(rename_all="camelCase",deny_unknown_fields)]
pub struct WriteRequest {pub action:String,pub catalog_revision:String,pub profile_ids:Vec<String>,pub host_ids:Vec<String>,pub handle:Option<String>,pub instance_id:Option<String>,pub expected_phase:Option<String>}
pub fn parse_write(value:serde_json::Value)->Result<WriteRequest,String>{
 let obj=value.as_object().ok_or("invalid_zerotier_device_request")?;
 if obj.len()!=7 || !["action","catalogRevision","profileIds","hostIds","handle","instanceId","expectedPhase"].iter().all(|key|obj.contains_key(*key)){return Err("invalid_zerotier_device_request".into());}
 let request:WriteRequest=serde_json::from_value(value).map_err(|_|"invalid_zerotier_device_request")?;
 validate_action(&request.action,request.handle.as_deref(),request.instance_id.as_deref(),request.expected_phase.as_deref())?;
 if request.catalog_revision.is_empty() || request.profile_ids.len()>32 || request.host_ids.len()>32 {return Err("invalid_zerotier_device_request".into());} Ok(request)
}
pub fn validate_action(action:&str,handle:Option<&str>,instance:Option<&str>,phase:Option<&str>)->Result<(),String>{
 match (action,handle,instance,phase) {
  ("create",None,None,None)=>Ok(()),
  ("forget",Some(h),Some(i),None) if valid_handle(h)&&valid_handle(i)=>Ok(()),
  ("recoverPendingCreation",Some(h),None,Some("record-present"|"finishing")) if valid_handle(h)=>Ok(()),
  ("discardPendingCreation",Some(h),None,Some("record-pending"|"finishing")) if valid_handle(h)=>Ok(()),
  ("recoverPendingDeletion",Some(h),None,Some("record-present"|"record-removed"|"finishing")) if valid_handle(h)=>Ok(()),
  _=>Err("invalid_zerotier_device_request".into())
 }
}
#[cfg(any(test,target_os="android"))]
use std::sync::atomic::{AtomicU64,Ordering};
#[cfg(any(test,target_os="android"))]
static NEXT_OPERATION_ID:AtomicU64=AtomicU64::new(0);
#[cfg(any(test,target_os="android"))]
fn next_id(counter:&AtomicU64)->Result<i64,String>{
 counter.fetch_update(Ordering::SeqCst,Ordering::SeqCst,|n|if n < i64::MAX as u64 {Some(n+1)}else{None}).map(|old|(old+1) as i64).map_err(|_|"zerotier_device_unavailable".into())
}
#[cfg(any(test,target_os="android"))]
pub fn next_operation_id()->Result<i64,String>{next_id(&NEXT_OPERATION_ID)}

// An uncertain IPC result cannot release the catalog lock while Java may still mutate.
#[cfg(any(test,target_os="android"))]
pub fn wait_for_fence(mut fence:impl FnMut()->Result<bool,String>,mut pause:impl FnMut()) {
 loop {if matches!(fence(),Ok(true)){return} pause();}
}
#[cfg(any(test,target_os="android"))]
pub fn settle_with_fence<T>(invoke:impl FnOnce()->Result<T,String>,fence:impl FnMut()->Result<bool,String>,pause:impl FnMut())->Result<T,String>{
 let result=invoke();wait_for_fence(fence,pause);result
}
pub fn checked_write(action:&str,expected:Option<&str>,value:serde_json::Value)->Result<Option<Device>,String>{
 if matches!(action,"forget"|"discardPendingCreation"|"recoverPendingDeletion") {return if value.is_null(){Ok(None)}else{Err("zerotier_device_result_unknown".into())};}
 let d:Device=serde_json::from_value(value).map_err(|_|"zerotier_device_result_unknown")?;
 if !d.valid() || (action=="recoverPendingCreation" && Some(d.handle.as_str())!=expected){return Err("zerotier_device_result_unknown".into());}Ok(Some(d))
}
#[cfg(test)] mod tests {
 use super::*;
 const H:&str="11111111-1111-4111-8111-111111111111";const I:&str="22222222-2222-4222-8222-222222222222";
 #[test] fn requests_and_replies_fail_closed(){assert!(validate_action("create",None,None,None).is_ok());assert!(validate_action("forget",Some(H),Some(I),None).is_ok());assert!(validate_action("forget",Some(H),None,None).is_err());assert!(validate_action("create",Some(H),None,None).is_err());assert!(validate_action("recoverPendingCreation",Some(&H.to_uppercase().replace('1',"A")),None,Some("finishing")).is_err());let device=serde_json::json!({"handle":H,"instanceId":I});assert!(checked_write("recoverPendingCreation",Some(I),device.clone()).is_err());assert!(checked_write("create",None,device).is_ok());assert!(checked_write("forget",Some(H),serde_json::json!({})).is_err());}
 #[test] fn pending_phase_matrix_is_exact(){
  for (action,allowed) in [("recoverPendingCreation",vec!["record-present","finishing"]),("discardPendingCreation",vec!["record-pending","finishing"]),("recoverPendingDeletion",vec!["record-present","record-removed","finishing"])] {for phase in ["record-present","record-pending","record-removed","finishing","unknown"] {assert_eq!(validate_action(action,Some(H),None,Some(phase)).is_ok(),allowed.contains(&phase),"{action} {phase}");}assert!(validate_action(action,Some(H),Some(I),Some("finishing")).is_err());assert!(validate_action(action,Some(H),None,None).is_err());}
  assert!(validate_action("create",None,None,Some("finishing")).is_err());assert!(validate_action("forget",Some(H),Some(I),Some("finishing")).is_err());assert!(checked_write("recoverPendingDeletion",Some(H),serde_json::Value::Null).is_ok());assert!(checked_write("recoverPendingDeletion",Some(H),serde_json::json!({"handle":H,"instanceId":I})).is_err());
 }
 #[test] fn request_schema_rejects_missing_and_unknown_fields(){let request=serde_json::json!({"action":"create","catalogRevision":"r","profileIds":[],"hostIds":[],"handle":null,"instanceId":null,"expectedPhase":null});assert!(parse_write(request.clone()).is_ok());let mut bad=request.clone();bad["secret"]="no".into();assert!(parse_write(bad).is_err());let mut bad=request;bad.as_object_mut().unwrap().remove("handle");assert!(parse_write(bad).is_err());}
 #[test] fn fence_never_treats_ipc_error_or_pending_as_completion(){let mut values=vec![Err("lost".into()),Ok(false),Ok(true)].into_iter();let mut pauses=0;wait_for_fence(||values.next().unwrap(),||pauses+=1);assert_eq!(pauses,2);}
 #[test] fn sequence_overflow_fails_closed(){let counter=AtomicU64::new(i64::MAX as u64-1);assert_eq!(next_id(&counter).unwrap(),i64::MAX);assert!(next_id(&counter).is_err());assert_eq!(counter.load(Ordering::SeqCst),i64::MAX as u64);}
 #[test] fn unknown_ipc_holds_operation_lease_until_fence_for_both_dispatch_paths(){
  use crate::network_identity::Operations;
  for dispatched in [false,true] {let ops=Operations::default();let lease=ops.enter().unwrap();let mut n=0;let result:settle_result::Result=settle_with_fence(||Err(if dispatched {"after".into()}else{"before".into()}),||{assert!(ops.enter().is_err());n+=1;Ok(n==3)},||{});assert!(result.is_err());assert_eq!(n,3);drop(lease);assert!(ops.enter().is_ok());}
 }
 mod settle_result {pub type Result=std::result::Result<(),String>;}
 #[test] fn status_is_exact_and_consistent(){let good:serde_json::Value=serde_json::from_str(r#"{"available":true,"device":null,"pendingCreation":null,"pendingDeletion":null}"#).unwrap();assert!(Status::checked(good.clone()).is_ok());let mut bad=good.clone();bad["secret"]="x".into();assert!(Status::checked(bad).is_err());let mut bad=good.clone();bad["device"]=serde_json::json!({"handle":H,"instanceId":I});bad["available"]=false.into();assert!(Status::checked(bad).is_err());let mut bad=good;bad["pendingCreation"]=serde_json::json!({"handle":H,"phase":"finishing"});bad["device"]=serde_json::json!({"handle":H,"instanceId":I});assert!(Status::checked(bad).is_err());}
}
