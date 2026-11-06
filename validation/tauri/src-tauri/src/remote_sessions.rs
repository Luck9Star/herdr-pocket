//! Tab-owned remote attempts. Cancelled attempts retain capacity until their task settles.
use std::{collections::HashMap, sync::Arc};
use herdr_readonly_transport::{AttemptGate, Cancellation, input::LiveInput, mobile_nodes::Binding};
use tokio::sync::oneshot;

#[derive(Default)]
pub struct Session {
    pub gate: AttemptGate,
    pub owner: u64,
    pub generation: u64,
    attempt: u64,
    cancellation: Option<Cancellation>,
    claimed: bool,
    pub host_id: Option<String>,
    pub record: Option<crate::hosts::Record>,
    pub node_binding: Option<Binding>,
    pub control: Option<herdr_readonly_transport::ObservationControl>,
    pub select: Option<(u64, oneshot::Sender<String>)>,
    pub ack: Option<(u64, u64, u64, oneshot::Sender<()>)>,
    pub input: Option<(u64, u64, Arc<LiveInput>)>,
}

#[derive(Default)]
pub struct Sessions { entries: HashMap<String, Session>, next: u64, pub focus: Option<(String,u64,u64,u64)>, pub visible: Option<(String,u64,u64)> }
impl Sessions {
    pub fn begin(&mut self, tab: &str, owner: u64, host: Option<String>, binding: Option<Binding>) -> Result<(u64, Cancellation), &'static str> {
        if tab.is_empty() || tab.len() > 64 || !tab.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_') || owner == 0 {return Err("invalid_tab");}
        if self.entries.contains_key(tab) {return Err("tab_busy");}
        if self.entries.len() >= 8 {return Err("tab_capacity");}
        let mut session = Session {owner, host_id:host, node_binding:binding, ..Session::default()};
        let next=self.next.checked_add(1).ok_or("generation_exhausted")?;
        let (attempt,cancel) = session.gate.begin()?;
        session.generation=next;session.attempt=attempt;session.cancellation=Some(cancel.clone());self.next=next;
        self.entries.insert(tab.to_owned(), session);
        Ok((next,cancel))
    }
    pub fn get(&self, tab:&str)->Option<&Session> {self.entries.get(tab)}
    pub fn get_mut(&mut self, tab:&str)->Option<&mut Session> {self.entries.get_mut(tab)}
    pub fn claim(&mut self, tab:&str, owner:u64, generation:u64)->Result<Cancellation,&'static str> {
        let s=self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;
        if s.claimed {return Err("tab_busy");}
        let cancel=s.cancellation.as_ref().ok_or("tab_stale")?.clone();
        if cancel.is_cancelled(){return Err("cancelled");}
        s.claimed=true;Ok(cancel)
    }
    pub fn cancel(&mut self, tab:&str, owner:u64, generation:u64) {
        if self.focus.as_ref().is_some_and(|(id,o,g,_)|id==tab && *o==owner && *g==generation) {self.focus=None;}
        if self.visible.as_ref().is_some_and(|(id,o,g)|id==tab && *o==owner && *g==generation) {self.visible=None;}
        let mut release=false;
        if let Some(s)=self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation) {
            release=!s.claimed;
            if let Some((_, _, input))=s.input.take() {input.invalidate();}
            s.select.take();s.ack.take();s.gate.cancel();
        }
        if release {self.entries.remove(tab);}
    }
    pub fn cancel_hosts(&mut self, ids:&[String]) {
        let targets:Vec<_>=self.entries.iter().filter(|(_,s)|s.host_id.as_ref().is_some_and(|id|ids.contains(id))).map(|(id,s)|(id.clone(),s.owner,s.generation)).collect();
        for (id,owner,generation) in targets {self.cancel(&id,owner,generation)}
    }
    pub fn cancel_handle(&mut self, handle:&str) {
        let targets:Vec<_>=self.entries.iter().filter(|(_,s)|s.record.as_ref().and_then(|r|r.pairing.as_ref()).is_some_and(|p|p.handle==handle)).map(|(id,s)|(id.clone(),s.owner,s.generation)).collect();
        for (id,owner,generation) in targets {self.cancel(&id,owner,generation)}
    }
    pub fn cancel_binding(&mut self, binding:&Binding) {
        let targets:Vec<_>=self.entries.iter().filter(|(_,s)|s.node_binding.as_ref()==Some(binding)).map(|(id,s)|(id.clone(),s.owner,s.generation)).collect();
        for (id,owner,generation) in targets {self.cancel(&id,owner,generation)}
    }
    pub fn finish(&mut self, tab:&str,owner:u64,generation:u64)->bool {
        let Some(s)=self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation) else {return false};
        let accepted=s.gate.finish(s.attempt);
        if let Some((_,_,input))=s.input.take(){input.invalidate();}
        if self.focus.as_ref().is_some_and(|(id,o,g,_)|id==tab && *o==owner && *g==generation) {self.focus=None;}
        if self.visible.as_ref().is_some_and(|(id,o,g)|id==tab && *o==owner && *g==generation) {self.visible=None;}
        self.entries.remove(tab);accepted
    }
    pub fn len(&self)->usize {self.entries.len()}
    pub fn owners(&self)->Vec<(String,u64,u64,Option<String>)> {let mut result:Vec<_>=self.entries.iter().map(|(id,s)|(id.clone(),s.owner,s.generation,s.host_id.clone())).collect();result.sort();result}
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn cancelled_slot_stays_reserved_and_cannot_cancel_other_tab() {
        let mut s=Sessions::default();
        let (g,c)=s.begin("a",1,Some("one".into()),None).unwrap();s.claim("a",1,g).unwrap();
        let (_,other)=s.begin("b",1,Some("two".into()),None).unwrap();
        for i in 2..8 {s.begin(&format!("t{i}"),1,None,None).unwrap();}
        s.cancel("a",1,g);assert!(c.is_cancelled());assert!(!other.is_cancelled());
        assert!(matches!(s.begin("new",1,None,None),Err("tab_capacity")));
        assert!(!s.finish("a",1,g));assert!(s.begin("new",1,None,None).is_ok());
    }
    #[test] fn affected_host_only_and_late_owner_are_isolated() {
        let mut s=Sessions::default();let (g,a)=s.begin("a",1,Some("one".into()),None).unwrap();s.claim("a",1,g).unwrap();
        let (_,b)=s.begin("b",1,Some("two".into()),None).unwrap();
        s.cancel_hosts(&["one".into()]);assert!(a.is_cancelled());assert!(!b.is_cancelled());
        assert!(!s.finish("a",2,g));assert!(s.get("a").is_some());
    }
    #[test] fn precancelled_reservation_cannot_attach_to_reused_tab() {
        let mut s=Sessions::default();let (old,_)=s.begin("a",1,None,None).unwrap();
        s.cancel("a",1,old);let (new,_)=s.begin("a",1,None,None).unwrap();
        assert!(matches!(s.claim("a",1,old),Err("tab_stale")));
        assert!(!s.finish("a",1,old));assert!(s.claim("a",1,new).is_ok());
    }

}
