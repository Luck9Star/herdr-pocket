//! Public status only. Secret bytes are never returned to the webview.
use serde::Serialize;
use std::sync::{Arc, atomic::{AtomicBool,Ordering}};
#[derive(Default)]
pub struct Operations(Arc<AtomicBool>);
pub struct Lease(Arc<AtomicBool>);
impl Drop for Lease {fn drop(&mut self){self.0.store(false,Ordering::Release);}}
impl Operations {pub fn enter(&self)->Result<Lease,String>{self.0.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|"network_identity_busy")?;Ok(Lease(self.0.clone()))}}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub struct Status {pub supported:bool,pub available:bool,pub present:bool,pub mode:Option<String>,pub handle:Option<String>}
impl Status {#[cfg(target_os="android")] pub fn from_metadata(metadata:Option<Metadata>)->Self {Self{supported:true,available:true,present:metadata.is_some(),mode:metadata.as_ref().map(|m|m.mode.clone()),handle:metadata.map(|m|m.handle)}}}
impl Status {pub fn unsupported()->Self{Self{supported:false,available:false,present:false,mode:None,handle:None}}}
#[cfg(target_os="android")]
#[derive(Clone)]
pub struct Metadata {pub mode:String,pub handle:String}
pub fn valid_handle(s:&str)->bool {
 let b=s.as_bytes();b.len()==36 && b.iter().enumerate().all(|(i,c)|match i {8|13|18|23=>*c==b'-',14=>*c==b'4',19=>matches!(*c,b'8'|b'9'|b'a'|b'b'),_=>c.is_ascii_digit() || (b'a'..=b'f').contains(c)})
}
pub fn validate_expected_handle(action:&str,handle:Option<&str>)->Result<(),String> {match (action,handle) {("create",None)=>Ok(()),("delete",Some(h)) if valid_handle(h)=>Ok(()),_=>Err("invalid_network_identity".into())}}
pub fn validate_input(mode:&str,secret:&str)->Result<(),String> {
 if secret.len()>1024 || secret.contains('\0') || !matches!((mode,secret.is_empty()),("PRIVATE",false)|("PUBLIC_NO_SECRET",true)) {return Err("invalid_network_identity".into());}Ok(())
}
#[cfg(test)]
mod tests {use super::*;
 #[test] fn modes_and_secret_limits_are_explicit(){assert!(validate_input("PRIVATE","secret").is_ok());assert!(validate_input("PUBLIC_NO_SECRET","").is_ok());for (mode,secret) in [("PRIVATE",""),("PUBLIC_NO_SECRET","secret"),("UNKNOWN","")]{assert!(validate_input(mode,secret).is_err());}assert!(validate_input("PRIVATE",&"x".repeat(1025)).is_err());assert!(validate_input("PRIVATE","a\0b").is_err());assert!(validate_input("PRIVATE",&"中".repeat(341)).is_ok());assert!(validate_input("PRIVATE",&"中".repeat(342)).is_err());}
 #[test] fn delete_requires_frozen_valid_uuid(){let a="11111111-1111-4111-8111-111111111111";assert!(validate_expected_handle("delete",Some(a)).is_ok());assert!(validate_expected_handle("delete",None).is_err());assert!(validate_expected_handle("delete",Some("not-a-handle")).is_err());assert!(validate_expected_handle("create",Some(a)).is_err());}
 #[test] fn operations_are_serial_and_release_after_unknown_result(){let a=Operations::default();let lease=a.enter().unwrap();assert!(a.enter().is_err());drop(lease);assert!(a.enter().is_ok());}
}
