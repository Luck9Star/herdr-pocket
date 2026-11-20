//! Linux Secret Service bridge. A durable handle journal precedes any write.
use std::ffi::{c_char, CString, CStr};
const TAURI: &[u8] = b"herdr-pocket.tauri\0";
unsafe extern "C" {
    fn hp_identity_reserve(out: *mut c_char) -> i32;
    fn hp_identity_create_reserved(app: *const c_char, handle: *const c_char, out: *mut c_char) -> i32;
    fn hp_identity_public(app: *const c_char, handle: *const c_char, out: *mut c_char) -> i32;
    fn hp_identity_sign(app: *const c_char, handle: *const c_char, data: *const u8, len: usize, out: *mut u8) -> i32;
    fn hp_identity_delete(app: *const c_char, handle: *const c_char) -> i32;
}
fn status(code: i32) -> Result<()> {
    match code { 0 => Ok(()), 1 => Err("invalid_device_key"), 2 => Err("key_missing"), 3 => Err("key_locked"),
        5 => Err("key_write_unknown"), 6 => Err("payload_too_large"), 7 => Err("key_exists"), _ => Err("key_unavailable") }
}
fn text_buffer(f: impl FnOnce(*mut c_char) -> i32, size: usize) -> Result<String> {
    let mut bytes = vec![0u8;size]; status(f(bytes.as_mut_ptr().cast()))?;
    CStr::from_bytes_until_nul(&bytes).map_err(|_| "key_unavailable")?.to_str().map(str::to_owned).map_err(|_| "key_unavailable")
}
fn reserve() -> Result<String> { text_buffer(|out| unsafe { hp_identity_reserve(out) }, 33) }
fn with_handle<T>(handle: &str, f: impl FnOnce(*const c_char) -> Result<T>) -> Result<T> {
    let h=CString::new(handle).map_err(|_| "invalid_device_key")?; f(h.as_ptr())
}
fn read_public(handle: &str) -> Result<String> { with_handle(handle, |h| text_buffer(|out| unsafe { hp_identity_public(TAURI.as_ptr().cast(),h,out) },128)) }
fn write_new(handle: &str) -> Result<String> { with_handle(handle, |h| text_buffer(|out| unsafe { hp_identity_create_reserved(TAURI.as_ptr().cast(),h,out) },128)) }
fn sign_key(handle: &str, data: &[u8]) -> Result<Vec<u8>> { with_handle(handle, |h| { let mut out=vec![0u8;64]; status(unsafe {hp_identity_sign(TAURI.as_ptr().cast(),h,data.as_ptr(),data.len(),out.as_mut_ptr())})?; Ok(out) }) }
fn remove_key(handle: &str) -> Result<()> { with_handle(handle, |h| status(unsafe {hp_identity_delete(TAURI.as_ptr().cast(),h)})) }

use herdr_readonly_transport::{pairing::KeyStore, Result};
use std::{fs::{self, File, OpenOptions}, io::{Read, Write}, os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
           path::PathBuf, sync::Mutex};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Journal { host_id: String, handle: String, target_sha256: String }

