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
    pub closing: bool,
    // Visible slots are per-tab: several tabs may observe at once (desktop split view).
    pub visible: bool,
    pub host_id: Option<String>,
    pub record: Option<crate::hosts::Record>,
    pub node_binding: Option<Binding>,
    pub control: Option<herdr_readonly_transport::ObservationControl>,
    pub select: Option<(u64, u64, oneshot::Sender<herdr_readonly_transport::DashboardTarget>)>,
    pub dashboard:crate::dashboard_watch::DashboardReview,
    pub selected:Option<herdr_readonly_transport::DashboardTarget>,
    pub ack: Option<(u64, u64, u64, oneshot::Sender<()>)>,
    pub input: Option<(u64, u64, Arc<LiveInput>)>,
}

impl Session {
    pub fn select_dashboard(&mut self,generation:u64,epoch:u64,revision:u64,pane:String,terminal:String)->Result<(),&'static str> {
        if self.generation!=generation || self.control.as_ref().is_none_or(|c|c.snapshot().epoch!=epoch) ||
            !self.select.as_ref().is_some_and(|(g,e,_)|*g==generation && *e==epoch) {return Err("stale_selection");}
        let target=self.dashboard.select(epoch,revision,pane,terminal)?;
        self.selected=Some(target.clone());
        self.select.take().unwrap().2.send(target).map_err(|_|"cancelled")
    }
}

