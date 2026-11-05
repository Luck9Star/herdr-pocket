//! Durable write-ahead marker. It contains target and request ID, never input bytes.
use crate::input::InputIdentity;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};

#[derive(Serialize, Deserialize, Clone, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Marker {
    version: u8,
    request_id: String,
    target: InputIdentity,
}
struct Inner {
    directory: PathBuf,
    _lock: File,
}
pub struct Recovery {
    inner: Option<Mutex<Inner>>,
    active: AtomicBool,
}
pub type SharedRecovery = Arc<Recovery>;
fn open_private(path: &Path) -> std::io::Result<File> {
    let mut opts = OpenOptions::new();
    opts.read(true).write(true).create(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    opts.open(path)
}
fn sync_dir(path: &Path) -> std::io::Result<()> {
    File::open(path)?.sync_all()
}
impl Recovery {
    pub fn disabled() -> SharedRecovery {
        Arc::new(Self {
            inner: None,
            active: AtomicBool::new(false),
        })
    }
    /// Call with the app's private directory, never a shared or user-selected path.
    pub fn open(directory: PathBuf) -> SharedRecovery {
        let result = (|| -> std::io::Result<Inner> {
            let mut missing = Vec::new();
            let mut current = directory.as_path();
            while !current.exists() {
                missing.push(current.to_path_buf());
                current = current
                    .parent()
                    .ok_or_else(|| std::io::Error::other("invalid path"))?;
            }
            fs::create_dir_all(&directory)?;
            for created in missing.iter().rev() {
                sync_dir(
                    created
                        .parent()
                        .ok_or_else(|| std::io::Error::other("invalid path"))?,
                )?;
            }
            if fs::symlink_metadata(&directory)?.file_type().is_symlink() {
                return Err(std::io::Error::other("unsafe directory"));
            }
            let lock_path = directory.join("owner.lock");
            if fs::symlink_metadata(&lock_path).is_ok_and(|m| m.file_type().is_symlink()) {
                return Err(std::io::Error::other("unsafe lock"));
            }
            let file = open_private(&lock_path)?;
            crate::file_lock::try_lock_owner(&file)?;
            Ok(Inner {
                directory,
                _lock: file,
            })
        })();
        match result {
            Ok(inner) => Arc::new(Self {
                inner: Some(Mutex::new(inner)),
                active: AtomicBool::new(false),
            }),
            Err(_) => Self::disabled(),
        }
    }
    fn read(inner: &Inner) -> std::io::Result<Option<Marker>> {
        let path = inner.directory.join("pending.json");
        let metadata = match fs::symlink_metadata(&path) {
            Ok(v) => v,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(e),
        };
        if !metadata.is_file() || metadata.len() > 8192 {
            return Err(std::io::Error::other("invalid marker"));
        }
        let mut bytes = Vec::new();
        File::open(path)?.take(8193).read_to_end(&mut bytes)?;
        let marker: Marker =
            serde_json::from_slice(&bytes).map_err(|_| std::io::Error::other("invalid marker"))?;
        if marker.version != 1
            || marker.request_id.len() != 32
            || !marker
                .request_id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(std::io::Error::other("invalid marker"));
        }
        Ok(Some(marker))
    }
    pub fn status(&self) -> &'static str {
        match self
            .inner
            .as_ref()
            .and_then(|m| m.lock().ok())
            .map(|g| Self::read(&g))
        {
            Some(Ok(None)) => "ready",
            Some(Ok(Some(_))) => "pending",
            _ => "unavailable",
        }
    }
    pub fn unknown(&self) -> bool {
        self.status() != "ready"
    }
    pub fn prepare(&self, target: &InputIdentity, id: &str) -> crate::Result<()> {
        let guard = self
            .inner
            .as_ref()
            .ok_or("input_storage_unavailable")?
            .lock()
            .map_err(|_| "input_storage_unavailable")?;
        if Self::read(&guard)
            .map_err(|_| "input_storage_unavailable")?
            .is_some()
        {
            return Err("input_recovery_required");
        }
        let marker = Marker {
            version: 1,
            request_id: id.into(),
            target: target.clone(),
        };
        let raw = serde_json::to_vec(&marker).map_err(|_| "input_storage_unavailable")?;
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(guard.directory.join("pending.json"))
            .map_err(|_| "input_storage_unavailable")?;
        file.write_all(&raw)
            .and_then(|_| file.sync_all())
            .and_then(|_| sync_dir(&guard.directory))
            .map_err(|_| "input_storage_unavailable")?;
        self.active.store(true, Ordering::SeqCst);
        Ok(())
    }
    pub(crate) fn end_attempt(&self) {
        self.active.store(false, Ordering::SeqCst);
    }
    pub fn clear_confirmed(&self, target: &InputIdentity, id: Option<&str>) -> crate::Result<()> {
        let guard = self
            .inner
            .as_ref()
            .ok_or("input_storage_unavailable")?
            .lock()
            .map_err(|_| "input_storage_unavailable")?;
        if id.is_none() && self.active.load(Ordering::SeqCst) {
            return Err("input_write_pending");
        }
        let marker = Self::read(&guard)
            .map_err(|_| "input_storage_unavailable")?
            .ok_or("input_stale")?;
        if &marker.target != target || id.is_some_and(|v| v != marker.request_id) {
            return Err("input_original_target_required");
        }
        fs::remove_file(guard.directory.join("pending.json"))
            .map_err(|_| "input_storage_unavailable")?;
        // The matching server ACK (or explicit human review) already resolved
        // the write. A failed directory sync can only leave a conservative stale
        // marker after a crash; it must not turn a known result into an untracked
        // unknown in the still-running process.
        let _ = sync_dir(&guard.directory);
        Ok(())
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    fn identity() -> InputIdentity {
        InputIdentity {
            host: "127.0.0.1".into(),
            port: 22,
            user: "fixture".into(),
            host_key: "key".into(),
            socket: "/fixture/socket".into(),
            herdr: "/fixture/herdr".into(),
            session: "fixture".into(),
            pane: "w:p1".into(),
            terminal: "term_123".into(),
        }
    }
    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            use ring::rand::SecureRandom;
            let mut b = [0u8; 16];
            ring::rand::SystemRandom::new().fill(&mut b).unwrap();
            let name = b.iter().map(|v| format!("{v:02x}")).collect::<String>();
            Self(std::env::temp_dir().join(format!("herdr-input-recovery-test-{name}")))
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    #[test]
    fn restart_preserves_marker_and_only_original_target_can_confirm() {
        let temp = Temp::new();
        let id = "0123456789abcdef0123456789abcdef";
        let target = identity();
        let first = Recovery::open(temp.0.clone());
        assert!(!first.unknown());
        first.prepare(&target, id).unwrap();
        assert!(first.clear_confirmed(&target, None).is_err());
        first.end_attempt();
        let raw = fs::read_to_string(temp.0.join("pending.json")).unwrap();
        assert!(raw.contains(id));
        assert!(!raw.contains("secret-input"));
        let competing = Recovery::open(temp.0.clone());
        assert_eq!(competing.status(), "unavailable");
        assert!(competing.prepare(&target, id).is_err());
        drop(competing);
        drop(first);
        let reopened = Recovery::open(temp.0.clone());
        assert!(reopened.unknown());
        let mut other = target.clone();
        other.terminal = "term_other".into();
        assert!(reopened.clear_confirmed(&other, None).is_err());
        assert!(reopened.clear_confirmed(&target, Some("wrong")).is_err());
        assert!(reopened.unknown());
        reopened.clear_confirmed(&target, None).unwrap();
        assert!(!reopened.unknown());
    }
    #[test]
    fn malformed_marker_and_unavailable_store_fail_closed() {
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        fs::write(temp.0.join("pending.json"), b"{").unwrap();
        assert!(store.unknown());
        assert!(
            store
                .prepare(&identity(), "0123456789abcdef0123456789abcdef")
                .is_err()
        );
        assert!(store.clear_confirmed(&identity(), None).is_err());
        let disabled = Recovery::disabled();
        assert!(disabled.unknown());
        assert!(
            disabled
                .prepare(&identity(), "0123456789abcdef0123456789abcdef")
                .is_err()
        );
    }
}
