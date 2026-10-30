//! Pure lifecycle/credit core. No credentials, sockets, filesystem or remote PTY APIs.
use std::collections::VecDeque;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Binding {
    pub target: String,
    pub generation: u64,
    pub epoch: u64,
}

#[derive(Debug)]
pub struct CreditStream {
    pub binding: Binding,
    pub outstanding_bytes: usize,
    max_bytes: usize,
    pending: VecDeque<usize>,
    cancelled: bool,
}
impl CreditStream {
    pub fn new(binding: Binding, max_bytes: usize) -> Self {
        Self { binding, outstanding_bytes: 0, max_bytes, pending: VecDeque::new(), cancelled: false }
    }
    pub fn reserve(&mut self, bytes: usize) -> Result<(), &'static str> {
        if self.cancelled { return Err("stream cancelled"); }
        if bytes == 0 || bytes > self.max_bytes || self.outstanding_bytes > self.max_bytes - bytes { return Err("credit budget exceeded"); }
        self.pending.push_back(bytes);
        self.outstanding_bytes += bytes;
        Ok(())
    }
    pub fn acknowledge(&mut self, bytes: usize) -> Result<(), &'static str> {
        if self.cancelled { return Err("stream cancelled"); }
        if self.pending.front().copied() != Some(bytes) { return Err("unexpected acknowledgment"); }
        self.pending.pop_front();
        self.outstanding_bytes -= bytes;
        Ok(())
    }
    pub fn cancel(&mut self) { self.cancelled = true; self.outstanding_bytes = 0; self.pending.clear(); }
}

/// A pinned identity is required before authentication. Session names never fall back to default.
#[derive(Debug)]
pub struct SessionGuard {
    expected_host_key: Vec<u8>,
    expected_session: String,
    authenticated: bool,
    bound: bool,
    generation: u64,
}
impl SessionGuard {
    pub fn new(key: Vec<u8>, session: String) -> Result<Self, &'static str> {
        if key.is_empty() || session.is_empty() || session.chars().any(char::is_control) { return Err("explicit key and session required"); }
        Ok(Self { expected_host_key:key, expected_session:session, authenticated:false, bound:false, generation:0 })
    }
    pub fn verify_host_key(&mut self, key: &[u8]) -> bool {
        self.authenticated = false; self.bound = false;
        key == self.expected_host_key
    }
    pub fn authenticated_after_key(&mut self, actual_key: &[u8]) -> Result<(), &'static str> {
        if actual_key != self.expected_host_key { return Err("host key mismatch"); }
        self.authenticated = true; Ok(())
    }
    pub fn bind_session(&mut self, session: &str) -> Result<u64, &'static str> {
        if !self.authenticated || session != self.expected_session { return Err("session binding rejected"); }
        self.bound=true; Ok(self.generation)
    }
    pub fn input_allowed(&self, generation: u64) -> bool { self.bound && self.authenticated && generation==self.generation }
    pub fn cancel(&mut self) { self.generation+=1; self.authenticated=false; self.bound=false; }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn stream() -> CreditStream { CreditStream::new(Binding { target:"a".into(), generation:1, epoch:1 }, 8) }
    #[test] fn budget_cannot_grow_unbounded() { let mut s=stream(); s.reserve(8).unwrap(); assert!(s.reserve(1).is_err()); assert_eq!(s.outstanding_bytes,8); }
    #[test] fn acknowledges_only_expected_chunk_once() { let mut s=stream();s.reserve(3).unwrap();assert!(s.acknowledge(2).is_err());s.acknowledge(3).unwrap();assert!(s.acknowledge(3).is_err()); }
    #[test] fn cancellation_rejects_late_ack_and_producer() {let mut s=stream();s.reserve(2).unwrap();s.cancel();assert!(s.reserve(2).is_err());assert!(s.acknowledge(2).is_err());assert_eq!(s.outstanding_bytes,0);}
    #[test] fn wrong_key_does_not_authenticate() {let mut g=SessionGuard::new(vec![1],"chosen".into()).unwrap();assert!(!g.verify_host_key(&[2]));assert!(g.authenticated_after_key(&[2]).is_err());assert!(g.bind_session("chosen").is_err());}
    #[test] fn missing_session_never_falls_back_to_default() {let mut g=SessionGuard::new(vec![1],"chosen".into()).unwrap();g.authenticated_after_key(&[1]).unwrap();assert!(g.bind_session("default").is_err());assert!(!g.input_allowed(0));}
    #[test] fn cancelled_generation_never_replays() {let mut g=SessionGuard::new(vec![1],"chosen".into()).unwrap();g.authenticated_after_key(&[1]).unwrap();let old=g.bind_session("chosen").unwrap();assert!(g.input_allowed(old));g.cancel();assert!(!g.input_allowed(old));g.authenticated_after_key(&[1]).unwrap();let next=g.bind_session("chosen").unwrap();assert_ne!(old,next);assert!(!g.input_allowed(old));}
}