#[derive(Clone)]
pub struct StopPlan {
    pub targets:Vec<(String,u64,u64)>,
    pub controls:Vec<herdr_readonly_transport::ObservationControl>,
    pub node:Option<herdr_readonly_transport::mobile_nodes::NodeAttempt>,
    pub legacy:Option<(u64,u64)>,
}
struct Stopping {binding:Binding,plan:StopPlan,active:bool}
#[derive(Default)]
/// Slot model: `visible` is a per-session flag (many tabs may observe simultaneously);
/// `focus` stays a single slot — at most one tab may hold input focus at any time.
pub struct Sessions { entries: HashMap<String, Session>, next: u64, stopping: Vec<Stopping>, pub focus: Option<(String,u64,u64,u64)> }
impl Sessions {
    pub fn begin(&mut self, tab: &str, owner: u64, host: Option<String>, binding: Option<Binding>) -> Result<(u64, Cancellation), &'static str> {
        if tab.is_empty() || tab.len() > 64 || !tab.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_') || owner == 0 {return Err("invalid_tab");}
        if binding.as_ref().is_some_and(|b|self.is_stopping(b)) {return Err("mobile_node_stop_pending");}
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
    // A visibility claim is only valid for the exact owner/generation that registered it.
    pub fn is_visible(&self, tab:&str, owner:u64, generation:u64)->bool {self.entries.get(tab).is_some_and(|s|s.owner==owner && s.generation==generation && s.visible)}
    pub fn set_visible(&mut self, tab:&str, owner:u64, generation:u64)->Result<(),&'static str> {self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation && !s.closing).map(|s|s.visible=true).ok_or("tab_stale")}
    // Input focus is unique: entering a write mode takes it, observe mode releases it.
    pub fn take_focus(&mut self, key:(String,u64,u64,u64))->Result<(),&'static str> {
        if self.focus.as_ref().is_some_and(|active|active!=&key) {return Err("focus_busy");}
        self.focus=Some(key);Ok(())
    }
    pub fn release_focus(&mut self, key:&(String,u64,u64,u64)) {if self.focus.as_ref()==Some(key) {self.focus=None;}}
    // Input sends require visibility plus the exact focused epoch; non-focused tabs get input_stale.
    pub fn input_guard(&self, tab:&str, owner:u64, generation:u64, epoch:u64)->Result<(),&'static str> {
        if !self.is_visible(tab,owner,generation) || !self.focus.as_ref().is_some_and(|(id,o,g,e)|id==tab && *o==owner && *g==generation && *e==epoch) {return Err("input_stale");}
        Ok(())
    }
    pub fn claim(&mut self, tab:&str, owner:u64, generation:u64)->Result<Cancellation,&'static str> {
        let s=self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;
        if s.claimed {return Err("tab_busy");}
        let cancel=s.cancellation.as_ref().ok_or("tab_stale")?.clone();
        if cancel.is_cancelled(){return Err("cancelled");}
        s.claimed=true;Ok(cancel)
    }
    pub fn cancel(&mut self, tab:&str, owner:u64, generation:u64) {
        if self.focus.as_ref().is_some_and(|(id,o,g,_)|id==tab && *o==owner && *g==generation) {self.focus=None;}
        let mut release=false;
        if let Some(s)=self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation) {
            release=!s.claimed;
            s.visible=false;
            if let Some((_, _, input))=s.input.take() {input.invalidate();}
            s.select.take();s.ack.take();s.gate.cancel();
        }
        if release {self.entries.remove(tab);}
    }
    pub fn prepare_close(&mut self, tab:&str, owner:u64, generation:u64)->Result<Option<herdr_readonly_transport::ObservationControl>,&'static str> {
        let s=self.entries.get(tab).filter(|s|s.owner==owner && s.generation==generation).ok_or("tab_stale")?;
        if s.closing {return Err("tab_close_pending");}
        if s.node_binding.as_ref().is_some_and(|binding|self.is_stopping(binding)) {
            return Err("mobile_node_stop_pending");
        }
        // An unclaimed reservation has never acquired a transport.
        if !s.claimed {self.cancel(tab,owner,generation);return Ok(None);}
        let control=s.control.clone().ok_or("tab_close_unconfirmed")?;
        self.entries.get_mut(tab).unwrap().closing=true;
        // Keep the ACK and input ownership until ObservationControl retires
        // them. Dropping an ACK here can exit the SSH task before graceful close.
        self.clear_visible(tab,owner,generation);
        Ok(Some(control))
    }
    pub fn cancel_hosts(&mut self, ids:&[String]) {
        let targets:Vec<_>=self.entries.iter().filter(|(_,s)|s.host_id.as_ref().is_some_and(|id|ids.contains(id))).map(|(id,s)|(id.clone(),s.owner,s.generation)).collect();
        for (id,owner,generation) in targets {self.cancel(&id,owner,generation)}
    }
    pub fn cancel_handle(&mut self, handle:&str) {
        let targets:Vec<_>=self.entries.iter().filter(|(_,s)|s.record.as_ref().and_then(|r|r.pairing.as_ref()).is_some_and(|p|p.handle==handle)).map(|(id,s)|(id.clone(),s.owner,s.generation)).collect();
        for (id,owner,generation) in targets {self.cancel(&id,owner,generation)}
    }
    pub fn stop_binding(&mut self,binding:&Binding,node:Option<herdr_readonly_transport::mobile_nodes::NodeAttempt>,legacy:Option<(u64,u64)>)->Result<StopPlan,&'static str> {
        if let Some(stop)=self.stopping.iter_mut().find(|s|s.binding==*binding) {
            if stop.active {return Err("mobile_node_stop_pending");}
            stop.active=true;
            let mut plan=stop.plan.clone();plan.controls.clear();return Ok(plan);
        }
        let targets:Vec<_>=self.entries.iter().filter(|(_,s)|s.node_binding.as_ref()==Some(binding)).map(|(id,s)|(id.clone(),s.owner,s.generation)).collect();
        let mut controls=Vec::new();
        for (id,owner,generation) in &targets {
            if self.focus.as_ref().is_some_and(|(tab,o,g,_)|tab==id && o==owner && g==generation) {self.focus=None;}
            if let Some(s)=self.entries.get_mut(id) {
                if s.closing {continue;} // Still wait for the exact pinned slot below.
                s.visible=false;
                if let Some(control)=&s.control {controls.push(control.clone());} else {s.gate.cancel();}
                if let Some((_,_,input))=s.input.take() {input.invalidate();}
                s.select.take();s.ack.take();
            }
            if self.entries.get(id).is_some_and(|s|!s.claimed) {self.cancel(id,*owner,*generation);}
        }
        let plan=StopPlan {targets,controls,node,legacy};
        self.stopping.push(Stopping {binding:binding.clone(),plan:plan.clone(),active:true});Ok(plan)
    }
    pub fn stop_settled(&self,targets:&[(String,u64,u64)])->bool {
        targets.iter().all(|(id,owner,generation)|self.entries.get(id).is_none_or(|s|s.owner!=*owner || s.generation!=*generation))
    }
    pub fn is_stopping(&self,binding:&Binding)->bool {self.stopping.iter().any(|s|s.binding==*binding)}
    pub fn defer_stop(&mut self,binding:&Binding) {if let Some(stop)=self.stopping.iter_mut().find(|s|s.binding==*binding) {stop.active=false;}}
    pub fn finish_stop(&mut self,binding:&Binding) {self.stopping.retain(|s|s.binding!=*binding);}
    pub fn cancel_binding(&mut self, binding:&Binding) {
        let targets:Vec<_>=self.entries.iter().filter(|(_,s)|s.node_binding.as_ref()==Some(binding)).map(|(id,s)|(id.clone(),s.owner,s.generation)).collect();
        for (id,owner,generation) in targets {self.cancel(&id,owner,generation)}
    }
    pub fn finish(&mut self, tab:&str,owner:u64,generation:u64)->bool {
        let Some(s)=self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation) else {return false};
        let accepted=s.gate.finish(s.attempt);
        if let Some((_,_,input))=s.input.take(){input.invalidate();}
        if self.focus.as_ref().is_some_and(|(id,o,g,_)|id==tab && *o==owner && *g==generation) {self.focus=None;}
        self.entries.remove(tab);accepted
    }
    pub fn len(&self)->usize {self.entries.len()}
    pub fn owners(&self)->Vec<(String,u64,u64,Option<String>)> {let mut result:Vec<_>=self.entries.iter().map(|(id,s)|(id.clone(),s.owner,s.generation,s.host_id.clone())).collect();result.sort();result}
    // Pause hides one tab from the visibility set without retiring its session
    // (a later resume re-attaches). Clears the tab's focus if it holds the
    // slot; returns whether the (id,owner,generation) triple matched, so the
    // caller can scope its own lease cleanup. This keeps every `visible`
    // write inside this file. The input itself is NOT invalidated here:
    // control.pause() already retired it before this runs.
    pub fn clear_visible(&mut self, tab:&str, owner:u64, generation:u64)->bool {
        if self.focus.as_ref().is_some_and(|(id,o,g,_)|id==tab && *o==owner && *g==generation) {self.focus=None;}
        if let Some(s)=self.entries.get_mut(tab).filter(|s|s.owner==owner && s.generation==generation) {s.visible=false;true} else {false}
    }
}

