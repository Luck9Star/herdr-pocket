// Compile and exercise the EXACT additive node FFI source with a fake engine.
// No EasyTier engine, sockets, DNS, credential paths or network identities.
use std::{collections::HashMap, ffi::{c_char, c_int, CStr, CString}, sync::{Arc, Mutex, MutexGuard, OnceLock, atomic::{AtomicU8, AtomicUsize, Ordering}}, time::Duration};
use tokio::runtime::Runtime;
use herdr_portable_stream_probe as pocket_stream;

const HEELER_ET_OK: c_int = 0;
const HEELER_ET_ERR: c_int = -1;
const HEELER_ET_ERR_TIMEOUT: c_int = -2;
const MAX_INSTANCES: usize = 32;
#[derive(Debug)]
struct Failure { code: c_int, message: String }
impl Failure {
    fn new(code: c_int, message: impl Into<String>) -> Self { Self { code, message: message.into() } }
    fn generic(message: impl Into<String>) -> Self { Self::new(-1, message) }
}
fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> { m.lock().unwrap_or_else(|e| e.into_inner()) }
fn ffi_call(err: *mut c_char, len: usize, body: impl FnOnce() -> Result<c_int, Failure>) -> c_int {
    match body() {
        Ok(code) => code,
        Err(error) => {
            if !err.is_null() && len > 0 {
                let bytes = error.message.as_bytes(); let n = bytes.len().min(len-1);
                unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), err.cast(), n); *err.add(n)=0; }
            }
            error.code
        }
    }
}
unsafe fn borrowed_str<'a>(ptr: *const c_char, _: &str) -> Result<&'a str, Failure> {
    if ptr.is_null() { return Err(Failure::generic("missing input")); }
    unsafe { CStr::from_ptr(ptr) }.to_str().map_err(|_| Failure::generic("UTF8"))
}
fn stream_runtime() -> Result<&'static Runtime, Failure> {
    if tokio::runtime::Handle::try_current().is_ok() { return Err(Failure::new(-10, "dedicated worker required")); }
    static RUNTIME: OnceLock<Runtime> = OnceLock::new();
    Ok(RUNTIME.get_or_init(|| tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build().unwrap()))
}
fn streams() -> &'static pocket_stream::Registry {
    static STREAMS: OnceLock<pocket_stream::Registry> = OnceLock::new();
    STREAMS.get_or_init(pocket_stream::Registry::default)
}
fn stream_failure(error: pocket_stream::Error) -> Failure { Failure::generic(error.to_string()) }
fn not_running() -> Failure { Failure::new(-3, "not engine started") }
struct FakeConfig { text: String }
struct FakeIdentity { network_name: String }
impl FakeConfig {
    fn get_network_identity(&self) -> FakeIdentity { FakeIdentity { network_name: "synthetic-network".into() } }
    fn get_credential_file(&self) -> Option<String> { self.text.contains("credential_file").then(|| "/not-read".into()) }
    fn get_managed_credentials(&self) -> Vec<()> { if self.text.contains("managed_credentials") { vec![()] } else { vec![] } }
}
fn outbound_only_config(text: &str) -> Result<FakeConfig, Failure> {
    if text.contains("parse-fail") { return Err(Failure::generic(format!("parser would leak {text}"))); }
    Ok(FakeConfig { text: text.to_owned() })
}
#[derive(Clone, Copy)]
enum CoreInstanceState { Created, Running, Stopped }
struct NativeCoreInstance { config: FakeConfig, state: AtomicU8, stop_attempts: AtomicUsize }
impl NativeCoreInstance {
    fn state(&self) -> CoreInstanceState {
        match self.state.load(Ordering::Acquire) { 1 => CoreInstanceState::Running, 2 => CoreInstanceState::Stopped, _ => CoreInstanceState::Created }
    }
    async fn start(self: &Arc<Self>) -> Result<(), ()> {
        if self.config.text.contains("slow-start") { tokio::time::sleep(Duration::from_millis(40)).await; }
        if self.config.text.contains("start-fail") { return Err(()); }
        self.state.store(1, Ordering::Release); Ok(())
    }
    async fn stop(self: &Arc<Self>) {
        if self.config.text.contains("slow-stop") && self.stop_attempts.fetch_add(1, Ordering::AcqRel) == 0 {
            tokio::time::sleep(Duration::from_millis(40)).await;
        }
        self.state.store(2, Ordering::Release);
    }
}
fn create_native_instance(config: FakeConfig) -> Result<Arc<NativeCoreInstance>, ()> {
    if config.text.contains("construct-fail") { return Err(()); }
    Ok(Arc::new(NativeCoreInstance { config, state: AtomicU8::new(0), stop_attempts: AtomicUsize::new(0) }))
}
enum DialSource { Manual { instance: Arc<NativeCoreInstance>, network_name: String } }
async fn dial_overlay(source: DialSource, network: Option<String>, _: String, _: u16, _: Duration) -> Result<tokio::io::DuplexStream, Failure> {
    let DialSource::Manual { instance, network_name } = source;
    if !matches!(instance.state(), CoreInstanceState::Running) || Some(network_name) != network { return Err(not_running()); }
    let (one, _two) = tokio::io::duplex(64); Ok(one)
}
include!("../nodes.txt");