pub struct LinuxPairingStore { dir: PathBuf, host: Mutex<Option<(String,String)>> }
impl LinuxPairingStore {
    pub fn new(dir: PathBuf) -> Self { Self { dir, host: Mutex::new(None) } }
    fn path(&self) -> PathBuf { self.dir.join("linux-pairing-pending.json") }
    fn read(&self) -> Result<Option<Journal>> {
        let path = self.path();
        let meta = match fs::symlink_metadata(&path) {
            Ok(meta) => meta,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err("key_unavailable"),
        };
        if !meta.is_file() || meta.len() > 256 { return Err("key_unavailable"); }
        let file = OpenOptions::new().read(true).custom_flags(libc::O_NOFOLLOW).open(path)
            .map_err(|_| "key_unavailable")?;
        let mut bytes = Vec::new(); file.take(257).read_to_end(&mut bytes).map_err(|_| "key_unavailable")?;
        if bytes.len() > 256 { return Err("key_unavailable"); }
        let j: Journal = serde_json::from_slice(&bytes).map_err(|_| "key_unavailable")?;
        if !valid_id(&j.host_id) || !valid_id(&j.handle) || !valid_digest(&j.target_sha256) { return Err("key_unavailable"); }
        Ok(Some(j))
    }
    fn sync_dir(&self) -> Result<()> { File::open(&self.dir).and_then(|f| f.sync_all()).map_err(|_| "key_unavailable") }
    fn lock(&self) -> Result<File> {
        let meta=fs::symlink_metadata(&self.dir).map_err(|_| "key_unavailable")?;
        if !meta.is_dir() || meta.file_type().is_symlink() { return Err("key_unavailable"); }
        let file=OpenOptions::new().read(true).write(true).create(true).mode(0o600)
            .custom_flags(libc::O_NOFOLLOW).open(self.dir.join("linux-pairing.lock")).map_err(|_| "key_unavailable")?;
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) } != 0 { return Err("key_unavailable"); }
        Ok(file)
    }
    fn publish(&self, host_id: &str, handle: &str, target_sha256: &str) -> Result<()> {
        let bytes = serde_json::to_vec(&Journal { host_id: host_id.into(), handle: handle.into(), target_sha256: target_sha256.into() })
            .map_err(|_| "key_unavailable")?;
        let temp=self.dir.join(format!(".linux-pairing-{handle}.tmp"));
        let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600)
            .custom_flags(libc::O_NOFOLLOW).open(&temp).map_err(|_| "key_creation_pending")?;
        file.write_all(&bytes).and_then(|_| file.sync_all()).map_err(|_| "key_creation_pending")?;
        let linked=fs::hard_link(&temp,self.path()).map_err(|_| "key_creation_pending");
        let removed=fs::remove_file(&temp).map_err(|_| "key_creation_pending");
        linked?; removed?;
        self.sync_dir().map_err(|_| "key_creation_pending")
    }
    fn clear(&self, handle: &str) -> Result<()> {
        let j = self.read()?.ok_or("key_creation_pending")?;
        if j.handle != handle { return Err("key_creation_pending"); }
        fs::remove_file(self.path()).map_err(|_| "key_creation_pending")?;
        self.sync_dir().map_err(|_| "key_creation_pending")
    }
}
fn target_digest(s: &str) -> String { ring::digest::digest(&ring::digest::SHA256, s.as_bytes()).as_ref().iter().map(|b| format!("{b:02x}")).collect() }
fn valid_digest(s: &str) -> bool { s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) }
fn valid_id(s: &str) -> bool { s.len() == 32 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) }
impl KeyStore for LinuxPairingStore {
    fn transaction(&self) -> Result<Box<dyn Send>> { Ok(Box::new(self.lock()?)) }
    fn begin_create(&self, host_id: &str, target: &str) -> Result<()> {
        if !valid_id(host_id) { return Err("invalid_device_key"); }
        if self.read()?.is_some() { return Err("key_creation_pending"); }
        *self.host.lock().map_err(|_| "key_unavailable")? = Some((host_id.into(),target_digest(target))); Ok(())
    }
    fn pending_create(&self, host_id: &str, target: &str) -> Result<Option<String>> {
        match self.read()? { Some(j) if j.host_id == host_id && j.target_sha256 == target_digest(target) => Ok(Some(j.handle)),
            Some(_) => Err("key_creation_pending"), None => Ok(None) }
    }
    fn create(&self) -> Result<(String, String)> {
        let (host, target_sha256) = self.host.lock().map_err(|_| "key_unavailable")?.take().ok_or("key_creation_pending")?;
        let handle = reserve()?;
        self.publish(&host, &handle, &target_sha256)?;
        match write_new(&handle) {
            Ok(public) => Ok((handle, public)),
            Err(e @ ("key_locked" | "key_unavailable" | "key_exists" | "invalid_device_key")) => {
                self.clear(&handle).map_err(|_| "key_creation_pending")?; Err(e)
            }
            Err(_) => Err("key_write_unknown"),
        }
    }
    fn finish_create(&self, handle: &str) -> Result<()> { self.clear(handle) }
    fn clear_deleted_create(&self, handle: &str) -> Result<()> {
        match self.read()? { None => Ok(()), Some(j) if j.handle == handle => self.clear(handle),
            Some(_) => Ok(()) }
    }
    fn failed_create_cleanup(&self, _handle: &str) -> Result<()> { Err("key_write_unknown") }
    fn public(&self, handle: &str) -> Result<String> { read_public(handle) }
    fn sign(&self, handle: &str, bytes: &[u8]) -> Result<Vec<u8>> { sign_key(handle, bytes) }
    fn delete(&self, handle: &str) -> Result<()> { remove_key(handle) }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn journal_lock_worker() {
        let Some(dir)=std::env::var_os("HP_JOURNAL_CHILD") else { return };
        let dir=PathBuf::from(dir);let store=LinuxPairingStore::new(dir.clone());
        fs::write(dir.join("ready"),b"ready").unwrap();
        let _lock=store.transaction().unwrap();
        store.clear(&"1".repeat(32)).unwrap();
        store.publish(&"3".repeat(32),&"2".repeat(32),&target_digest("target")).unwrap();
    }
    #[test]
    fn process_lock_and_atomic_publish_preserve_new_handle() {
        let dir=std::env::temp_dir().join(format!("hp-linux-lock-{}",reserve().unwrap()));
        fs::create_dir(&dir).unwrap();let store=LinuxPairingStore::new(dir.clone());
        let old="1".repeat(32);let new="2".repeat(32);let host="3".repeat(32);
        let partial=dir.join(".linux-pairing-interrupted.tmp");fs::write(&partial,b"partial").unwrap();
        assert!(store.read().unwrap().is_none());
        let guard=store.transaction().unwrap();store.publish(&host,&old,&target_digest("target")).unwrap();
        let mut child=std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact","linux_pairing_keys::tests::journal_lock_worker","--nocapture"])
            .env("HP_JOURNAL_CHILD",&dir).spawn().unwrap();
        let deadline=std::time::Instant::now()+std::time::Duration::from_secs(5);
        while !dir.join("ready").exists() { assert!(std::time::Instant::now()<deadline);std::thread::sleep(std::time::Duration::from_millis(5)); }
        assert!(child.try_wait().unwrap().is_none());
        assert_eq!(store.read().unwrap().unwrap().handle,old);
        drop(guard);assert!(child.wait().unwrap().success());
        let _lock=store.transaction().unwrap();
        assert_eq!(store.clear(&old),Err("key_creation_pending"));
        assert_eq!(store.read().unwrap().unwrap().handle,new);
        store.clear(&new).unwrap();drop(_lock);
        fs::remove_file(partial).unwrap();fs::remove_file(dir.join("ready")).unwrap();
        fs::remove_file(dir.join("linux-pairing.lock")).unwrap();fs::remove_dir(dir).unwrap();
    }
    #[test]
    fn journal_blocks_new_identity_and_binds_exact_host_and_handle() {
        let dir=std::env::temp_dir().join(format!("hp-linux-journal-{}", reserve().unwrap()));
        fs::create_dir(&dir).unwrap();
        let store=LinuxPairingStore::new(dir.clone());let guard=store.transaction().unwrap();
        let host="1".repeat(32);let other="2".repeat(32);let handle=reserve().unwrap();
        store.begin_create(&host,"target-a").unwrap();store.publish(&host,&handle,&target_digest("target-a")).unwrap();
        assert_eq!(store.begin_create(&host,"target-a"),Err("key_creation_pending"));
        assert_eq!(store.pending_create(&host,"target-a").unwrap(),Some(handle.clone()));
        assert_eq!(store.pending_create(&other,"target-a"),Err("key_creation_pending"));
        assert_eq!(store.pending_create(&host,"target-b"),Err("key_creation_pending"));
        assert_eq!(store.clear(&other),Err("key_creation_pending"));
        store.clear_deleted_create(&other).unwrap();
        assert!(store.read().unwrap().is_some());
        store.clear(&handle).unwrap();assert!(store.read().unwrap().is_none());drop(guard);
        fs::remove_file(dir.join("linux-pairing.lock")).unwrap();fs::remove_dir(&dir).unwrap();
    }
    #[test]
    fn actual_service_recovers_original_journal_after_new_store_instance() {
        let Some(base)=std::env::var_os("HP_SECRET_TEST_DIR") else { return };
        let dir=std::path::PathBuf::from(base).join(format!("tauri-journal-{}", reserve().unwrap()));
        fs::create_dir(&dir).unwrap();
        let host="3".repeat(32);
        let store=LinuxPairingStore::new(dir.clone());let guard=store.transaction().unwrap();
        store.begin_create(&host,"target-a").unwrap();
        let (handle, public)=store.create().unwrap();
        drop(guard);drop(store);
        let restored=LinuxPairingStore::new(dir.clone());let guard=restored.transaction().unwrap();
        assert_eq!(restored.pending_create(&host,"target-a").unwrap(),Some(handle.clone()));
        assert_eq!(restored.public(&handle).unwrap(),public);
        assert_eq!(restored.sign(&handle,b"fixture").unwrap().len(),64);
        assert_eq!(restored.begin_create(&host,"target-a"),Err("key_creation_pending"));
        restored.delete(&handle).unwrap();
        restored.clear_deleted_create(&handle).unwrap();
        assert!(restored.pending_create(&host,"target-a").unwrap().is_none());
        assert_eq!(restored.public(&handle),Err("key_missing"));drop(guard);
        fs::remove_file(dir.join("linux-pairing.lock")).unwrap();fs::remove_dir(dir).unwrap();
    }
    #[test]
    fn unavailable_service_before_write_does_not_leave_a_creation_intent() {
        if std::env::var_os("HP_TEST_NO_SERVICE").is_none() { return }
        let dir=std::env::temp_dir().join(format!("hp-linux-journal-{}", reserve().unwrap()));
        fs::create_dir(&dir).unwrap(); let store=LinuxPairingStore::new(dir.clone());let guard=store.transaction().unwrap();
        let host="4".repeat(32);store.begin_create(&host,"target-a").unwrap();
        assert_eq!(store.create(),Err("key_unavailable"));
        assert!(store.pending_create(&host,"target-a").unwrap().is_none());
        let handle=reserve().unwrap();store.publish(&host,&handle,&target_digest("target-a")).unwrap();
        assert_eq!(store.delete(&handle),Err("key_unavailable"));
        assert_eq!(store.pending_create(&host,"target-a").unwrap(),Some(handle.clone()));
        store.clear(&handle).unwrap();drop(guard);fs::remove_file(dir.join("linux-pairing.lock")).unwrap();fs::remove_dir(dir).unwrap();
    }
    #[test]
    fn invalid_or_symlink_journal_does_not_establish_absence() {
        use std::os::unix::fs::symlink;
        let dir=std::env::temp_dir().join(format!("hp-linux-journal-{}", reserve().unwrap()));
        fs::create_dir(&dir).unwrap();let store=LinuxPairingStore::new(dir.clone());
        let target=dir.join("other");fs::write(&target,b"{}").unwrap();symlink(&target,store.path()).unwrap();
        assert!(matches!(store.read(),Err("key_unavailable")));
        fs::remove_file(store.path()).unwrap();fs::remove_file(target).unwrap();fs::remove_dir(dir).unwrap();
    }
}
