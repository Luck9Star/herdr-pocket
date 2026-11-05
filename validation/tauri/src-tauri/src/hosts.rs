//! App-private, bounded host records. Handles never cross the frontend bridge.
use herdr_readonly_transport::{
    RemoteConfig,
    pairing::{Pairing, PairingReference, ReferenceStatus, random_public_id},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::PathBuf,
    sync::Mutex,
};

const MAX_HOSTS: usize = 32;
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Target {
    pub host: String,
    pub port: u16,
    pub username: String,
    pub expected_host_key: String,
    pub socket_path: String,
    pub herdr_path: String,
    pub session: String,
}
impl Target {
    pub fn config(&self) -> RemoteConfig {
        RemoteConfig {
            schema_version: 1,
            host: self.host.clone(),
            port: self.port,
            username: self.username.clone(),
            expected_host_key: self.expected_host_key.clone(),
            private_key_pem: String::new(),
            socket_path: self.socket_path.clone(),
            herdr_path: self.herdr_path.clone(),
            session: self.session.clone(),
            pane_id: String::new(),
            review_confirmed: true,
        }
    }
    pub fn from_config(c: &RemoteConfig) -> Self {
        Self {
            host: c.host.clone(),
            port: c.port,
            username: c.username.clone(),
            expected_host_key: c.expected_host_key.clone(),
            socket_path: c.socket_path.clone(),
            herdr_path: c.herdr_path.clone(),
            session: c.session.clone(),
        }
    }
    fn validate(&self) -> Result<(), String> {
        self.config().validate_pair_target().map_err(str::to_string)
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub id: String,
    pub name: String,
    pub enabled: bool,
    pub target: Target,
    pub pairing: Option<PairingReference>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Disk {
    version: u8,
    hosts: Vec<Record>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct View {
    pub id: String,
    pub name: String,
    pub enabled: bool,
    pub target: Target,
    pub device_fingerprint: Option<String>,
    pub host_fingerprint: String,
    pub pairing_status: Option<ReferenceStatus>,
}
impl Record {
    fn validate(&self) -> Result<(), String> {
        if self.id.len() != 32
            || !self
                .id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || !valid_name(&self.name)
        {
            return Err("invalid_host_record".into());
        }
        self.target.validate()?;
        if let Some(r) = &self.pairing {
            if r.handle.is_empty()
                || r.handle.len() > 128
                || Pairing::reference_fingerprint(r).is_err()
            {
                return Err("invalid_host_record".into());
            }
        }
        Ok(())
    }
    pub fn view(&self) -> Result<View, String> {
        Ok(View {
            id: self.id.clone(),
            name: self.name.clone(),
            enabled: self.enabled,
            target: self.target.clone(),
            device_fingerprint: self
                .pairing
                .as_ref()
                .map(Pairing::reference_fingerprint)
                .transpose()
                .map_err(str::to_string)?,
            host_fingerprint: herdr_readonly_transport::pairing::fingerprint(
                &self.target.expected_host_key,
            )
            .map_err(str::to_string)?,
            pairing_status: self.pairing.as_ref().map(|p| p.status),
        })
    }
}
fn valid_name(name: &str) -> bool {
    !name.trim().is_empty() && name.len() <= 96 && !name.chars().any(char::is_control)
}
struct Repository {
    dir: PathBuf,
    _lock: File,
    items: Vec<Record>,
}
pub struct Hosts(Mutex<Option<Repository>>);
impl Default for Hosts {
    fn default() -> Self {
        Self(Mutex::new(None))
    }
}
fn private_options() -> OpenOptions {
    let mut o = OpenOptions::new();
    o.read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    o
}
impl Repository {
    fn open(dir: PathBuf) -> Result<Self, String> {
        fs::create_dir_all(&dir).map_err(|_| "host_storage_unavailable")?;
        if fs::symlink_metadata(&dir)
            .map_err(|_| "host_storage_unavailable")?
            .file_type()
            .is_symlink()
        {
            return Err("host_storage_unavailable".into());
        }
        let lock_path = dir.join("owner.lock");
        if fs::symlink_metadata(&lock_path).is_ok_and(|m| m.file_type().is_symlink()) {
            return Err("host_storage_unavailable".into());
        }
        let lock = private_options()
            .create(true)
            .open(lock_path)
            .map_err(|_| "host_storage_unavailable")?;
        herdr_readonly_transport::file_lock::try_lock_owner(&lock).map_err(|error| {
            if error.kind() == std::io::ErrorKind::WouldBlock { "host_storage_busy" }
            else { "host_storage_lock_failed" }
        })?;
        let path = dir.join("hosts.json");
        let items = match fs::symlink_metadata(&path) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Vec::new(),
            Ok(m) if m.is_file() && m.len() <= 131072 => {
                let mut raw = Vec::new();
                File::open(path)
                    .and_then(|f| f.take(131073).read_to_end(&mut raw))
                    .map_err(|_| "host_storage_unavailable")?;
                let disk: Disk =
                    serde_json::from_slice(&raw).map_err(|_| "host_storage_corrupt")?;
                if disk.version != 1 {
                    return Err("host_storage_corrupt".into());
                }
                disk.hosts
            }
            _ => return Err("host_storage_corrupt".into()),
        };
        if items.len() > MAX_HOSTS {
            return Err("host_storage_corrupt".into());
        }
        let mut ids = HashSet::new();
        let mut handles = HashSet::new();
        for r in &items {
            r.validate()?;
            if !ids.insert(&r.id)
                || r.pairing
                    .as_ref()
                    .is_some_and(|p| !handles.insert(&p.handle))
            {
                return Err("host_storage_corrupt".into());
            }
        }
        Ok(Self {
            dir,
            _lock: lock,
            items,
        })
    }
    fn commit(&mut self, items: Vec<Record>) -> Result<(), String> {
        if items.len() > MAX_HOSTS {
            return Err("host_limit".into());
        }
        for r in &items {
            r.validate()?;
        }
        let bytes = serde_json::to_vec(&Disk {
            version: 1,
            hosts: items.clone(),
        })
        .map_err(|_| "host_storage_unavailable")?;
        if bytes.len() > 131072 {
            return Err("host_limit".into());
        }
        let temp = self.dir.join(format!(
            "hosts-{}.tmp",
            random_public_id().map_err(str::to_string)?
        ));
        let result = (|| -> std::io::Result<()> {
            let mut file = private_options().create_new(true).open(&temp)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            fs::rename(&temp, self.dir.join("hosts.json"))?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temp);
            return Err("host_storage_unavailable".into());
        }
        self.items = items;
        // A lost directory sync can leave only the old or new complete record set.
        File::open(&self.dir)
            .and_then(|f| f.sync_all())
            .map_err(|_| "host_storage_unavailable".to_string())
    }
}
impl Hosts {
    pub fn init(&self, dir: PathBuf) -> Result<(), String> {
        let mut slot = self.0.lock().map_err(|_| "host_storage_unavailable")?;
        if slot.is_none() {
            *slot = Some(Repository::open(dir)?);
        }
        Ok(())
    }
    fn with<T>(&self, f: impl FnOnce(&mut Repository) -> Result<T, String>) -> Result<T, String> {
        let mut slot = self.0.lock().map_err(|_| "host_storage_unavailable")?;
        f(slot.as_mut().ok_or("host_storage_unavailable")?)
    }
    pub fn initialized(&self) -> Result<bool, String> {
        Ok(self
            .0
            .lock()
            .map_err(|_| "host_storage_unavailable")?
            .is_some())
    }
    pub fn list(&self) -> Result<Vec<View>, String> {
        self.with(|r| r.items.iter().map(Record::view).collect())
    }
    pub fn get(&self, id: &str) -> Result<Record, String> {
        self.with(|r| {
            r.items
                .iter()
                .find(|x| x.id == id)
                .cloned()
                .ok_or("host_missing".into())
        })
    }
    pub fn save(
        &self,
        id: Option<&str>,
        name: &str,
        target: Target,
        pairing: Option<PairingReference>,
    ) -> Result<View, String> {
        self.with(|r| {
            if !valid_name(name) {
                return Err("invalid_host_name".into());
            }
            target.validate()?;
            let mut list = r.items.clone();
            let host_id = if let Some(id) = id {
                let old = list.iter_mut().find(|x| x.id == id).ok_or("host_missing")?;
                if old.target != target {
                    return Err("host_target_changed".into());
                }
                old.name = name.into();
                if pairing.is_some() {
                    old.pairing = pairing;
                }
                id.to_string()
            } else {
                if list.iter().any(|h| h.target == target) {
                    return Err("host_already_exists".into());
                }
                let id = random_public_id().map_err(str::to_string)?;
                list.push(Record {
                    id: id.clone(),
                    name: name.into(),
                    enabled: true,
                    target,
                    pairing,
                });
                id
            };
            let mut seen = HashSet::new();
            if list
                .iter()
                .filter_map(|h| h.pairing.as_ref())
                .any(|p| !seen.insert(&p.handle))
            {
                return Err("host_key_in_use".into());
            }
            let view = list
                .iter()
                .find(|h| h.id == host_id)
                .ok_or("host_missing")?
                .view()?;
            r.commit(list)?;
            Ok(view)
        })
    }
    pub fn update(
        &self,
        id: &str,
        name: Option<&str>,
        enabled: Option<bool>,
    ) -> Result<(), String> {
        self.with(|r| {
            let mut list = r.items.clone();
            let h = list.iter_mut().find(|x| x.id == id).ok_or("host_missing")?;
            if let Some(n) = name {
                if !valid_name(n) {
                    return Err("invalid_host_name".into());
                }
                h.name = n.into();
            }
            if let Some(v) = enabled {
                h.enabled = v;
            }
            r.commit(list)
        })
    }
    pub fn attach_pending(
        &self,
        id: &str,
        target: &Target,
        reference: PairingReference,
    ) -> Result<(), String> {
        self.with(|r| {
            let mut list = r.items.clone();
            if list
                .iter()
                .filter_map(|h| h.pairing.as_ref())
                .any(|p| p.handle == reference.handle)
            {
                return Err("host_key_in_use".into());
            }
            let h = list.iter_mut().find(|h| h.id == id).ok_or("host_missing")?;
            if !h.enabled
                || &h.target != target
                || h.pairing.is_some()
                || reference.status != ReferenceStatus::AwaitingHost
            {
                return Err("host_pairing_exists".into());
            }
            h.pairing = Some(reference);
            r.commit(list)
        })
    }
    pub fn set_status(&self, handle: &str, status: ReferenceStatus) -> Result<(), String> {
        self.with(|r| {
            let mut list = r.items.clone();
            let h = list
                .iter_mut()
                .find(|h| h.pairing.as_ref().is_some_and(|p| p.handle == handle))
                .ok_or("host_pairing_missing")?;
            h.pairing.as_mut().ok_or("host_pairing_missing")?.status = status;
            r.commit(list)
        })
    }
    pub fn remove(&self, id: &str) -> Result<Record, String> {
        self.with(|r| {
            let mut list = r.items.clone();
            let pos = list.iter().position(|h| h.id == id).ok_or("host_missing")?;
            let removed = list.remove(pos);
            r.commit(list)?;
            Ok(removed)
        })
    }
    pub fn clear_handle(&self, handle: &str) -> Result<(), String> {
        self.with(|r| {
            let mut list = r.items.clone();
            let mut changed = false;
            for h in &mut list {
                if h.pairing.as_ref().is_some_and(|p| p.handle == handle) {
                    h.pairing = None;
                    h.enabled = false;
                    changed = true;
                }
            }
            if changed {
                r.commit(list)?;
            }
            Ok(())
        })
    }
    pub fn contains_handle(&self, handle: &str) -> Result<bool, String> {
        self.with(|r| {
            Ok(r.items
                .iter()
                .any(|x| x.pairing.as_ref().is_some_and(|p| p.handle == handle)))
        })
    }
}

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
mod tests {
    use super::*;
    use herdr_readonly_transport::pairing::{KeyStore, VolatileKeyStore};
    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            Self(
                std::env::temp_dir()
                    .join(format!("herdr-hosts-test-{}", random_public_id().unwrap())),
            )
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    fn target() -> Target {
        let (_, key) = VolatileKeyStore::default().create().unwrap();
        Target {
            host: "127.0.0.1".into(),
            port: 22,
            username: "fixture".into(),
            expected_host_key: key,
            socket_path: "/tmp/root/herdr/sessions/work/herdr.sock".into(),
            herdr_path: "/usr/bin/herdr".into(),
            session: "work".into(),
        }
    }
    #[test]
    fn records_persist_disable_and_reject_target_replacement() {
        let temp = Temp::new();
        let store = Hosts::default();
        store.init(temp.0.clone()).unwrap();
        let t = target();
        let host = store.save(None, "工作站", t.clone(), None).unwrap();
        assert!(store.save(None, "duplicate", t.clone(), None).is_err());
        let mut changed = t.clone();
        changed.host = "example.com".into();
        assert!(store.save(Some(&host.id), "same", changed, None).is_err());
        store.update(&host.id, Some("改名"), Some(false)).unwrap();
        let raw = fs::read_to_string(temp.0.join("hosts.json")).unwrap();
        assert!(
            !raw.contains("privateKeyPem") && !raw.contains("seed") && !raw.contains("password")
        );
        let competitor = Hosts::default();
        assert!(competitor.init(temp.0.clone()).is_err());
        drop(store);
        let reloaded = Hosts::default();
        reloaded.init(temp.0.clone()).unwrap();
        let item = reloaded.get(&host.id).unwrap();
        assert_eq!(item.name, "改名");
        assert!(!item.enabled);
        assert!(item.pairing.is_none());
        reloaded.remove(&host.id).unwrap();
        assert!(reloaded.list().unwrap().is_empty());
    }
    #[test]
    fn public_view_excludes_handle_and_duplicate_device_identity_is_rejected() {
        let temp = Temp::new();
        let store = Hosts::default();
        store.init(temp.0.clone()).unwrap();
        let keys = std::sync::Arc::new(VolatileKeyStore::default());
        let first = target();
        let pairing =
            Pairing::create(keys, "fixture", &first.expected_host_key, "Pocket", 100).unwrap();
        let reference = PairingReference {
            handle: pairing.local_handle().to_owned(),
            request_json: pairing.request_json().unwrap(),
            status: ReferenceStatus::Authorized,
        };
        let view = store
            .save(None, "One", first.clone(), Some(reference.clone()))
            .unwrap();
        let serialized = serde_json::to_string(&view).unwrap();
        assert!(!serialized.contains(&reference.handle));
        assert!(!serialized.contains("request_json"));
        let mut second = first;
        second.host = "example.com".into();
        assert!(store.save(None, "Two", second, Some(reference)).is_err());
        assert_eq!(store.list().unwrap().len(), 1);
    }
    #[test]
    fn malformed_or_oversized_store_is_not_silently_reset() {
        let temp = Temp::new();
        fs::create_dir_all(&temp.0).unwrap();
        fs::write(temp.0.join("hosts.json"), b"{").unwrap();
        let store = Hosts::default();
        assert!(store.init(temp.0.clone()).is_err());
        assert_eq!(fs::read(temp.0.join("hosts.json")).unwrap(), b"{");
    }
    #[test]
    fn pending_reference_survives_reopen_and_cancel_is_durable_without_secrets() {
        let temp = Temp::new();
        let hosts = Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        let keys = std::sync::Arc::new(VolatileKeyStore::default());
        let target = target();
        let view = hosts.save(None, "Pending", target.clone(), None).unwrap();
        let mut pairing = Pairing::create(
            keys.clone(),
            "fixture",
            &target.expected_host_key,
            "Pocket",
            100,
        )
        .unwrap();
        pairing.bind_target(&target.config()).unwrap();
        let reference = pairing.pending_reference(&target.config()).unwrap();
        hosts
            .attach_pending(&view.id, &target, reference.clone())
            .unwrap();
        assert!(
            hosts
                .attach_pending(&view.id, &target, reference.clone())
                .is_err()
        );
        let raw = fs::read_to_string(temp.0.join("hosts.json")).unwrap();
        assert!(
            !raw.contains("privateKeyPem") && !raw.contains("seed") && !raw.contains("password")
        );
        drop(hosts);
        let hosts = Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        let saved = hosts.get(&view.id).unwrap();
        let saved_ref = saved.pairing.unwrap();
        let restored =
            Pairing::restore_pending(keys.clone(), &saved_ref, &target.config(), true, 101)
                .unwrap();
        assert_eq!(
            restored.request_json().unwrap(),
            pairing.request_json().unwrap()
        );
        assert!(
            Pairing::restore_pending(
                std::sync::Arc::new(VolatileKeyStore::default()),
                &saved_ref,
                &target.config(),
                true,
                101
            )
            .is_err()
        );
        hosts
            .set_status(&saved_ref.handle, ReferenceStatus::Cancelled)
            .unwrap();
        drop(hosts);
        let hosts = Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        assert_eq!(
            hosts.get(&view.id).unwrap().pairing.unwrap().status,
            ReferenceStatus::Cancelled
        );
    }
}