// The single place ordering focus arbitration against the transport-mode
// switch. Focus MUST be arbitrated BEFORE the transport mutation:
// LiveInput::set_mode has no rollback (its failure paths retire the input
// outright), so a write-mode request that mutated the transport first and
// only then lost arbitration would leave the rejected tab switched to write
// mode holding a discarded epoch. The pre-check below is that arbitration;
// take_focus after a successful switch only re-asserts it (nothing else can
// interleave under the flow lock). Observe mode only releases focus — it
// never preempts another tab.
pub fn switch_input_mode<S>(tabs:&mut Sessions,key:(String,u64,u64,u64),mode:&str,focused:bool,mut switch:S)->Result<u64,String>
where S:FnMut(&str,bool)->Result<u64,String> {
    if mode!="observe" && tabs.focus.as_ref().is_some_and(|active|active!=&key) {return Err("focus_busy".into());}
    let epoch=switch(mode,focused)?;
    if mode!="observe" {tabs.take_focus(key).map_err(str::to_string)?;} else {tabs.release_focus(&key);}
    Ok(epoch)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_close_targets_exact_paused_slot_without_retiring_the_other_input_focus() {
        let mut tabs=Sessions::default();
        let binding=Binding::new("profile".into(),1,"qa".into(),"identity-a".into()).unwrap();
        let (a,ca)=tabs.begin("a",1,Some("host-a".into()),Some(binding.clone())).unwrap();
        let (b,cb)=tabs.begin("b",2,Some("host-b".into()),Some(binding.clone())).unwrap();
        tabs.claim("a",1,a).unwrap();
        tabs.claim("b",2,b).unwrap();
        tabs.set_visible("b",2,b).unwrap();
        tabs.take_focus(("b".into(),2,b,3)).unwrap();
        let control=herdr_readonly_transport::ObservationControl::new();
        let (tx,_rx)=oneshot::channel();
        let session=tabs.get_mut("a").unwrap();
        session.control=Some(control.clone());
        session.ack=Some((a,1,1,tx));

        assert!(matches!(tabs.prepare_close("a",2,a),Err("tab_stale")));
        assert!(matches!(tabs.prepare_close("a",1,b),Err("tab_stale")));
        let close=tabs.prepare_close("a",1,a).unwrap().unwrap();
        assert!(matches!(tabs.prepare_close("a",1,a),Err("tab_close_pending")));
        assert_eq!(tabs.set_visible("a",1,a),Err("tab_stale"));
        assert!(tabs.get("a").unwrap().ack.is_some());
        assert!(tabs.input_guard("b",2,b,3).is_ok());
        close.stop_gracefully();
        assert_eq!(control.snapshot().phase,herdr_readonly_transport::ObservationPhase::Closed);
        assert!(!ca.is_cancelled() && !cb.is_cancelled());
        assert!(matches!(tabs.begin("a",3,None,None),Err("tab_busy")));

        // A separate security revocation still overrides graceful retirement.
        tabs.cancel_hosts(&["host-a".into()]);
        assert!(ca.is_cancelled() && !cb.is_cancelled());
        tabs.finish("a",1,a);
        let (new,cn)=tabs.begin("a",3,None,Some(binding)).unwrap();
        assert!(matches!(tabs.prepare_close("a",1,a),Err("tab_stale")));
        assert!(tabs.prepare_close("a",3,new).unwrap().is_none());
        assert!(cn.is_cancelled() && !cb.is_cancelled());
        assert!(tabs.input_guard("b",2,b,3).is_ok());
    }

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
    #[test] fn two_tabs_hold_visibility_and_claims_simultaneously() {
        let mut s=Sessions::default();
        let (ga,ca)=s.begin("a",1,None,None).unwrap();let (gb,cb)=s.begin("b",1,None,None).unwrap();
        s.set_visible("a",1,ga).unwrap();s.set_visible("b",1,gb).unwrap();
        s.claim("a",1,ga).unwrap();s.claim("b",1,gb).unwrap();
        assert!(s.is_visible("a",1,ga) && s.is_visible("b",1,gb));
        assert!(!ca.is_cancelled() && !cb.is_cancelled());
        assert!(!s.is_visible("a",1,ga+1) && !s.is_visible("a",2,ga));
    }
    #[test] fn write_focus_stays_unique_and_nonfocused_tab_input_is_rejected() {
        let mut s=Sessions::default();
        let (ga,_)=s.begin("a",1,None,None).unwrap();let (gb,_)=s.begin("b",1,None,None).unwrap();
        s.set_visible("a",1,ga).unwrap();s.set_visible("b",1,gb).unwrap();
        s.claim("b",1,gb).unwrap();
        s.take_focus(("a".into(),1,ga,7)).unwrap();
        assert!(matches!(s.take_focus(("b".into(),1,gb,9)),Err("focus_busy")));
        // Tab b is visible and observing, but without focus its input is rejected.
        assert_eq!(s.input_guard("b",1,gb,9),Err("input_stale"));
        assert_eq!(s.input_guard("a",1,ga,7),Ok(()));
        // Releasing focus (observe mode) frees the slot for the other tab.
        s.release_focus(&("a".into(),1,ga,7));
        s.take_focus(("b".into(),1,gb,9)).unwrap();
        assert_eq!(s.input_guard("b",1,gb,9),Ok(()));
        assert!(s.focus.as_ref()!=Some(&("a".into(),1,ga,7)));
    }
    #[test] fn cancel_closes_one_observation_without_disturbing_the_other() {
        let mut s=Sessions::default();
        let (ga,ca)=s.begin("a",1,None,None).unwrap();let (gb,cb)=s.begin("b",1,None,None).unwrap();
        for (tab,g) in [("a",ga),("b",gb)] {s.set_visible(tab,1,g).unwrap();s.claim(tab,1,g).unwrap();}
        s.take_focus(("a".into(),1,ga,3)).unwrap();
        s.cancel("a",1,ga);
        assert!(ca.is_cancelled() && !cb.is_cancelled());
        assert!(!s.is_visible("a",1,ga) && s.is_visible("b",1,gb));
        assert!(s.focus.is_none());
        assert!(!s.finish("a",1,ga)); // cancelled slot stays reserved until settled
        assert!(s.get("b").is_some() && s.finish("b",1,gb));
    }
    #[test] fn stale_generation_cannot_become_visible() {
        let mut s=Sessions::default();let (ga,_)=s.begin("a",1,None,None).unwrap();
        s.cancel("a",1,ga);
        let (gn,_)=s.begin("a",1,None,None).unwrap();
        assert!(matches!(s.set_visible("a",1,ga),Err("tab_stale")));
        assert!(!s.is_visible("a",1,ga));
        s.set_visible("a",1,gn).unwrap();
        assert!(s.is_visible("a",1,gn) && !s.is_visible("a",1,ga));
    }

    #[test] fn rejected_write_mode_request_never_touches_the_transport_input() {
        let mut s=Sessions::default();
        let (ga,_)=s.begin("a",1,None,None).unwrap();let (gb,_)=s.begin("b",1,None,None).unwrap();
        s.set_visible("a",1,ga).unwrap();s.set_visible("b",1,gb).unwrap();
        // Tab a already holds the single focus slot in a write mode.
        s.take_focus(("a".into(),1,ga,5)).unwrap();
        let mut switches=0u32;
        // Tab b requests direct mode: arbitration must reject the request BEFORE
        // the transport input (the closure) is switched — otherwise b would end
        // up in write mode holding a discarded epoch while told it was rejected.
        assert_eq!(switch_input_mode(&mut s,("b".into(),1,gb,9),"direct",true,|_,_|{switches+=1;Ok(9)}),Err("focus_busy".to_string()));
        assert_eq!(switches,0); // transport never mutated: mode/focused/epoch untouched
        assert_eq!(s.focus.as_ref(),Some(&("a".into(),1,ga,5))); // the holder is undisturbed
        // When the transport switch itself fails, focus was never taken and the
        // slot stays free: a failed attempt must not block the next writer.
        s.release_focus(&("a".into(),1,ga,5));
        assert_eq!(switch_input_mode(&mut s,("b".into(),1,gb,9),"direct",true,|_,_|Err("input_result_unknown".to_string())),Err("input_result_unknown".to_string()));
        assert_eq!(s.focus,None);
        // Happy path still takes the slot and returns the new transport epoch;
        // observe mode releases it again without preempting anyone.
        assert_eq!(switch_input_mode(&mut s,("b".into(),1,gb,9),"direct",true,|_,_|Ok(12)),Ok(12));
        assert_eq!(s.focus.as_ref(),Some(&("b".into(),1,gb,9)));
        assert_eq!(switch_input_mode(&mut s,("b".into(),1,gb,9),"observe",false,|_,_|Ok(13)),Ok(13));
        assert_eq!(s.focus,None);
    }
    #[test] fn same_tab_old_epoch_focus_blocks_new_epoch_until_released() {
        let mut s=Sessions::default();
        let (ga,_)=s.begin("a",1,None,None).unwrap();
        s.set_visible("a",1,ga).unwrap();
        s.take_focus(("a".into(),1,ga,5)).unwrap();
        // Registered pre-existing behavior: the focus key embeds the epoch, so
        // the same tab's next epoch cannot take focus while the old epoch still
        // holds the slot (not introduced by the multi-visible change; do not
        // "fix" here without a separate decision).
        assert!(matches!(s.take_focus(("a".into(),1,ga,9)),Err("focus_busy")));
        let mut switched=0u32;
        assert_eq!(switch_input_mode(&mut s,("a".into(),1,ga,9),"direct",true,|_,_|{switched+=1;Ok(10)}),Err("focus_busy".to_string()));
        assert_eq!(switched,0); // rejected before the transport is touched
        // Epoch mismatch alone (right tab, holding focus, wrong epoch) also
        // rejects input sends.
        assert_eq!(s.input_guard("a",1,ga,4),Err("input_stale"));
        assert_eq!(s.input_guard("a",1,ga,5),Ok(()));
        // Releasing the old key frees the slot for the new epoch.
        s.release_focus(&("a".into(),1,ga,5));
        assert!(s.take_focus(("a".into(),1,ga,9)).is_ok());
        assert_eq!(s.input_guard("a",1,ga,9),Ok(()));
    }
    #[test] fn clear_visible_hides_one_tab_and_its_focus_but_keeps_the_session() {
        let mut s=Sessions::default();
        let (ga,ca)=s.begin("a",1,None,None).unwrap();let (gb,cb)=s.begin("b",1,None,None).unwrap();
        s.set_visible("a",1,ga).unwrap();s.set_visible("b",1,gb).unwrap();
        s.take_focus(("a".into(),1,ga,3)).unwrap();
        assert!(s.clear_visible("a",1,ga));
        assert!(!s.is_visible("a",1,ga) && s.is_visible("b",1,gb));
        assert_eq!(s.focus,None); // the paused tab's focus went with visibility
        assert!(!s.clear_visible("a",2,ga)); // wrong owner does not match
        assert!(!ca.is_cancelled() && !cb.is_cancelled()); // gate untouched, resume may re-attach
        assert!(s.get("a").is_some()); // session retained, unlike cancel
    }

    #[tokio::test]
    async fn refreshed_review_keeps_selection_receiver_and_rejects_old_row_without_consuming_it() {
        use herdr_readonly_transport::{Pane,session_watch::{SessionWatchPhase,SessionWatchUpdate}};
        let mut session=Session {generation:41,control:Some(herdr_readonly_transport::ObservationControl::new()),..Session::default()};
        let (tx,mut rx)=oneshot::channel();session.select=Some((41,1,tx));
        let update=|revision,terminal:&str|SessionWatchUpdate {epoch:1,revision,phase:SessionWatchPhase::Fresh,reason:"fixture",panes:Some(vec![Pane {pane_id:"w1:p1".into(),terminal_id:terminal.into(),label:None,agent:None,agent_status:"working",workspace:None,tab:None}])};
        session.dashboard.update(1,&update(1,"term_abc"));
        session.dashboard.update(1,&update(2,"term_def"));
        assert_eq!(session.select_dashboard(41,1,1,"w1:p1".into(),"term_abc".into()),Err("dashboard_stale"));
        assert_eq!(session.select_dashboard(41,1,2,"w1:p1".into(),"term_abc".into()),Err("target_changed"));
        assert_eq!(session.select_dashboard(42,1,2,"w1:p1".into(),"term_def".into()),Err("stale_selection"));
        assert!(matches!(rx.try_recv(),Err(oneshot::error::TryRecvError::Empty)));
        session.select_dashboard(41,1,2,"w1:p1".into(),"term_def".into()).unwrap();
        let selected=rx.await.unwrap();assert_eq!(selected.terminal_id,"term_def");
        assert_eq!(session.select_dashboard(41,1,2,"w1:p1".into(),"term_def".into()),Err("stale_selection"));
    }

}

