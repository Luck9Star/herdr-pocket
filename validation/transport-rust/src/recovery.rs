//! Durable public write-ahead records. Never stores input bytes.
//! One exact InputIdentity may have one pending request, across all UI aliases.
use crate::input::InputIdentity;
use serde::{Deserialize, Serialize};
use std::{
    cell::Cell,
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    sync::{Arc, Mutex, MutexGuard},
};

pub const MAX_TARGETS: usize = 32;
pub const MAX_RECORD_BYTES: usize = 8192;
pub const MAX_STORE_BYTES: usize = 262144;

#[derive(Serialize, Deserialize, Clone, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Marker {
    version: u8,
    request_id: String,
    target: InputIdentity,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    version: u8,
    // Keep original public records byte-for-byte through migration and updates.
    records: Vec<String>,
}
#[derive(Clone)]
struct Record {
    raw: String,
    marker: Marker,
}
struct Active {
    target: InputIdentity,
    request_id: String,
}
struct Inner {
    directory: PathBuf,
    owner: File,
    active: Vec<Active>,
    // Rename succeeded but directory sync failed: durability is not established.
    // Do not reopen admission in this runtime from an ordinary status read.
    uncertain: bool,
    known_store: Cell<bool>,
}
pub struct Recovery {
    inner: Option<Mutex<Inner>>,
}
pub type SharedRecovery = Arc<Recovery>;
fn invalid() -> io::Error {
    io::Error::other("invalid input recovery store")
}
fn private_options() -> OpenOptions {
    let options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut options = options;
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
        options
    }
    #[cfg(not(unix))]
    {
        options
    }
}
fn open_private(path: &Path) -> io::Result<File> {
    private_options()
        .read(true)
        .write(true)
        .create(true)
        .open(path)
}
fn sync_dir(path: &Path) -> io::Result<()> {
    let directory = private_options().read(true).open(path)?;
    if !directory.metadata()?.is_dir() {
        return Err(invalid());
    }
    directory.sync_all()
}
fn valid_id(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn validate(marker: &Marker) -> io::Result<()> {
    fn text(s: &str, max: usize) -> bool {
        !s.is_empty() && s.len() <= max && !s.chars().any(char::is_control)
    }
    let t = &marker.target;
    if marker.version != 1
        || !valid_id(&marker.request_id)
        || t.port == 0
        || !text(&t.host, 253)
        || !text(&t.user, 128)
        || !text(&t.host_key, 4096)
        || !text(&t.socket, 1024)
        || !text(&t.herdr, 1024)
        || !text(&t.session, 64)
        || !text(&t.pane, 128)
        || !text(&t.terminal, 128)
        || t.route.as_ref().is_some_and(|r| {
            r.profile_revision == 0 || !text(&r.profile_id, 256) || !text(&r.identity_ref, 256)
        })
    {
        return Err(invalid());
    }
    Ok(())
}
fn parse(raw: String) -> io::Result<Record> {
    if raw.is_empty() || raw.len() > MAX_RECORD_BYTES {
        return Err(invalid());
    }
    let marker: Marker = serde_json::from_str(&raw).map_err(|_| invalid())?;
    validate(&marker)?;
    Ok(Record { raw, marker })
}
impl Inner {
    fn verify(&self) -> io::Result<()> {
        if self.uncertain || !fs::symlink_metadata(&self.directory)?.file_type().is_dir() {
            return Err(invalid());
        }
        let path = fs::symlink_metadata(self.directory.join("owner.lock"))?;
        if !path.file_type().is_file() {
            return Err(invalid());
        }
        let owner = self.owner.metadata()?;
        if !owner.is_file() {
            return Err(invalid());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if owner.dev() != path.dev() || owner.ino() != path.ino() {
                return Err(invalid());
            }
        }
        Ok(())
    }
    fn load(&self) -> io::Result<Vec<Record>> {
        self.verify()?;
        let path = self.directory.join("pending.json");
        match fs::symlink_metadata(&path) {
            Err(e) if e.kind() == io::ErrorKind::NotFound && !self.known_store.get() => {
                return Ok(Vec::new());
            }
            Err(e) => return Err(e),
            Ok(m) if !m.file_type().is_file() || m.len() > MAX_STORE_BYTES as u64 => {
                return Err(invalid());
            }
            _ => {}
        }
        self.known_store.set(true);
        let mut file = private_options().read(true).open(path)?;
        if !file.metadata()?.is_file() {
            return Err(invalid());
        }
        let mut raw = String::new();
        Read::by_ref(&mut file)
            .take((MAX_STORE_BYTES + 1) as u64)
            .read_to_string(&mut raw)?;
        if raw.len() > MAX_STORE_BYTES {
            return Err(invalid());
        }
        if let Ok(envelope) = serde_json::from_str::<Envelope>(&raw) {
            if envelope.version != 2 || envelope.records.len() > MAX_TARGETS {
                return Err(invalid());
            }
            let mut records: Vec<Record> = Vec::with_capacity(envelope.records.len());
            for raw in envelope.records {
                let record = parse(raw)?;
                if records
                    .iter()
                    .any(|old| old.marker.target == record.marker.target)
                {
                    return Err(invalid());
                }
                records.push(record);
            }
            return Ok(records);
        }
        // Strict old version 1, with absent route retaining system semantics.
        // It is not filled from a selected host or rewritten during a read.
        Ok(vec![parse(raw)?])
    }
    fn persist(&mut self, records: &[Record]) -> crate::Result<()> {
        self.verify().map_err(|_| "input_storage_unavailable")?;
        if records.len() > MAX_TARGETS {
            return Err("input_storage_capacity");
        }
        let raw = serde_json::to_vec(&Envelope {
            version: 2,
            records: records.iter().map(|r| r.raw.clone()).collect(),
        })
        .map_err(|_| "input_storage_unavailable")?;
        if raw.len() > MAX_STORE_BYTES {
            return Err("input_storage_capacity");
        }
        let id = crate::input::random_id().ok_or("input_storage_unavailable")?;
        let temporary = self.directory.join(format!("pending-{id}.tmp"));
        let destination = self.directory.join("pending.json");
        let staged = (|| -> io::Result<()> {
            let mut file = private_options()
                .write(true)
                .create_new(true)
                .open(&temporary)?;
            file.write_all(&raw)?;
            file.sync_all()?;
            // Do not remove destination first. Platforms without replace-by-
            // rename or directory sync reject the write, never create a gap.
            fs::rename(&temporary, &destination)?;
            self.known_store.set(true);
            if let Err(error) = sync_dir(&self.directory) {
                self.uncertain = true;
                return Err(error);
            }
            Ok(())
        })();
        if staged.is_err() {
            // Staging does not authorize input. Before rename, the old ledger
            // remains intact; after rename, uncertainty keeps admission closed.
            let _ = fs::remove_file(&temporary);
        }
        staged.map_err(|_| "input_storage_unavailable")
    }
}
impl Recovery {
    pub fn disabled() -> SharedRecovery {
        Arc::new(Self { inner: None })
    }
    /// The caller supplies the app-private directory, never a picker path.
    pub fn open(directory: PathBuf) -> SharedRecovery {
        let result = (|| -> io::Result<Inner> {
            let mut missing = Vec::new();
            let mut current = directory.as_path();
            while !current.exists() {
                missing.push(current.to_path_buf());
                current = current.parent().ok_or_else(invalid)?;
            }
            fs::create_dir_all(&directory)?;
            for created in missing.iter().rev() {
                sync_dir(created.parent().ok_or_else(invalid)?)?;
            }
            if !fs::symlink_metadata(&directory)?.file_type().is_dir() {
                return Err(invalid());
            }
            let lock_path = directory.join("owner.lock");
            if fs::symlink_metadata(&lock_path).is_ok_and(|m| !m.file_type().is_file()) {
                return Err(invalid());
            }
            let owner = open_private(&lock_path)?;
            crate::file_lock::try_lock_owner(&owner)?;
            let inner = Inner {
                directory,
                owner,
                active: Vec::new(),
                uncertain: false,
                known_store: Cell::new(false),
            };
            inner.load()?;
            Ok(inner)
        })();
        match result {
            Ok(inner) => Arc::new(Self {
                inner: Some(Mutex::new(inner)),
            }),
            Err(_) => Self::disabled(),
        }
    }
    fn lock(&self) -> crate::Result<MutexGuard<'_, Inner>> {
        self.inner
            .as_ref()
            .ok_or("input_storage_unavailable")?
            .lock()
            .map_err(|_| "input_storage_unavailable")
    }
    /// Diagnostics across every target. Input admission uses status_for instead.
    pub fn status(&self) -> &'static str {
        match self.lock().and_then(|g| {
            g.load()
                .map(|records| records.is_empty() && g.active.is_empty())
                .map_err(|_| "input_storage_unavailable")
        }) {
            Ok(true) => "ready",
            Ok(false) => "pending",
            Err(_) => "unavailable",
        }
    }
    pub fn unknown(&self) -> bool {
        self.status() != "ready"
    }
    pub fn status_for(&self, target: &InputIdentity) -> &'static str {
        match self.lock().and_then(|g| {
            g.load()
                .map(|records| {
                    records.iter().any(|r| r.marker.target == *target)
                        || g.active.iter().any(|a| a.target == *target)
                })
                .map_err(|_| "input_storage_unavailable")
        }) {
            Ok(false) => "ready",
            Ok(true) => "pending",
            Err(_) => "unavailable",
        }
    }
    pub fn unknown_for(&self, target: &InputIdentity) -> bool {
        self.status_for(target) != "ready"
    }
    pub fn pending_id(&self, target: &InputIdentity) -> crate::Result<Option<String>> {
        let guard = self.lock()?;
        let records = guard.load().map_err(|_| "input_storage_unavailable")?;
        Ok(records
            .into_iter()
            .find(|r| r.marker.target == *target)
            .map(|r| r.marker.request_id))
    }
    pub fn prepare(&self, target: &InputIdentity, id: &str) -> crate::Result<()> {
        let marker = Marker {
            version: 1,
            request_id: id.into(),
            target: target.clone(),
        };
        validate(&marker).map_err(|_| "input_storage_unavailable")?;
        let raw = serde_json::to_string(&marker).map_err(|_| "input_storage_unavailable")?;
        if raw.len() > MAX_RECORD_BYTES {
            return Err("input_record_limit");
        }
        let mut guard = self.lock()?;
        let mut records = guard.load().map_err(|_| "input_storage_unavailable")?;
        if records.iter().any(|r| r.marker.target == *target) {
            return Err("input_recovery_required");
        }
        if guard.active.iter().any(|a| a.target == *target) {
            return Err("input_write_pending");
        }
        let retained = guard
            .active
            .iter()
            .filter(|a| !records.iter().any(|r| r.marker.target == a.target))
            .count();
        if records.len() + retained >= MAX_TARGETS {
            return Err("input_storage_capacity");
        }
        records.push(Record { raw, marker });
        guard.persist(&records)?;
        guard.active.push(Active {
            target: target.clone(),
            request_id: id.into(),
        });
        Ok(())
    }
    pub(crate) fn end_attempt(&self, target: &InputIdentity, id: &str) {
        if let Ok(mut guard) = self.lock() {
            guard
                .active
                .retain(|a| a.target != *target || a.request_id != id);
        }
    }
    /// Exact correlated server result. None is retained for storage-level
    /// compatibility only; UI review must use a captured ID with clear_reviewed.
    pub fn clear_confirmed(&self, target: &InputIdentity, id: Option<&str>) -> crate::Result<()> {
        self.clear(target, id, id.is_none())
    }
    pub fn clear_reviewed(&self, target: &InputIdentity, id: &str) -> crate::Result<()> {
        self.clear(target, Some(id), true)
    }
    fn clear(&self, target: &InputIdentity, id: Option<&str>, reviewed: bool) -> crate::Result<()> {
        let mut guard = self.lock()?;
        let mut records = guard.load().map_err(|_| "input_storage_unavailable")?;
        let index = records
            .iter()
            .position(|r| r.marker.target == *target)
            .ok_or(if records.is_empty() {
                "input_stale"
            } else {
                "input_original_target_required"
            })?;
        if id.is_some_and(|id| id != records[index].marker.request_id) {
            return Err("input_original_target_required");
        }
        if reviewed && guard.active.iter().any(|a| a.target == *target) {
            return Err("input_write_pending");
        }
        records.remove(index);
        guard.persist(&records)
    }
}
#[cfg(all(test, unix))]
mod tests {
    use super::*;
    fn identity() -> InputIdentity {
        InputIdentity {
            route: None,
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
        first.end_attempt(&target, id);
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
    #[test]
    fn overlay_recovery_requires_exact_durable_route_and_legacy_remains_system_only() {
        use crate::transport::{OverlayProvider, OverlayRouteIdentity};
        let temp = Temp::new();
        let id = "0123456789abcdef0123456789abcdef";
        let system = identity();
        let mut overlay = system.clone();
        overlay.route = Some(OverlayRouteIdentity {
            provider: OverlayProvider::EasyTier,
            profile_id: "phone-a".into(),
            profile_revision: 7,
            identity_ref: "device-safe-ref".into(),
        });
        let store = Recovery::open(temp.0.clone());
        store.prepare(&system, id).unwrap();
        store.end_attempt(&system, id);
        // An old marker has no route field. Deserializing it means system,
        // and an overlay connection may never confirm or erase it.
        let raw = fs::read_to_string(temp.0.join("pending.json")).unwrap();
        assert!(!raw.contains("route"));
        assert!(store.clear_confirmed(&overlay, None).is_err());
        store.clear_confirmed(&system, None).unwrap();
        store.prepare(&overlay, id).unwrap();
        store.end_attempt(&overlay, id);
        drop(store);
        let reopened = Recovery::open(temp.0.clone());
        assert!(reopened.clear_confirmed(&system, None).is_err());
        for variant in 0..4 {
            let mut other = overlay.clone();
            let route = other.route.as_mut().unwrap();
            match variant {
                0 => route.profile_id = "phone-b".into(),
                1 => route.profile_revision += 1,
                2 => route.identity_ref = "another-device-ref".into(),
                _ => route.provider = OverlayProvider::Tailscale,
            }
            assert!(reopened.clear_confirmed(&other, None).is_err());
            assert!(reopened.unknown());
        }
        // The durable route is unchanged across reconnect/restart; no owner
        // or process-local native epoch appears in this identity.
        reopened.clear_confirmed(&overlay, None).unwrap();
        assert!(!reopened.unknown());
    }
    fn request(n: usize) -> String {
        format!("{n:032x}")
    }
    fn target(n: usize) -> InputIdentity {
        let mut t = identity();
        t.pane = format!("w:p{n}");
        t.terminal = format!("term_{n:x}");
        t
    }
    fn records(temp: &Temp) -> Vec<String> {
        let envelope: Envelope =
            serde_json::from_slice(&fs::read(temp.0.join("pending.json")).unwrap()).unwrap();
        assert_eq!(envelope.version, 2);
        envelope.records
    }
    #[test]
    fn legacy_migrates_on_mutation_without_rebinding_or_changing_original_bytes() {
        let temp = Temp::new();
        fs::create_dir(&temp.0).unwrap();
        let a = target(1);
        let b = target(2);
        let raw = serde_json::to_string_pretty(&Marker {
            version: 1,
            request_id: request(1),
            target: a.clone(),
        })
        .unwrap()
            + "\n";
        fs::write(temp.0.join("pending.json"), &raw).unwrap();
        let store = Recovery::open(temp.0.clone());
        assert_eq!(store.pending_id(&a).unwrap(), Some(request(1)));
        assert_eq!(store.status_for(&b), "ready");
        assert_eq!(
            fs::read_to_string(temp.0.join("pending.json")).unwrap(),
            raw
        );
        store.prepare(&b, &request(2)).unwrap();
        assert_eq!(records(&temp)[0], raw);
        store.clear_confirmed(&b, Some(&request(2))).unwrap();
        store.end_attempt(&b, &request(2));
        assert_eq!(records(&temp), vec![raw]);
        assert_eq!(store.status_for(&a), "pending");
        assert_eq!(store.status_for(&b), "ready");
    }
    #[test]
    fn exact_attempt_retirement_and_review_cannot_touch_newer_or_other_active_requests() {
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        let a = target(1);
        let b = target(2);
        store.prepare(&a, &request(1)).unwrap();
        store.end_attempt(&a, &request(1));
        let reviewed = store.pending_id(&a).unwrap().unwrap();
        store.clear_reviewed(&a, &reviewed).unwrap();
        store.prepare(&a, &request(3)).unwrap();
        store.prepare(&b, &request(2)).unwrap();
        store.end_attempt(&a, &request(1));
        store.end_attempt(&b, &request(1));
        assert_eq!(
            store.clear_reviewed(&a, &request(3)),
            Err("input_write_pending")
        );
        assert_eq!(
            store.clear_reviewed(&b, &request(2)),
            Err("input_write_pending")
        );
        assert_eq!(
            store.clear_reviewed(&a, &reviewed),
            Err("input_original_target_required")
        );
        assert_eq!(
            store.clear_confirmed(&a, Some(&reviewed)),
            Err("input_original_target_required")
        );
        assert_eq!(records(&temp).len(), 2);
        store.clear_confirmed(&a, Some(&request(3))).unwrap();
        assert_eq!(store.prepare(&a, &request(4)), Err("input_write_pending"));
        store.end_attempt(&a, &request(1));
        assert_eq!(store.prepare(&a, &request(4)), Err("input_write_pending"));
        store.end_attempt(&a, &request(3));
        store.prepare(&a, &request(4)).unwrap();
        store.end_attempt(&b, &request(2));
        store.clear_reviewed(&b, &request(2)).unwrap();
        assert_eq!(store.pending_id(&a).unwrap(), Some(request(4)));
    }
    #[test]
    fn target_limit_never_evicts_unknown_and_retiring_one_target_does_not_free_another() {
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        for n in 1..=MAX_TARGETS {
            store.prepare(&target(n), &request(n)).unwrap();
            store.end_attempt(&target(n), &request(n));
        }
        let before = fs::read(temp.0.join("pending.json")).unwrap();
        assert_eq!(
            store.prepare(&target(33), &request(33)),
            Err("input_storage_capacity")
        );
        assert_eq!(fs::read(temp.0.join("pending.json")).unwrap(), before);
        store.clear_reviewed(&target(17), &request(17)).unwrap();
        store.prepare(&target(33), &request(33)).unwrap();
        assert_eq!(records(&temp).len(), 32);
        assert_eq!(store.pending_id(&target(1)).unwrap(), Some(request(1)));
        let active = Temp::new();
        let store = Recovery::open(active.0.clone());
        for n in 1..=MAX_TARGETS {
            store.prepare(&target(n), &request(n)).unwrap();
            store
                .clear_confirmed(&target(n), Some(&request(n)))
                .unwrap();
        }
        assert_eq!(
            store.prepare(&target(33), &request(33)),
            Err("input_storage_capacity")
        );
        store.end_attempt(&target(1), &request(2));
        assert_eq!(
            store.prepare(&target(33), &request(33)),
            Err("input_storage_capacity")
        );
        store.end_attempt(&target(1), &request(1));
        store.prepare(&target(33), &request(33)).unwrap();
    }
    #[test]
    fn record_and_total_utf8_limits_leave_all_existing_records_unchanged() {
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        let mut oversized = target(1);
        oversized.host_key = "\"".repeat(4096);
        assert_eq!(
            store.prepare(&oversized, &request(1)),
            Err("input_record_limit")
        );
        assert!(!temp.0.join("pending.json").exists());
        let mut raw = Vec::new();
        for n in 1..=31 {
            let marker = serde_json::to_string(&Marker {
                version: 1,
                request_id: request(n),
                target: target(n),
            })
            .unwrap();
            raw.push(format!("{marker:width$}", width = MAX_RECORD_BYTES));
        }
        let wire = serde_json::to_vec(&Envelope {
            version: 2,
            records: raw.clone(),
        })
        .unwrap();
        assert!(wire.len() <= MAX_STORE_BYTES);
        fs::write(temp.0.join("pending.json"), &wire).unwrap();
        let mut large = target(32);
        large.host_key = "\"".repeat(2000);
        assert_eq!(
            store.prepare(&large, &request(32)),
            Err("input_storage_capacity")
        );
        assert_eq!(fs::read(temp.0.join("pending.json")).unwrap(), wire);
        assert_eq!(records(&temp), raw);
        let fixture: serde_json::Value =
            serde_json::from_str(include_str!("../../shared/target-input-journal-v1.json"))
                .unwrap();
        assert_eq!(fixture["limits"]["maxTargets"], MAX_TARGETS);
        assert_eq!(fixture["limits"]["maxRecordUtf8Bytes"], MAX_RECORD_BYTES);
        assert_eq!(fixture["limits"]["maxStoreUtf8Bytes"], MAX_STORE_BYTES);
    }
    #[test]
    fn concurrent_aliases_have_one_pending_and_distinct_prepare_clear_preserve_unknown() {
        use std::sync::Barrier;
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        let barrier = Arc::new(Barrier::new(16));
        let workers: Vec<_> = (1..=16)
            .map(|n| {
                let store = store.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    store.prepare(&target(1), &request(n))
                })
            })
            .collect();
        assert_eq!(
            workers
                .into_iter()
                .map(|w| w.join().unwrap())
                .filter(Result::is_ok)
                .count(),
            1
        );
        assert_eq!(records(&temp).len(), 1);
        let a = records(&temp)[0].clone();
        let barrier = Arc::new(Barrier::new(16));
        let workers: Vec<_> = (2..=17)
            .map(|n| {
                let store = store.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    store.prepare(&target(n), &request(n)).unwrap();
                    store
                        .clear_confirmed(&target(n), Some(&request(n)))
                        .unwrap();
                    store.end_attempt(&target(n), &request(n));
                })
            })
            .collect();
        for worker in workers {
            worker.join().unwrap();
        }
        assert_eq!(records(&temp), vec![a]);
    }
    #[test]
    fn corrupt_duplicate_unknown_version_and_oversized_stores_are_never_empty() {
        let a = serde_json::to_string(&Marker {
            version: 1,
            request_id: request(1),
            target: target(1),
        })
        .unwrap();
        let mut duplicate: Marker = serde_json::from_str(&a).unwrap();
        duplicate.request_id = request(2);
        let cases=vec![
            "{".into(),
            serde_json::json!({"version":3,"records":[]}).to_string(),
            serde_json::json!({"version":2,"records":[a.clone(),serde_json::to_string(&duplicate).unwrap()]}).to_string(),
            serde_json::json!({"version":2,"records":[" ".repeat(MAX_RECORD_BYTES+1)]}).to_string(),
            serde_json::json!({"version":2,"records":[a.clone()],"input":"not permitted"}).to_string(),
            format!("{{\"version\":2,\"version\":2,\"records\":[]}}"),
            serde_json::json!({"version":2,"records":vec![a.clone();33]}).to_string(),
            " ".repeat(MAX_STORE_BYTES+1),
        ];
        for wire in cases {
            let temp = Temp::new();
            fs::create_dir(&temp.0).unwrap();
            fs::write(temp.0.join("pending.json"), wire.as_bytes()).unwrap();
            let store = Recovery::open(temp.0.clone());
            assert_eq!(store.status_for(&target(1)), "unavailable");
            assert!(store.prepare(&target(2), &request(2)).is_err());
            assert!(store.clear_reviewed(&target(1), &request(1)).is_err());
            assert_eq!(
                fs::read(temp.0.join("pending.json")).unwrap(),
                wire.as_bytes()
            );
        }
    }
    #[test]
    fn symlinks_and_replaced_owner_lock_fail_closed_without_writing_their_destinations() {
        use std::os::unix::fs::symlink;
        let victim = Temp::new();
        fs::create_dir(&victim.0).unwrap();
        let destination = victim.0.join("original");
        fs::write(&destination, b"untouched").unwrap();
        let temp = Temp::new();
        fs::create_dir(&temp.0).unwrap();
        symlink(&destination, temp.0.join("pending.json")).unwrap();
        let store = Recovery::open(temp.0.clone());
        assert_eq!(store.status(), "unavailable");
        assert!(store.prepare(&target(1), &request(1)).is_err());
        assert_eq!(fs::read(&destination).unwrap(), b"untouched");
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        store.prepare(&target(1), &request(1)).unwrap();
        fs::rename(temp.0.join("owner.lock"), temp.0.join("retired.lock")).unwrap();
        fs::write(temp.0.join("owner.lock"), b"").unwrap();
        assert_eq!(store.status(), "unavailable");
        assert!(
            store
                .clear_confirmed(&target(1), Some(&request(1)))
                .is_err()
        );
        let deleted = Temp::new();
        let store = Recovery::open(deleted.0.clone());
        store.prepare(&target(1), &request(1)).unwrap();
        store.end_attempt(&target(1), &request(1));
        fs::remove_file(deleted.0.join("pending.json")).unwrap();
        assert_eq!(store.status(), "unavailable");
        assert!(store.prepare(&target(2), &request(2)).is_err());
        assert!(!deleted.0.join("pending.json").exists());
    }
    #[test]
    fn pre_replace_io_failure_preserves_unknown_and_unrelated_target_can_resume_after_storage_recovers()
     {
        use std::os::unix::fs::PermissionsExt;
        if unsafe { libc::geteuid() } == 0 {
            return;
        }
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        let a = target(1);
        let b = target(2);
        store.prepare(&a, &request(1)).unwrap();
        store.end_attempt(&a, &request(1));
        let old = records(&temp)[0].clone();
        struct Restore(PathBuf);
        impl Drop for Restore {
            fn drop(&mut self) {
                let _ = fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700));
            }
        }
        let restore = Restore(temp.0.clone());
        fs::set_permissions(&temp.0, fs::Permissions::from_mode(0o500)).unwrap();
        assert_eq!(
            store.clear_reviewed(&a, &request(1)),
            Err("input_storage_unavailable")
        );
        assert_eq!(store.status_for(&a), "pending");
        assert_eq!(store.status_for(&b), "ready");
        assert_eq!(records(&temp), vec![old.clone()]);
        drop(restore);
        store.prepare(&b, &request(2)).unwrap();
        store.clear_confirmed(&b, Some(&request(2))).unwrap();
        store.end_attempt(&b, &request(2));
        assert_eq!(records(&temp), vec![old]);
    }
    #[test]
    fn every_persistent_identity_field_remains_part_of_recovery_binding() {
        use crate::transport::{OverlayProvider, OverlayRouteIdentity};
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        let a = target(1);
        let id = request(1);
        store.prepare(&a, &id).unwrap();
        store.end_attempt(&a, &id);
        let before = records(&temp);
        for changed in 0..10 {
            let mut other = a.clone();
            match changed {
                0 => other.host = "other.example".into(),
                1 => other.port += 1,
                2 => other.user = "other-user".into(),
                3 => other.host_key = "other-key".into(),
                4 => other.socket = "/other/socket".into(),
                5 => other.herdr = "/other/herdr".into(),
                6 => other.session = "other-session".into(),
                7 => other.pane = "w:p2".into(),
                8 => other.terminal = "term_def".into(),
                _ => {
                    other.route = Some(OverlayRouteIdentity {
                        provider: OverlayProvider::EasyTier,
                        profile_id: "network".into(),
                        profile_revision: 1,
                        identity_ref: "vault-ref".into(),
                    })
                }
            }
            assert_eq!(store.status_for(&other), "ready");
            assert_eq!(
                store.clear_reviewed(&other, &id),
                Err("input_original_target_required")
            );
            assert_eq!(records(&temp), before);
        }
    }
    #[test]
    fn post_rename_directory_sync_failure_latches_unavailable_until_reopen() {
        use std::os::unix::fs::PermissionsExt;
        if unsafe { libc::geteuid() } == 0 {
            return;
        }
        let temp = Temp::new();
        let store = Recovery::open(temp.0.clone());
        let a = target(1);
        let b = target(2);
        store.prepare(&a, &request(1)).unwrap();
        store.end_attempt(&a, &request(1));
        store.prepare(&b, &request(2)).unwrap();
        store.end_attempt(&b, &request(2));
        let b_raw = records(&temp)[1].clone();
        struct Restore(PathBuf);
        impl Drop for Restore {
            fn drop(&mut self) {
                let _ = fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700));
            }
        }
        let restore = Restore(temp.0.clone());
        // Write+execute permits create/rename, but denies opening the directory
        // for the required fsync. This is an actual local I/O failure.
        fs::set_permissions(&temp.0, fs::Permissions::from_mode(0o300)).unwrap();
        assert_eq!(
            store.clear_reviewed(&a, &request(1)),
            Err("input_storage_unavailable")
        );
        drop(restore);
        assert_eq!(store.status_for(&a), "unavailable");
        assert_eq!(store.status_for(&b), "unavailable");
        assert!(store.prepare(&target(3), &request(3)).is_err());
        assert_eq!(records(&temp), vec![b_raw.clone()]);
        drop(store);
        let reopened = Recovery::open(temp.0.clone());
        assert_eq!(reopened.status_for(&a), "ready");
        assert_eq!(reopened.status_for(&b), "pending");
        assert_eq!(records(&temp), vec![b_raw]);
    }
}