static SERIAL: Mutex<()> = Mutex::new(());
fn start(config: &str, timeout_ms: u32) -> (c_int, u64) {
    let config = CString::new(config).unwrap(); let mut id=0;
    let code=unsafe { heeler_et_node_start(config.as_ptr(), timeout_ms, &mut id, std::ptr::null_mut(), 0) };
    (code,id)
}
fn stop(id: u64, timeout: u32) -> c_int { unsafe { heeler_et_node_stop(id, timeout, std::ptr::null_mut(), 0) } }

#[test]
fn pocket_node_exact_ffi_epoch_selector_drain_and_status() {
    let _serial=lock(&SERIAL);
    let (code,id)=start("synthetic",100); assert_eq!(code,0); assert_ne!(id,0);
    let mut state=0; assert_eq!(unsafe { heeler_et_node_status(id,&mut state,std::ptr::null_mut(),0) },0); assert_eq!(state,1);
    let network=CString::new("wrong").unwrap(); let host=CString::new("fake").unwrap(); let mut handle=0;
    assert_eq!(unsafe { heeler_et_node_stream_connect(id,network.as_ptr(),host.as_ptr(),22,100,&mut handle,std::ptr::null_mut(),0) },-4); assert_eq!(handle,0);
    let network=CString::new("synthetic-network").unwrap();
    assert_eq!(unsafe { heeler_et_node_stream_connect(id,network.as_ptr(),host.as_ptr(),22,100,&mut handle,std::ptr::null_mut(),0) },0);
    assert_eq!(stop(id,100),-10);
    stream_runtime().unwrap().block_on(streams().close(handle)).unwrap(); pocket_stream_closed(handle);
    assert_eq!(stop(id,100),0); assert_eq!(stop(id,100),-6);
    let (_,new_id)=start("synthetic",100); assert!(new_id>id); assert_eq!(stop(new_id,100),0);
}

#[test]
fn pocket_node_start_and_stop_timeout_retain_lease_and_capacity() {
    let _serial=lock(&SERIAL);
    let (code,id)=start("slow-start;slow-stop",1); assert_eq!(code,-2); assert_ne!(id,0);
    assert!(lock(pocket_nodes()).entries.contains_key(&id));
    assert_eq!(stop(id,1),-2); assert!(lock(pocket_nodes()).entries.contains_key(&id));
    assert_eq!(stop(id,100),0); assert!(!lock(pocket_nodes()).entries.contains_key(&id));
    let (code,id)=start("start-fail",100); assert_eq!(code,-1); assert_ne!(id,0); assert_eq!(stop(id,100),0);
    let (code,id)=start("construct-fail",100); assert_eq!(code,-1); assert_eq!(id,0);
}

#[test]
fn pocket_node_capacity_and_exhausted_ids_refuse_without_reuse() {
    let _serial=lock(&SERIAL); let mut ids=vec![];
    for _ in 0..MAX_INSTANCES { let (code,id)=start("synthetic",100); assert_eq!(code,0); ids.push(id); }
    assert_eq!(start("synthetic",100),(-9,0));
    for id in ids { assert_eq!(stop(id,100),0); }
    let saved=lock(pocket_nodes()).next; lock(pocket_nodes()).next=u64::MAX;
    assert_eq!(start("synthetic",100),(-9,0)); lock(pocket_nodes()).next=saved;
}

#[test]
fn pocket_node_rejects_file_credentials_and_redacts_error_payload() {
    let _serial=lock(&SERIAL);
    for config in ["credential_file", "managed_credentials"] { assert_eq!(start(config,100),(-1,0)); }
    let config=CString::new("parse-fail;DO-NOT-LEAK").unwrap(); let mut id=0; let mut error=[0 as c_char;128];
    assert_eq!(unsafe { heeler_et_node_start(config.as_ptr(),100,&mut id,error.as_mut_ptr(),error.len()) },-1);
    let message=unsafe { CStr::from_ptr(error.as_ptr()) }.to_str().unwrap(); assert!(!message.contains("DO-NOT-LEAK"));
    stream_runtime().unwrap().block_on(async {
        let mut id=0;
        assert_eq!(unsafe { heeler_et_node_start(config.as_ptr(),100,&mut id,std::ptr::null_mut(),0) },-10);
    });
}