#[cfg(test)]
mod stop_tests {
    use super::*;
    #[test]
    fn explicit_stop_captures_full_binding_and_fences_only_matching_new_attempts() {
        let binding=Binding::new("profile".into(),1,"qa".into(),"identity-a".into()).unwrap();
        let other=Binding::new("profile".into(),1,"qa".into(),"identity-b".into()).unwrap();
        let mut tabs=Sessions::default();
        let (a,ca)=tabs.begin("a",1,Some("host-a".into()),Some(binding.clone())).unwrap();tabs.claim("a",1,a).unwrap();
        let control=herdr_readonly_transport::ObservationControl::new();tabs.get_mut("a").unwrap().control=Some(control.clone());
        let (b,cb)=tabs.begin("b",2,Some("host-b".into()),Some(other.clone())).unwrap();tabs.claim("b",2,b).unwrap();
        tabs.set_visible("a",1,a).unwrap();tabs.set_visible("b",2,b).unwrap();
        let plan=tabs.stop_binding(&binding,None,None).unwrap();let targets=plan.targets;let controls=plan.controls;
        assert_eq!(targets,vec![("a".into(),1,a)]);
        assert!(!tabs.is_visible("a",1,a));assert!(tabs.is_visible("b",2,b));
        assert!(!ca.is_cancelled() && !cb.is_cancelled());
        assert_eq!(control.snapshot().phase,herdr_readonly_transport::ObservationPhase::Starting);
        for control in controls {control.stop_gracefully();}
        assert!(!ca.is_cancelled());assert!(!tabs.stop_settled(&targets));
        assert!(matches!(tabs.begin("blocked",3,None,Some(binding.clone())),Err("mobile_node_stop_pending")));
        assert!(tabs.begin("other",3,None,Some(other)).is_ok());
        assert!(!tabs.finish("a",2,a));assert!(!tabs.stop_settled(&targets));
        tabs.finish("a",1,a);assert!(tabs.stop_settled(&targets));
        tabs.finish_stop(&binding);let (new,_) =tabs.begin("a",4,None,Some(binding)).unwrap();
        tabs.cancel("a",1,a);assert!(tabs.claim("a",4,new).is_ok());assert!(!cb.is_cancelled());
    }
}

#[cfg(test)]
mod deferred_stop_tests {
 use super::*;
 #[test]
 fn delayed_retirement_requires_new_explicit_stop_and_rejects_parallel_native_admission() {
  let binding=Binding::new("profile".into(),1,"qa".into(),"identity".into()).unwrap();let mut tabs=Sessions::default();
  let (g,_)=tabs.begin("a",1,None,Some(binding.clone())).unwrap();tabs.claim("a",1,g).unwrap();
  let first=tabs.stop_binding(&binding,None,Some((7,11))).unwrap();
  assert!(matches!(tabs.stop_binding(&binding,None,None),Err("mobile_node_stop_pending")));
  tabs.defer_stop(&binding);assert!(tabs.is_stopping(&binding));
  assert!(matches!(tabs.begin("new",2,None,Some(binding.clone())),Err("mobile_node_stop_pending")));
  tabs.finish("a",1,g);
  let retry=tabs.stop_binding(&binding,None,Some((7,12))).unwrap();
  assert_eq!(retry.targets,first.targets);assert_eq!(retry.legacy,Some((7,11)));assert!(tabs.stop_settled(&retry.targets));
  let mut native_calls=0;
  if tabs.stop_settled(&retry.targets){native_calls+=1;}
  assert!(tabs.stop_binding(&binding,None,None).is_err());assert_eq!(native_calls,1);
  // A failed native cleanup stays fenced, but another explicit click can
  // retry only the original plan. Success alone releases its admission fence.
  tabs.defer_stop(&binding);assert!(tabs.is_stopping(&binding));
  let again=tabs.stop_binding(&binding,None,None).unwrap();assert_eq!(again.legacy,Some((7,11)));
  tabs.finish_stop(&binding);assert!(!tabs.is_stopping(&binding));
 }
}
