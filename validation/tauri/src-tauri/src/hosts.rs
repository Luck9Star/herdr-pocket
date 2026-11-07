//! App-private, bounded host records. Handles never cross the frontend bridge.
use crate::networks::NetworkProfile;
use herdr_readonly_transport::{
    RemoteConfig,
    config_transfer::{Archive, ArchiveV2, PortableHost, PortableHostV2, PortableNetwork, PortableTarget, Preferences, Provider},
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
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all="lowercase")]
pub enum KeyCleanupMode { Identity, Host }
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
    #[serde(default)]
    pub provider: Provider,
    #[serde(default)]
    pub retired: bool,
    #[serde(default, rename = "networkProfileId")]
    pub network_profile_id: Option<String>,
    #[serde(default, rename = "requiresNetworkBinding", skip_serializing_if = "is_false")]
    pub requires_network_binding: bool,
    #[serde(default, rename="keyDeletionPending", skip_serializing_if="is_false")]
    pub key_deletion_pending: bool,
    #[serde(default, rename="keyCleanupMode", skip_serializing_if="Option::is_none")]
    pub key_cleanup_mode: Option<KeyCleanupMode>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Disk {
    version: u8,
    hosts: Vec<Record>,
    #[serde(default, rename = "networkProfiles")]
    network_profiles: Vec<NetworkProfile>,
    #[serde(default = "default_preferences")]
    preferences: Preferences,
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
    pub provider: Provider,
    pub retired: bool,
    pub network_profile_id: Option<String>,
    pub requires_network_binding: bool,
    pub key_deletion_pending: bool,
    pub key_cleanup_mode: Option<KeyCleanupMode>,
}
impl Record {
    pub fn review_network_binding(&self, profile:Option<&NetworkProfile>) -> Result<(),String> {
        if self.requires_network_binding {
            let profile=profile.ok_or("network_binding_required")?;
            if !profile.enabled {return Err("network_profile_missing".into());}
            if profile.provider!=self.provider {return Err("network_provider_mismatch".into());}
        }
        Ok(())
    }
    fn validate(&self) -> Result<(), String> {
        if self.id.len() != 32
            || !self
                .id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || !valid_name(&self.name)
            || (self.retired && self.enabled)
            || (self.key_deletion_pending != self.key_cleanup_mode.is_some())
            || (self.key_deletion_pending && (self.enabled || self.pairing.is_none()))
            || (self.requires_network_binding && (!overlay_provider(self.provider) || self.network_profile_id.is_some()))
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
            provider: self.provider,
            retired: self.retired,
            network_profile_id: self.network_profile_id.clone(),
            requires_network_binding: self.requires_network_binding,
            key_deletion_pending: self.key_deletion_pending,
            key_cleanup_mode: self.key_cleanup_mode,
        })
    }
}
fn is_false(value: &bool) -> bool { !*value }
fn overlay_provider(provider: Provider) -> bool {
    matches!(provider, Provider::Tailscale | Provider::Easytier | Provider::Zerotier)
}
fn valid_name(name: &str) -> bool {
    !name.trim().is_empty() && name.len() <= 96 && !name.chars().any(char::is_control)
}
fn default_preferences() -> Preferences { Preferences { terminal_font_size:14 } }
struct Repository {
    dir: PathBuf,
    _lock: File,
    items: Vec<Record>,
    profiles: Vec<NetworkProfile>,
    preferences: Preferences,
    revision: String,
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
            if error.kind() == std::io::ErrorKind::WouldBlock {
                "host_storage_busy"
            } else {
                "host_storage_lock_failed"
            }
        })?;
        let path = dir.join("hosts.json");
        let (items, profiles, preferences) = match fs::symlink_metadata(&path) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (Vec::new(), Vec::new(), default_preferences()),
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
                (disk.hosts, disk.network_profiles, disk.preferences)
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
        Self::validate_profiles(&items, &profiles)?;
        if !(10..=28).contains(&preferences.terminal_font_size) {return Err("host_storage_corrupt".into());}
        Ok(Self {
            dir,
            _lock: lock,
            items,
            profiles,
            preferences,
            revision: random_public_id().map_err(str::to_string)?,
        })
    }
    fn validate_profiles(items: &[Record], profiles: &[NetworkProfile]) -> Result<(), String> {
        let mut ids = HashSet::new();
        if profiles.len() > 32 { return Err("network_profile_limit".into()); }
        for p in profiles { p.validate()?; if !ids.insert(&p.id) { return Err("invalid_network_profile".into()); } }
        if items.iter().any(|h| h.network_profile_id.as_ref().is_some_and(|id| !ids.contains(id))) {return Err("network_profile_missing".into());}
        Ok(())
    }
    fn validate_items(items: &[Record], profiles: &[NetworkProfile], preferences: &Preferences) -> Result<Vec<u8>, String> {
        if !(10..=28).contains(&preferences.terminal_font_size) {return Err("invalid_preferences".into());}
        Self::validate_profiles(items, profiles)?;
        if items.len() > MAX_HOSTS {
            return Err("host_limit".into());
        }
        let mut ids = HashSet::new();
        let mut handles = HashSet::new();
        for r in items {
            r.validate()?;
            if !ids.insert(&r.id)
                || r.pairing
                    .as_ref()
                    .is_some_and(|p| !handles.insert(&p.handle))
            {
                return Err("invalid_host_record".into());
            }
        }
        let bytes = serde_json::to_vec(&Disk {
            version: 1,
            hosts: items.to_vec(),
            network_profiles: profiles.to_vec(),
            preferences: preferences.clone(),
        })
        .map_err(|_| "host_storage_unavailable")?;
        if bytes.len() > 131072 {
            return Err("host_limit".into());
        }
        Ok(bytes)
    }
    fn commit(&mut self, items: Vec<Record>) -> Result<(), String> {
        self.commit_all(items, self.profiles.clone())
    }
    fn commit_all(&mut self, items: Vec<Record>, profiles: Vec<NetworkProfile>) -> Result<(), String> {
        self.commit_state(items, profiles, self.preferences.clone())
    }
    fn commit_state(&mut self, items: Vec<Record>, profiles: Vec<NetworkProfile>, preferences: Preferences) -> Result<(), String> {
        let next_revision = random_public_id().map_err(str::to_string)?;
        let bytes = Self::validate_items(&items, &profiles, &preferences)?;
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
        self.profiles = profiles;
        self.preferences = preferences;
        self.revision = next_revision;
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
        self.save_with_provider_hint(id, name, target, pairing, None)
    }
    pub fn save_with_provider_hint(
        &self,
        id: Option<&str>,
        name: &str,
        target: Target,
        pairing: Option<PairingReference>,
        provider_hint: Option<Provider>,
    ) -> Result<View, String> {
        if id.is_some() && provider_hint.is_some() {
            return Err("host_provider_hint_existing".into());
        }
        if provider_hint == Some(Provider::Unspecified) {
            return Err("invalid_provider_hint".into());
        }
        self.with(|r| {
            if !valid_name(name) {
                return Err("invalid_host_name".into());
            }
            target.validate()?;
            if r.items.iter().any(|h|h.key_deletion_pending && h.target==target) {return Err("host_key_cleanup_pending".into());}
            let mut list = r.items.clone();
            let host_id = if let Some(id) = id {
                let old = list.iter_mut().find(|x| x.id == id).ok_or("host_missing")?;
                if old.retired {
                    return Err("host_retired".into());
                }
                if old.target != target {
                    return Err("host_target_changed".into());
                }
                old.name = name.into();
                if pairing.is_some() {
                    if old.pairing.as_ref().is_some_and(|p| p.status == ReferenceStatus::Revoked) {
                        return Err("pairing_revoked".into());
                    }
                    old.pairing = pairing;
                }
                id.to_string()
            } else {
                if list.iter().any(|h| !h.retired && h.target == target) {
                    return Err("host_already_exists".into());
                }
                let id = random_public_id().map_err(str::to_string)?;
                list.push(Record {
                    id: id.clone(),
                    name: name.into(),
                    enabled: true,
                    target,
                    pairing,
                    provider: provider_hint.unwrap_or_default(),
                    retired: false,
                    network_profile_id: None,
                    requires_network_binding: provider_hint.is_some_and(overlay_provider),
                    key_deletion_pending: false,
                    key_cleanup_mode: None,
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
                if v && h.retired {
                    return Err("host_retired".into());
                }
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
            let index = r.items.iter()
                .position(|h| h.pairing.as_ref().is_some_and(|p| p.handle == handle))
                .ok_or("host_pairing_missing")?;
            let mut list = r.items.clone();
            let reference = list[index].pairing.as_mut().ok_or("host_pairing_missing")?;
            if reference.status == ReferenceStatus::Revoked && status != ReferenceStatus::Revoked {
                return Err("pairing_revoked".into());
            }
            reference.status = status;
            // A failed durable write must still stop local observers from
            // restoring the old authorized handle in this running process.
            if status == ReferenceStatus::Revoked {
                r.items[index].pairing = list[index].pairing.clone();
            }
            r.commit(list)
        })
    }
    pub fn remove(&self, id: &str) -> Result<Record, String> {
        self.with(|r| {
            let mut list = r.items.clone();
            let pos = list.iter().position(|h| h.id == id).ok_or("host_missing")?;
            if list[pos].key_deletion_pending {return Err("host_key_cleanup_pending".into());}
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
                    if h.key_deletion_pending {return Err("host_key_cleanup_pending".into());}
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
    pub fn find_handle(&self, handle:&str) -> Result<Option<Record>,String> {self.with(|r|Ok(r.items.iter().find(|h|h.pairing.as_ref().is_some_and(|p|p.handle==handle)).cloned()))}
    pub fn prepare_key_cleanup(&self, id:&str, expected_handle:&str, mode:KeyCleanupMode) -> Result<Record,String> {self.with(|r| {
        let mut list=r.items.clone();let host=list.iter_mut().find(|h|h.id==id).ok_or("host_missing")?;
        if !host.pairing.as_ref().is_some_and(|p|p.handle==expected_handle) {return Err("host_key_cleanup_changed".into());}
        if host.key_deletion_pending {if host.key_cleanup_mode!=Some(mode) {return Err("host_key_cleanup_intent_changed".into());}return Ok(host.clone());}
        host.enabled=false;host.key_deletion_pending=true;host.key_cleanup_mode=Some(mode);let ticket=host.clone();r.commit(list)?;Ok(ticket)
    })}
    pub fn finish_key_cleanup(&self, ticket:&Record) -> Result<(),String> {self.with(|r| {
        let mut list=r.items.clone();let index=list.iter().position(|h|h.id==ticket.id).ok_or("host_key_cleanup_changed")?;
        let current=&list[index];
        if !ticket.key_deletion_pending || !current.key_deletion_pending || serde_json::to_vec(current).map_err(|_|"host_storage_unavailable")?!=serde_json::to_vec(ticket).map_err(|_|"host_storage_unavailable")? {return Err("host_key_cleanup_changed".into());}
        match ticket.key_cleanup_mode.ok_or("host_key_cleanup_changed")? {
            KeyCleanupMode::Host=>{list.remove(index);},
            KeyCleanupMode::Identity=>{list[index].pairing=None;list[index].key_deletion_pending=false;list[index].key_cleanup_mode=None;list[index].enabled=false;}
        }
        r.commit(list)
    })}
    pub fn contains_handle(&self, handle: &str) -> Result<bool, String> {
        self.with(|r| {
            Ok(r.items
                .iter()
                .any(|x| x.pairing.as_ref().is_some_and(|p| p.handle == handle)))
        })
    }
}

#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub struct NetworkCatalog { pub revision: String, pub profiles: Vec<NetworkProfile>, pub bindings: Vec<NetworkBinding>, pub preferences: Preferences }
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub struct NetworkBinding { pub host_id: String, pub profile_id: String }
impl Hosts {
    pub fn networks(&self) -> Result<NetworkCatalog,String> { self.with(|r| Ok(NetworkCatalog { revision:r.revision.clone(), profiles:r.profiles.clone(), preferences:r.preferences.clone(), bindings:r.items.iter().filter_map(|h|h.network_profile_id.as_ref().map(|id|NetworkBinding{host_id:h.id.clone(),profile_id:id.clone()})).collect() })) }
    pub fn save_network(&self, mut profile: NetworkProfile, expected_catalog: &str, expected_revision: Option<u32>, affected: &[String]) -> Result<Vec<String>,String> { self.with(|r| {
        if r.revision != expected_catalog {return Err("network_changed".into());}
        let mut profiles=r.profiles.clone();
        let mut actual:Vec<String>=r.items.iter().filter(|h| h.network_profile_id.as_deref()==Some(&profile.id)).map(|h|h.id.clone()).collect(); actual.sort(); let mut supplied=affected.to_vec();supplied.sort(); if supplied!=actual {return Err("network_changed".into());}
        if let Some(old)=profiles.iter_mut().find(|p|p.id==profile.id) {
            if expected_revision!=Some(old.revision) || old.provider!=profile.provider {return Err("network_changed".into());}
            profile.revision=old.revision.checked_add(1).filter(|r|*r<=i32::MAX as u32).ok_or("network_revision_overflow")?;
            profile.validate()?; *old=profile;
        } else {
            if expected_revision.is_some() || !affected.is_empty() {return Err("network_changed".into());}
            profile.id=random_public_id().map_err(str::to_string)?; profile.revision=1;profile.validate()?;profiles.push(profile);
        }
        r.commit_all(r.items.clone(),profiles)?;Ok(actual)
    }) }
    pub fn save_preferences(&self, font:u8, expected_catalog:&str)->Result<(),String> {self.with(|r| {if r.revision!=expected_catalog {return Err("network_changed".into());}r.commit_state(r.items.clone(),r.profiles.clone(),Preferences{terminal_font_size:font})})}
    pub fn delete_network(&self, id:&str, expected_catalog:&str, expected_revision:u32) -> Result<(),String> { self.with(|r| {
        if r.revision!=expected_catalog {return Err("network_changed".into());}
        if r.items.iter().any(|h|h.network_profile_id.as_deref()==Some(id)) {return Err("network_in_use".into());}
        let mut profiles=r.profiles.clone();let pos=profiles.iter().position(|p|p.id==id && p.revision==expected_revision).ok_or("network_changed")?;profiles.remove(pos);r.commit_all(r.items.clone(),profiles)
    }) }
    pub fn bind_network(&self, host_id:&str, profile_id:Option<String>, expected_catalog:&str) -> Result<(),String> { self.with(|r| {
        if r.revision!=expected_catalog {return Err("network_changed".into());}
        if let Some(id)=&profile_id {if !r.profiles.iter().any(|p|&p.id==id && p.enabled) {return Err("network_profile_missing".into());}}
        let mut list=r.items.clone();
        let h=list.iter_mut().find(|h|h.id==host_id && !h.retired).ok_or("host_missing")?;
        let profile=profile_id.as_ref().and_then(|id|r.profiles.iter().find(|p|&p.id==id));
        h.review_network_binding(profile)?;
        h.requires_network_binding=false;
        h.network_profile_id=profile_id;
        r.commit(list)
    }) }
    pub fn route(&self, host:&Record) -> Result<Option<NetworkProfile>,String> { self.with(|r| {
        let current=r.items.iter().find(|h|h.id==host.id).ok_or("host_missing")?;
        if current.key_deletion_pending {return Err("host_key_cleanup_pending".into());}
        if current.target!=host.target || current.network_profile_id!=host.network_profile_id
            || current.provider!=host.provider || current.requires_network_binding!=host.requires_network_binding {
            return Err("host_selection_changed".into());
        }
        r.route(current)
    }) }
    // Device authentication must identify the record that owns its local key.
    // An omitted/wrong id cannot select a separate system-network path.
    pub fn review_device_host(&self, host_id:Option<&str>, handle:&str, target:&Target) -> Result<Record,String> {self.with(|r| {
        let host=r.items.iter().find(|h|h.pairing.as_ref().is_some_and(|p|p.handle==handle)).ok_or("host_selection_changed")?;
        if host_id!=Some(host.id.as_str()) || !host.enabled || host.retired || &host.target!=target {
            return Err("host_selection_changed".into());
        }
        r.route(host)?;
        Ok(host.clone())
    }) }
}
impl Repository {
    fn route(&self, host:&Record) -> Result<Option<NetworkProfile>,String> {
        if host.key_deletion_pending {return Err("host_key_cleanup_pending".into());}
        if host.requires_network_binding {return Err("network_binding_required".into());}
        let Some(id)=&host.network_profile_id else {return Ok(None)};
        let p=self.profiles.iter().find(|p|&p.id==id).ok_or("network_profile_missing")?;
        if !p.enabled {return Err("network_profile_disabled".into());}
        Ok(Some(p.clone()))
    }
}

impl From<&Target> for PortableTarget {
    fn from(t: &Target) -> Self {
        Self {
            host: t.host.clone(),
            port: t.port,
            username: t.username.clone(),
            expected_host_key: t.expected_host_key.clone(),
            socket_path: t.socket_path.clone(),
            herdr_path: t.herdr_path.clone(),
            session: t.session.clone(),
        }
    }
}
impl From<&PortableTarget> for Target {
    fn from(t: &PortableTarget) -> Self {
        Self {
            host: t.host.clone(),
            port: t.port,
            username: t.username.clone(),
            expected_host_key: t.expected_host_key.clone(),
            socket_path: t.socket_path.clone(),
            herdr_path: t.herdr_path.clone(),
            session: t.session.clone(),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportConflict {
    pub id: String,
    pub name: String,
    pub target: Target,
    pub paired: bool,
    pub retired: bool,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportEntry {
    pub index: usize,
    pub host: PortableHost,
    pub conflicts: Vec<ImportConflict>,
    pub same_label_indices: Vec<usize>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportPlan {
    pub revision: String,
    pub entries: Vec<ImportEntry>,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ImportChoice {
    pub index: usize,
    pub action: ImportAction,
    pub replace_ids: Vec<String>,
}
#[derive(Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ImportAction {
    Add,
    Keep,
    Replace,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportResult {
    pub added: Vec<View>,
    pub retired: Vec<View>,
    pub removed_ids: Vec<String>,
}

fn transfer_revision(
    items: &[Record],
    archive: &Archive,
    revision: &str,
) -> Result<String, String> {
    let raw =
        serde_json::to_vec(&(items, archive, revision)).map_err(|_| "transfer_invalid_schema")?;
    Ok(herdr_readonly_transport::config_transfer::revision_digest(
        &raw,
    ))
}
fn conflict_ids(items: &[Record], host: &PortableHost) -> Vec<String> {
    let target = Target::from(&host.target);
    items
        .iter()
        .filter(|r| !r.retired && (r.name == host.label || r.target == target))
        .map(|r| r.id.clone())
        .collect()
}
impl Hosts {
    pub fn export_portable(&self, ids: &[String]) -> Result<Archive, String> {
        self.with(|r| {
            if ids.is_empty()
                || ids.len() > 16
                || ids.iter().collect::<HashSet<_>>().len() != ids.len()
            {
                return Err("transfer_invalid_selection".into());
            }
            let mut hosts = Vec::new();
            for id in ids {
                let h = r
                    .items
                    .iter()
                    .find(|h| &h.id == id && !h.retired)
                    .ok_or("host_missing")?;
                if h.key_deletion_pending {return Err("host_key_cleanup_pending".into());}
                if h.network_profile_id.is_some() || h.requires_network_binding { return Err("transfer_network_unavailable".into()); }
                hosts.push(PortableHost {
                    label: h.name.clone(),
                    provider: h.provider,
                    target: PortableTarget::from(&h.target),
                });
            }
            let archive = Archive { version: 1, hosts };
            archive.validate().map_err(str::to_string)?;
            Ok(archive)
        })
    }
    pub fn preview_import(&self, archive: &Archive) -> Result<ImportPlan, String> {
        archive.validate().map_err(str::to_string)?;
        self.with(|r| {
            let entries = archive
                .hosts
                .iter()
                .enumerate()
                .map(|(index, host)| {
                    let ids = conflict_ids(&r.items, host);
                    let conflicts = r
                        .items
                        .iter()
                        .filter(|h| ids.contains(&h.id))
                        .map(|h| ImportConflict {
                            id: h.id.clone(),
                            name: h.name.clone(),
                            target: h.target.clone(),
                            paired: h.pairing.is_some(),
                            retired: h.retired,
                        })
                        .collect();
                    let same_label_indices = archive
                        .hosts
                        .iter()
                        .enumerate()
                        .filter(|(i, h)| *i != index && h.label == host.label)
                        .map(|(i, _)| i)
                        .collect();
                    ImportEntry {
                        index,
                        host: host.clone(),
                        conflicts,
                        same_label_indices,
                    }
                })
                .collect();
            Ok(ImportPlan {
                revision: transfer_revision(&r.items, archive, &r.revision)?,
                entries,
            })
        })
    }
    #[cfg(test)]
    pub fn apply_import(
        &self,
        archive: &Archive,
        revision: &str,
        choices: &[ImportChoice],
    ) -> Result<ImportResult, String> {
        self.apply_import_with(archive, revision, choices, |_| Ok(()))
    }
    pub fn apply_import_with(
        &self,
        archive: &Archive,
        revision: &str,
        choices: &[ImportChoice],
        before_commit: impl FnOnce(&[Record]) -> Result<(), String>,
    ) -> Result<ImportResult, String> {
        archive.validate().map_err(str::to_string)?;
        self.with(|r| {
            if transfer_revision(&r.items, archive, &r.revision)? != revision {
                return Err("transfer_stale_plan".into());
            }
            if choices.len() != archive.hosts.len() {
                return Err("transfer_invalid_choice".into());
            }
            let mut list = r.items.clone();
            let mut added_ids = Vec::new();
            let mut retired_ids = Vec::new();
            let mut removed_ids = Vec::new();
            let mut replaced = Vec::new();
            let mut seen = HashSet::new();
            for choice in choices {
                if choice.index >= archive.hosts.len() || !seen.insert(choice.index) {
                    return Err("transfer_invalid_choice".into());
                }
                let host = &archive.hosts[choice.index];
                let mut expected = conflict_ids(&r.items, host);
                expected.sort();
                let mut selected = choice.replace_ids.clone();
                selected.sort();
                if choice.action != ImportAction::Replace && !selected.is_empty() {
                    return Err("transfer_invalid_choice".into());
                }
                if choice.action == ImportAction::Keep {
                    continue;
                }
                let incoming_target=Target::from(&host.target);
                if r.items.iter().any(|h|h.key_deletion_pending && (h.target==incoming_target || selected.contains(&h.id))) {return Err("host_key_cleanup_pending".into());}
                if choice.action == ImportAction::Replace {
                    if expected.is_empty() || selected != expected {
                        return Err("transfer_invalid_choice".into());
                    }
                    for id in selected {
                        let pos = list
                            .iter()
                            .position(|h| h.id == id && !h.retired)
                            .ok_or("transfer_conflict_changed")?;
                        replaced.push(list[pos].clone());
                        if list[pos].pairing.is_some() {
                            list[pos].retired = true;
                            list[pos].enabled = false;
                            retired_ids.push(id);
                        } else {
                            list.remove(pos);
                            removed_ids.push(id);
                        }
                    }
                }
                let target = Target::from(&host.target);
                if list.iter().any(|h| !h.retired && h.target == target) {
                    return Err("transfer_target_conflict".into());
                }
                let id = random_public_id().map_err(str::to_string)?;
                if list.iter().any(|h| h.id == id) {
                    return Err("transfer_id_conflict".into());
                }
                list.push(Record {
                    id: id.clone(),
                    name: host.label.clone(),
                    enabled: true,
                    target,
                    pairing: None,
                    provider: host.provider,
                    retired: false,
                    network_profile_id: None,
                    requires_network_binding: false,
                    key_deletion_pending: false,
                    key_cleanup_mode: None,
                });
                added_ids.push(id);
            }
            let added = added_ids
                .iter()
                .map(|id| list.iter().find(|h| &h.id == id).unwrap().view())
                .collect::<Result<Vec<_>, _>>()?;
            let retired = retired_ids
                .iter()
                .map(|id| list.iter().find(|h| &h.id == id).unwrap().view())
                .collect::<Result<Vec<_>, _>>()?;
            Repository::validate_items(&list, &r.profiles, &r.preferences)?;
            before_commit(&replaced)?;
            r.commit(list)?;
            Ok(ImportResult {
                added,
                retired,
                removed_ids,
            })
        })
    }
}


#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub struct ImportPlanV2 { pub revision:String, pub entries:Vec<ImportEntryV2>, pub networks:Vec<ImportNetwork>, pub preferences:Option<Preferences> }
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub struct ImportEntryV2 { pub index:usize, pub host:PortableHostV2, pub conflicts:Vec<ImportConflict>, pub same_label_indices:Vec<usize> }
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub struct ImportNetwork { pub network:PortableNetwork, pub same_label:Vec<NetworkProfile> }
fn conflict_ids_v2(items:&[Record], h:&PortableHostV2)->Vec<String> {let target=Target::from(&h.target);items.iter().filter(|r|!r.retired && (r.name==h.label || r.target==target)).map(|r|r.id.clone()).collect()}
fn transfer_revision_v2(a:&ArchiveV2,revision:&str)->Result<String,String> {let raw=serde_json::to_vec(&(a,revision)).map_err(|_|"transfer_invalid_schema")?;Ok(herdr_readonly_transport::config_transfer::revision_digest(&raw))}
impl Hosts {
 pub fn export_v2(&self,ids:&[String],network_ids:&[String],include_preferences:bool)->Result<ArchiveV2,String>{self.with(|r|{
    if ids.len()>16 || network_ids.len()>16 || ids.iter().collect::<HashSet<_>>().len()!=ids.len() || network_ids.iter().collect::<HashSet<_>>().len()!=network_ids.len(){return Err("transfer_invalid_selection".into());}
    let chosen:Vec<&Record>=ids.iter().map(|id|r.items.iter().find(|h|&h.id==id && !h.retired).ok_or("host_missing")).collect::<Result<_,_>>()?;
    if chosen.iter().any(|h|h.key_deletion_pending) {return Err("host_key_cleanup_pending".into());}
    let mut included=network_ids.to_vec();for h in &chosen {if let Some(id)=&h.network_profile_id {if !included.contains(id){included.push(id.clone());}}}
    if included.len()>16 {return Err("transfer_invalid_selection".into());}
    let networks:Vec<PortableNetwork>=included.iter().enumerate().map(|(i,id)| {let p=r.profiles.iter().find(|p|&p.id==id).ok_or("network_profile_missing")?;Ok(PortableNetwork{key:format!("n{i}"),label:p.label.clone(),provider:p.provider,settings:p.settings.clone()})}).collect::<Result<_,String>>()?;
    let hosts=chosen.iter().map(|h|{let profile=h.network_profile_id.as_ref().and_then(|id|included.iter().position(|p|p==id));PortableHostV2{label:h.name.clone(),provider:profile.map(|i|networks[i].provider).unwrap_or(h.provider),target:PortableTarget::from(&h.target),network_key:profile.map(|i|networks[i].key.clone()),requires_network_binding:h.requires_network_binding}}).collect();
    let a=ArchiveV2{version:2,hosts,networks,preferences:include_preferences.then(||r.preferences.clone())};a.validate().map_err(str::to_string)?;Ok(a)
 })}
 pub fn preview_v2(&self,a:&ArchiveV2)->Result<ImportPlanV2,String>{a.validate().map_err(str::to_string)?;self.with(|r|{
    let entries=a.hosts.iter().enumerate().map(|(index,h)|{let ids=conflict_ids_v2(&r.items,h);ImportEntryV2{index,host:h.clone(),conflicts:r.items.iter().filter(|x|ids.contains(&x.id)).map(|x|ImportConflict{id:x.id.clone(),name:x.name.clone(),target:x.target.clone(),paired:x.pairing.is_some(),retired:x.retired}).collect(),same_label_indices:a.hosts.iter().enumerate().filter(|(i,x)|*i!=index && x.label==h.label).map(|(i,_)|i).collect()}}).collect();
    let networks=a.networks.iter().map(|n|ImportNetwork{network:n.clone(),same_label:r.profiles.iter().filter(|p|p.label==n.label).cloned().collect()}).collect();
    Ok(ImportPlanV2{revision:transfer_revision_v2(a,&r.revision)?,entries,networks,preferences:a.preferences.clone()})
 })}
 pub fn apply_v2(&self,a:&ArchiveV2,revision:&str,choices:&[ImportChoice],selected_networks:&[String],apply_preferences:bool,before_commit:impl FnOnce(&[Record])->Result<(),String>)->Result<ImportResult,String>{
  a.validate().map_err(str::to_string)?;self.with(|r|{
    if transfer_revision_v2(a,&r.revision)?!=revision{return Err("transfer_stale_plan".into());}
    if choices.len()!=a.hosts.len() || selected_networks.iter().collect::<HashSet<_>>().len()!=selected_networks.len() || selected_networks.iter().any(|key|!a.networks.iter().any(|n|&n.key==key)) || (apply_preferences && a.preferences.is_none()) {return Err("transfer_invalid_choice".into());}
    let mut wanted:HashSet<String>=selected_networks.iter().cloned().collect();
    let mut seen=HashSet::new();for choice in choices {if choice.index>=a.hosts.len() || !seen.insert(choice.index){return Err("transfer_invalid_choice".into());}if choice.action!=ImportAction::Keep {if let Some(k)=&a.hosts[choice.index].network_key {wanted.insert(k.clone());}}}
    let mut profiles=r.profiles.clone();let mut ids=std::collections::HashMap::new();
    for network in a.networks.iter().filter(|n|wanted.contains(&n.key)) {let id=random_public_id().map_err(str::to_string)?;let p=NetworkProfile{id:id.clone(),label:network.label.clone(),provider:network.provider,enabled:false,revision:1,settings:network.settings.clone()};p.validate()?;profiles.push(p);ids.insert(network.key.clone(),id);}
    let mut list=r.items.clone();let(mut added_ids,mut retired_ids,mut removed_ids,mut replaced)=(Vec::new(),Vec::new(),Vec::new(),Vec::new());
    for choice in choices {let h=&a.hosts[choice.index];let mut expected=conflict_ids_v2(&r.items,h);expected.sort();let mut selected=choice.replace_ids.clone();selected.sort();if choice.action!=ImportAction::Replace && !selected.is_empty(){return Err("transfer_invalid_choice".into());}if choice.action==ImportAction::Keep {continue;}
        let incoming_target=Target::from(&h.target);if r.items.iter().any(|x|x.key_deletion_pending && (x.target==incoming_target || selected.contains(&x.id))) {return Err("host_key_cleanup_pending".into());}
        if choice.action==ImportAction::Replace {if expected.is_empty() || selected!=expected {return Err("transfer_invalid_choice".into());}for id in selected {let pos=list.iter().position(|h|h.id==id && !h.retired).ok_or("transfer_conflict_changed")?;replaced.push(list[pos].clone());if list[pos].pairing.is_some(){list[pos].retired=true;list[pos].enabled=false;retired_ids.push(id);}else{list.remove(pos);removed_ids.push(id);}}}
        let target=Target::from(&h.target);if list.iter().any(|x|!x.retired && x.target==target){return Err("transfer_target_conflict".into());}let id=random_public_id().map_err(str::to_string)?;list.push(Record{id:id.clone(),name:h.label.clone(),enabled:true,target,pairing:None,provider:h.provider,retired:false,key_deletion_pending:false,key_cleanup_mode:None,requires_network_binding:h.requires_network_binding,network_profile_id:h.network_key.as_ref().map(|key|ids.get(key).cloned().ok_or("transfer_invalid_schema")).transpose()?});added_ids.push(id);
    }
    let added=added_ids.iter().map(|id|list.iter().find(|h|&h.id==id).unwrap().view()).collect::<Result<Vec<_>,_>>()?;let retired=retired_ids.iter().map(|id|list.iter().find(|h|&h.id==id).unwrap().view()).collect::<Result<Vec<_>,_>>()?;
    let prefs=if apply_preferences {a.preferences.clone().ok_or("transfer_invalid_choice")?}else{r.preferences.clone()};Repository::validate_items(&list,&profiles,&prefs)?;before_commit(&replaced)?;r.commit_state(list,profiles,prefs)?;Ok(ImportResult{added,retired,removed_ids})
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
    fn add_network(hosts: &Hosts, provider: Provider, enabled: bool) -> NetworkProfile {
        use crate::networks::Settings;
        let settings=match provider {
            Provider::Tailscale=>Settings::Tailscale{control_url:String::new(),hostname:String::new()},
            Provider::Easytier=>Settings::Easytier{network_name:"team".into(),peers:vec!["tcp://example.test:1234".into()]},
            Provider::Zerotier=>Settings::Zerotier{network_id:"0123456789abcdef".into()},
            _=>panic!("overlay fixture required"),
        };
        let cat=hosts.networks().unwrap();
        hosts.save_network(NetworkProfile{id:"0".repeat(32),label:"fixture".into(),provider,enabled,revision:1,settings},&cat.revision,None,&[]).unwrap();
        hosts.networks().unwrap().profiles.last().unwrap().clone()
    }
    #[test]
    fn scanned_overlay_requires_binding_after_save_rename_and_reopen() {
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let mut ids=Vec::new();
        for provider in [Provider::Tailscale,Provider::Easytier,Provider::Zerotier] {
            let t=target();let view=hosts.save_with_provider_hint(None,"scan",t.clone(),None,Some(provider)).unwrap();
            assert_eq!(view.provider,provider);assert!(view.requires_network_binding);assert!(view.network_profile_id.is_none());
            let record=hosts.get(&view.id).unwrap();
            assert!(matches!(hosts.route(&record),Err(e) if e=="network_binding_required"));
            let before=fs::read(temp.0.join("hosts.json")).unwrap();
            assert!(matches!(hosts.save_with_provider_hint(Some(&view.id),"overwrite",t.clone(),None,Some(Provider::Direct)),Err(e) if e=="host_provider_hint_existing"));
            assert!(matches!(hosts.save_with_provider_hint(None,"duplicate",t.clone(),None,Some(Provider::Direct)),Err(e) if e=="host_already_exists"));
            assert_eq!(fs::read(temp.0.join("hosts.json")).unwrap(),before);
            hosts.save(Some(&view.id),"renamed",t,None).unwrap();
            assert!(hosts.get(&view.id).unwrap().requires_network_binding);
            let json=serde_json::to_value(hosts.get(&view.id).unwrap().view().unwrap()).unwrap();
            assert_eq!(json["requiresNetworkBinding"],true);
            ids.push(view.id);
        }
        assert!(hosts.save_with_provider_hint(None,"invalid hint",target(),None,Some(Provider::Unspecified)).is_err());
        let manual=hosts.save(None,"manual",target(),None).unwrap();
        let direct=hosts.save_with_provider_hint(None,"scan direct",target(),None,Some(Provider::Direct)).unwrap();
        assert!(!manual.requires_network_binding);assert!(!direct.requires_network_binding);
        assert!(hosts.route(&hosts.get(&manual.id).unwrap()).unwrap().is_none());
        drop(hosts);let reopened=Hosts::default();reopened.init(temp.0.clone()).unwrap();
        for id in ids {assert!(reopened.get(&id).unwrap().requires_network_binding);assert!(reopened.route(&reopened.get(&id).unwrap()).is_err());}
        // Missing optional fields in old disk records still mean the legacy rule.
        assert!(!reopened.get(&manual.id).unwrap().requires_network_binding);
        let disk:serde_json::Value=serde_json::from_slice(&fs::read(temp.0.join("hosts.json")).unwrap()).unwrap();
        assert!(disk["hosts"].as_array().unwrap().iter().find(|h|h["id"]==manual.id).unwrap().get("requiresNetworkBinding").is_none());
    }
    #[test]
    fn first_network_binding_checks_provider_enablement_revision_and_atomic_commit() {
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let h=hosts.save_with_provider_hint(None,"scan",target(),None,Some(Provider::Tailscale)).unwrap();
        let stale=hosts.get(&h.id).unwrap();
        let wrong=add_network(&hosts,Provider::Easytier,true);
        let disabled=add_network(&hosts,Provider::Tailscale,false);
        let matching=add_network(&hosts,Provider::Tailscale,true);
        let cat=hosts.networks().unwrap();let before=fs::read(temp.0.join("hosts.json")).unwrap();
        assert!(matches!(hosts.bind_network(&h.id,None,&cat.revision),Err(e) if e=="network_binding_required"));
        assert!(matches!(hosts.bind_network(&h.id,Some(wrong.id.clone()),&cat.revision),Err(e) if e=="network_provider_mismatch"));
        assert!(matches!(hosts.bind_network(&h.id,Some(disabled.id.clone()),&cat.revision),Err(e) if e=="network_profile_missing"));
        assert!(matches!(hosts.bind_network(&h.id,Some(matching.id.clone()),"stale"),Err(e) if e=="network_changed"));
        assert_eq!(fs::read(temp.0.join("hosts.json")).unwrap(),before);
        assert_eq!(hosts.networks().unwrap().revision,cat.revision);
        // Force the atomic rename to fail: neither the flag nor the binding may advance in memory.
        fs::rename(temp.0.join("hosts.json"),temp.0.join("saved.json")).unwrap();
        fs::create_dir(temp.0.join("hosts.json")).unwrap();
        assert!(matches!(hosts.bind_network(&h.id,Some(matching.id.clone()),&cat.revision),Err(e) if e=="host_storage_unavailable"));
        assert!(hosts.get(&h.id).unwrap().requires_network_binding);
        assert!(hosts.get(&h.id).unwrap().network_profile_id.is_none());
        fs::remove_dir(temp.0.join("hosts.json")).unwrap();
        fs::rename(temp.0.join("saved.json"),temp.0.join("hosts.json")).unwrap();
        hosts.bind_network(&h.id,Some(matching.id.clone()),&cat.revision).unwrap();
        let bound=hosts.get(&h.id).unwrap();assert!(!bound.requires_network_binding);
        assert_eq!(hosts.route(&bound).unwrap().unwrap().id,matching.id);
        assert!(matches!(hosts.route(&stale),Err(e) if e=="host_selection_changed"));
        drop(hosts);let reopened=Hosts::default();reopened.init(temp.0.clone()).unwrap();
        let record=reopened.get(&h.id).unwrap();assert!(!record.requires_network_binding);assert_eq!(record.network_profile_id,Some(matching.id));
        // After explicit first binding, the existing rebind/clear workflow stays available.
        let cat=reopened.networks().unwrap();reopened.bind_network(&h.id,Some(wrong.id.clone()),&cat.revision).unwrap();
        assert_eq!(reopened.route(&reopened.get(&h.id).unwrap()).unwrap().unwrap().id,wrong.id);
        let cat=reopened.networks().unwrap();reopened.bind_network(&h.id,None,&cat.revision).unwrap();
        assert!(reopened.route(&reopened.get(&h.id).unwrap()).unwrap().is_none());
    }
    #[test]
    fn device_auth_requires_owning_host_id_and_obeys_pending_route() {
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let t=target();let h=hosts.save_with_provider_hint(None,"scan",t.clone(),None,Some(Provider::Tailscale)).unwrap();
        let other=hosts.save(None,"manual",target(),None).unwrap();
        let keys=std::sync::Arc::new(VolatileKeyStore::default());
        let p=crate::create_offline_pair(keys,&t.config(),"Pocket",100).unwrap();
        let reference=p.pending_reference(&t.config()).unwrap();
        hosts.attach_pending(&h.id,&t,reference.clone()).unwrap();
        for id in [None,Some(other.id.as_str())] {
            assert!(matches!(hosts.review_device_host(id,&reference.handle,&t),Err(e) if e=="host_selection_changed"));
        }
        assert!(matches!(hosts.review_device_host(Some(&h.id),&reference.handle,&t),Err(e) if e=="network_binding_required"));
        assert!(hosts.review_device_host(Some(&h.id),"unknown-handle",&t).is_err());
        let network=add_network(&hosts,Provider::Tailscale,true);let cat=hosts.networks().unwrap();hosts.bind_network(&h.id,Some(network.id),&cat.revision).unwrap();
        assert_eq!(hosts.review_device_host(Some(&h.id),&reference.handle,&t).unwrap().id,h.id);
        let mut changed=t;changed.port=23;assert!(hosts.review_device_host(Some(&h.id),&reference.handle,&changed).is_err());
        // Independent manual records retain their original system route.
        assert!(hosts.route(&hosts.get(&other.id).unwrap()).unwrap().is_none());
    }
    #[test]
    fn pending_scan_v2_transfer_preserves_restriction_and_v1_export_rejects_loss() {
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let h=hosts.save_with_provider_hint(None,"scan",target(),None,Some(Provider::Zerotier)).unwrap();
        assert!(matches!(hosts.export_portable(&[h.id.clone()]),Err(e) if e=="transfer_network_unavailable"));
        let archive=hosts.export_v2(&[h.id.clone()],&[],false).unwrap();
        assert!(archive.hosts[0].requires_network_binding);assert!(archive.hosts[0].network_key.is_none());assert!(archive.networks.is_empty());
        let bytes=serde_json::to_vec(&archive).unwrap();
        let parsed=herdr_readonly_transport::config_transfer::PortableArchive::parse(&bytes).unwrap().into_v2();
        let plan=hosts.preview_v2(&parsed).unwrap();
        let before=fs::read(temp.0.join("hosts.json")).unwrap();
        let choice=ImportChoice{index:0,action:ImportAction::Replace,replace_ids:vec![h.id.clone()]};
        assert!(hosts.apply_v2(&parsed,&plan.revision,&[choice],&[],false,|_|Err("simulated_stop_failure".into())).is_err());
        assert_eq!(fs::read(temp.0.join("hosts.json")).unwrap(),before);
        let choice=ImportChoice{index:0,action:ImportAction::Replace,replace_ids:vec![h.id.clone()]};
        let applied=hosts.apply_v2(&parsed,&plan.revision,&[choice],&[],false,|_|Ok(())).unwrap();
        let imported=&applied.added[0];assert!(imported.requires_network_binding);assert!(imported.network_profile_id.is_none());
        assert!(hosts.route(&hosts.get(&imported.id).unwrap()).is_err());
        assert!(matches!(hosts.get(&h.id),Err(e) if e=="host_missing"));
        let next=hosts.export_v2(&[imported.id.clone()],&[],false).unwrap();assert_eq!(next.hosts[0],archive.hosts[0]);
        drop(hosts);let reopened=Hosts::default();reopened.init(temp.0.clone()).unwrap();assert!(reopened.get(&imported.id).unwrap().requires_network_binding);
    }
    #[test]
    fn corrupt_pending_flag_with_bound_network_or_direct_provider_is_rejected() {
        for provider in [Provider::Direct,Provider::Tailscale] {
            let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
            let h=hosts.save(None,"legacy",target(),None).unwrap();
            if provider==Provider::Tailscale {let profile=add_network(&hosts,provider,true);let cat=hosts.networks().unwrap();hosts.bind_network(&h.id,Some(profile.id),&cat.revision).unwrap();}
            drop(hosts);
            let path=temp.0.join("hosts.json");let mut disk:serde_json::Value=serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            disk["hosts"][0]["provider"]=serde_json::to_value(provider).unwrap();disk["hosts"][0]["requiresNetworkBinding"]=true.into();
            fs::write(&path,serde_json::to_vec(&disk).unwrap()).unwrap();
            assert!(Hosts::default().init(temp.0.clone()).is_err());
        }
    }
    #[test]
    fn network_catalog_persists_and_binding_never_exports_as_direct() {
        use crate::networks::{Provider, Settings};
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let h=hosts.save(None,"fixture",target(),None).unwrap();let initial=hosts.networks().unwrap();
        let p=NetworkProfile{id:"0".repeat(32),label:"network".into(),provider:Provider::Tailscale,enabled:true,revision:1,settings:Settings::Tailscale{control_url:String::new(),hostname:String::new()}};
        hosts.save_network(p,&initial.revision,None,&[]).unwrap();let catalog=hosts.networks().unwrap();let profile=catalog.profiles[0].clone();
        assert!(hosts.bind_network(&h.id,Some(profile.id.clone()),&initial.revision).is_err());
        hosts.bind_network(&h.id,Some(profile.id.clone()),&catalog.revision).unwrap();
        assert!(matches!(hosts.export_portable(&[h.id.clone()]),Err(e) if e=="transfer_network_unavailable"));
        let catalog=hosts.networks().unwrap();assert!(matches!(hosts.delete_network(&profile.id,&catalog.revision,1),Err(e) if e=="network_in_use"));
        let mut edited=profile.clone();edited.enabled=false;hosts.save_network(edited,&catalog.revision,Some(1),&[h.id.clone()]).unwrap();
        assert!(matches!(hosts.route(&hosts.get(&h.id).unwrap()),Err(e) if e=="network_profile_disabled"));
        drop(hosts);let reopened=Hosts::default();reopened.init(temp.0.clone()).unwrap();let catalog=reopened.networks().unwrap();assert_eq!(catalog.profiles[0].revision,2);assert_eq!(reopened.get(&h.id).unwrap().network_profile_id,Some(profile.id));
    }
    #[test]
    fn v2_import_is_atomic_and_keep_does_not_create_dependencies() {
        use crate::networks::Settings;
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let h=hosts.save(None,"original",target(),None).unwrap();let initial=hosts.networks().unwrap();
        let p=NetworkProfile{id:"0".repeat(32),label:"team".into(),provider:Provider::Tailscale,enabled:true,revision:1,settings:Settings::Tailscale{control_url:String::new(),hostname:String::new()}};
        hosts.save_network(p,&initial.revision,None,&[]).unwrap();let cat=hosts.networks().unwrap();let original_profile=cat.profiles[0].id.clone();hosts.bind_network(&h.id,Some(original_profile.clone()),&cat.revision).unwrap();
        let archive=hosts.export_v2(&[h.id.clone()],&[],true).unwrap();assert_eq!(archive.networks.len(),1);assert_eq!(archive.hosts[0].network_key.as_deref(),Some("n0"));
        let plan=hosts.preview_v2(&archive).unwrap();let keep=ImportChoice{index:0,action:ImportAction::Keep,replace_ids:vec![]};hosts.apply_v2(&archive,&plan.revision,&[keep],&[],false,|_|Ok(())).unwrap();
        assert_eq!(hosts.networks().unwrap().profiles.len(),1);assert_eq!(hosts.get(&h.id).unwrap().network_profile_id,Some(original_profile));
        let plan=hosts.preview_v2(&archive).unwrap();let replace=ImportChoice{index:0,action:ImportAction::Replace,replace_ids:vec![h.id.clone()]};
        let mut stopped=false;let bad=hosts.apply_v2(&archive,"stale",&[replace],&[],true,|_|{stopped=true;Ok(())});assert!(bad.is_err());assert!(!stopped);assert_eq!(hosts.networks().unwrap().profiles.len(),1);
        let replace=ImportChoice{index:0,action:ImportAction::Replace,replace_ids:vec![h.id.clone()]};let result=hosts.apply_v2(&archive,&plan.revision,&[replace],&[],true,|_|Ok(())).unwrap();
        let cat=hosts.networks().unwrap();assert_eq!(cat.profiles.len(),2);let new_id=result.added[0].network_profile_id.clone().unwrap();let new=cat.profiles.iter().find(|p|p.id==new_id).unwrap();assert!(!new.enabled);assert_eq!(new.revision,1);assert_eq!(cat.preferences.terminal_font_size,14);
        drop(hosts);let reload=Hosts::default();reload.init(temp.0.clone()).unwrap();assert_eq!(reload.networks().unwrap().profiles.len(),2);
    }
    #[test]
    fn network_limit_is_checked_before_stopping_active_host() {
        use crate::networks::Settings;
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let h=hosts.save(None,"target",target(),None).unwrap();
        for _ in 0..32 {let cat=hosts.networks().unwrap();let p=NetworkProfile{id:"0".repeat(32),label:"same".into(),provider:Provider::Tailscale,enabled:true,revision:1,settings:Settings::Tailscale{control_url:String::new(),hostname:String::new()}};hosts.save_network(p,&cat.revision,None,&[]).unwrap();}
        let cat=hosts.networks().unwrap();hosts.bind_network(&h.id,Some(cat.profiles[0].id.clone()),&cat.revision).unwrap();let archive=hosts.export_v2(&[h.id.clone()],&[],false).unwrap();let plan=hosts.preview_v2(&archive).unwrap();
        let replace=ImportChoice{index:0,action:ImportAction::Replace,replace_ids:vec![h.id.clone()]};let mut stopped=false;
        assert!(hosts.apply_v2(&archive,&plan.revision,&[replace],&[],false,|_|{stopped=true;Ok(())}).is_err());assert!(!stopped);assert_eq!(hosts.networks().unwrap().profiles.len(),32);assert_eq!(hosts.get(&h.id).unwrap().name,"target");
    }
    #[test]
    fn preferences_only_and_network_only_roundtrip() {
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();let cat=hosts.networks().unwrap();hosts.save_preferences(22,&cat.revision).unwrap();
        let archive=hosts.export_v2(&[],&[],true).unwrap();let cat=hosts.networks().unwrap();hosts.save_preferences(14,&cat.revision).unwrap();let plan=hosts.preview_v2(&archive).unwrap();hosts.apply_v2(&archive,&plan.revision,&[],&[],false,|_|Ok(())).unwrap();assert_eq!(hosts.networks().unwrap().preferences.terminal_font_size,14);
        let plan=hosts.preview_v2(&archive).unwrap();hosts.apply_v2(&archive,&plan.revision,&[],&[],true,|_|Ok(())).unwrap();assert_eq!(hosts.networks().unwrap().preferences.terminal_font_size,22);
        let fixture:serde_json::Value=serde_json::from_str(include_str!("../../../shared/config-transfer-v2.json")).unwrap();let a=herdr_readonly_transport::config_transfer::PortableArchive::parse(fixture["validPlaintexts"][1]["plaintext"].as_str().unwrap().as_bytes()).unwrap().into_v2();let plan=hosts.preview_v2(&a).unwrap();hosts.apply_v2(&a,&plan.revision,&[],&[a.networks[0].key.clone()],false,|_|Ok(())).unwrap();assert_eq!(hosts.networks().unwrap().profiles.len(),1);
    }
    #[test]
    fn offline_pairing_survives_enabled_and_disabled_overlay_configuration() {
        use crate::networks::Settings;
        let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();let target=target();let host=hosts.save(None,"fixture",target.clone(),None).unwrap();let mut second_target=target.clone();second_target.host="other.invalid".into();let second=hosts.save(None,"other",second_target.clone(),None).unwrap();
        let p=NetworkProfile{id:"0".repeat(32),label:"overlay".into(),provider:Provider::Tailscale,enabled:true,revision:1,settings:Settings::Tailscale{control_url:String::new(),hostname:String::new()}};
        let cat=hosts.networks().unwrap();hosts.save_network(p,&cat.revision,None,&[]).unwrap();let cat=hosts.networks().unwrap();let mut p=cat.profiles[0].clone();hosts.bind_network(&host.id,Some(p.id.clone()),&cat.revision).unwrap();let cat=hosts.networks().unwrap();hosts.bind_network(&second.id,Some(p.id.clone()),&cat.revision).unwrap();
        let record=hosts.get(&host.id).unwrap();assert!(hosts.route(&record).unwrap().is_some());
        let keys=std::sync::Arc::new(VolatileKeyStore::default());let pair=crate::create_offline_pair(keys.clone(),&target.config(),"Pocket",100).unwrap();let reference=pair.pending_reference(&target.config()).unwrap();hosts.attach_pending(&host.id,&target,reference.clone()).unwrap();
        let restored=crate::restore_offline_pair(keys.clone(),&reference,&target.config(),true,101).unwrap();assert_eq!(restored.request_json().unwrap(),pair.request_json().unwrap());
        let cat=hosts.networks().unwrap();p.enabled=false;hosts.save_network(p,&cat.revision,Some(1),&[host.id.clone(),second.id.clone()]).unwrap();let record=hosts.get(&host.id).unwrap();assert!(matches!(hosts.route(&record),Err(e) if e=="network_profile_disabled"));
        let restored=crate::restore_offline_pair(keys.clone(),&reference,&target.config(),true,101).unwrap();assert_eq!(restored.request_json().unwrap(),pair.request_json().unwrap());
        let second_pair=crate::create_offline_pair(keys,&second_target.config(),"Pocket 2",101).unwrap();hosts.attach_pending(&second.id,&second_target,second_pair.pending_reference(&second_target.config()).unwrap()).unwrap();
    }
    #[test]
    fn identity_write_requires_reviewed_profile_revision_and_host_set() {
        use crate::networks::Settings;let temp=Temp::new();let hosts=Hosts::default();hosts.init(temp.0.clone()).unwrap();
        let host=hosts.save(None,"fixture",target(),None).unwrap();let cat=hosts.networks().unwrap();
        let p=NetworkProfile{id:"0".repeat(32),label:"team".into(),provider:Provider::Easytier,enabled:true,revision:1,settings:Settings::Easytier{network_name:"team".into(),peers:vec!["tcp://example.test:1234".into()]}};
        hosts.save_network(p,&cat.revision,None,&[]).unwrap();let cat=hosts.networks().unwrap();let id=cat.profiles[0].id.clone();hosts.bind_network(&host.id,Some(id.clone()),&cat.revision).unwrap();let cat=hosts.networks().unwrap();
        assert!(crate::reviewed_identity_profile(&hosts,&id,1,&cat.revision,&[host.id.clone()]).is_ok());
        assert!(crate::reviewed_identity_profile(&hosts,&id,2,&cat.revision,&[host.id.clone()]).is_err());
        assert!(crate::reviewed_identity_profile(&hosts,&id,1,&cat.revision,&[]).is_err());
        assert!(crate::reviewed_identity_profile(&hosts,&id,1,"stale",&[host.id]).is_err());
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
    fn revoked_identity_retains_only_cleanup_authority_across_reopen_and_write_failure() {
        let temp = Temp::new();
        let hosts = Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        let target = target();
        let keys = std::sync::Arc::new(VolatileKeyStore::default());
        let pairing = Pairing::create(keys, "fixture", &target.expected_host_key, "Pocket", 100).unwrap();
        let old = PairingReference {
            handle: pairing.local_handle().into(), request_json: pairing.request_json().unwrap(),
            status: ReferenceStatus::Authorized,
        };
        let view = hosts.save(None, "Fixture", target.clone(), Some(old.clone())).unwrap();

        // Block the final rename inside our temporary fixture only.
        let catalog = temp.0.join("hosts.json");
        let backup = temp.0.join("original.json");
        fs::rename(&catalog, &backup).unwrap();
        fs::create_dir(&catalog).unwrap();
        assert!(hosts.set_status(&old.handle, ReferenceStatus::Revoked).is_err());
        assert_eq!(hosts.get(&view.id).unwrap().pairing.unwrap().status, ReferenceStatus::Revoked);
        assert!(hosts.set_status(&old.handle, ReferenceStatus::Cancelled).is_err());
        assert!(hosts.save(Some(&view.id), "Fixture", target, Some(old.clone())).is_err());
        fs::remove_dir(&catalog).unwrap();
        fs::rename(backup, catalog).unwrap();
        hosts.set_status(&old.handle, ReferenceStatus::Revoked).unwrap();
        drop(hosts);

        let reloaded = Hosts::default();
        reloaded.init(temp.0.clone()).unwrap();
        let record = reloaded.get(&view.id).unwrap();
        let public = record.view().unwrap();
        assert_eq!(public.pairing_status, Some(ReferenceStatus::Revoked));
        assert_eq!(public.device_fingerprint, view.device_fingerprint);
        assert!(!serde_json::to_string(&public).unwrap().contains(&old.handle));
        let cleanup = record.pairing.unwrap();
        assert_eq!(cleanup.handle, old.handle);
        assert_eq!(cleanup.request_json, old.request_json);
        assert!(reloaded.set_status(&old.handle, ReferenceStatus::Authorized).is_err());
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

    #[test]
    fn import_requires_review_revision_and_preserves_paired_identity() {
        let temp = Temp::new();
        let hosts = Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        let target = target();
        let keys = std::sync::Arc::new(VolatileKeyStore::default());
        let pairing =
            Pairing::create(keys, "fixture", &target.expected_host_key, "Pocket", 100).unwrap();
        let reference = PairingReference {
            handle: pairing.local_handle().to_owned(),
            request_json: pairing.request_json().unwrap(),
            status: ReferenceStatus::Authorized,
        };
        let old = hosts
            .save(None, "same", target.clone(), Some(reference.clone()))
            .unwrap();
        let mut incoming = PortableTarget::from(&target);
        incoming.host = "other.invalid".into();
        let archive = Archive {
            version: 1,
            hosts: vec![PortableHost {
                label: "same".into(),
                provider: Provider::Tailscale,
                target: incoming,
            }],
        };
        let stale = hosts.preview_import(&archive).unwrap();
        assert_eq!(stale.entries[0].conflicts.len(), 1);
        hosts.update(&old.id, Some("changed"), None).unwrap();
        let choices = [ImportChoice {
            index: 0,
            action: ImportAction::Replace,
            replace_ids: vec![old.id.clone()],
        }];
        assert!(
            hosts
                .apply_import(&archive, &stale.revision, &choices)
                .is_err()
        );
        hosts.update(&old.id, Some("same"), None).unwrap();
        assert!(
            hosts
                .apply_import(&archive, &stale.revision, &choices)
                .is_err()
        );
        let plan = hosts.preview_import(&archive).unwrap();
        let invalid = [ImportChoice {
            index: 0,
            action: ImportAction::Replace,
            replace_ids: vec![],
        }];
        let called = std::cell::Cell::new(false);
        assert!(
            hosts
                .apply_import_with(&archive, &plan.revision, &invalid, |_| {
                    called.set(true);
                    Ok(())
                })
                .is_err()
        );
        assert!(!called.get());
        assert!(
            hosts
                .apply_import_with(&archive, &plan.revision, &choices, |replaced| {
                    assert_eq!(replaced.len(), 1);
                    assert_eq!(replaced[0].id, old.id);
                    Err("fixture_cancel".into())
                })
                .is_err()
        );
        assert!(!hosts.get(&old.id).unwrap().retired);
        let result = hosts
            .apply_import(&archive, &plan.revision, &choices)
            .unwrap();
        assert_eq!(result.added.len(), 1);
        assert_ne!(result.added[0].id, old.id);
        assert_eq!(result.retired.len(), 1);
        assert_eq!(result.retired[0].id, old.id);
        let retained = hosts.get(&old.id).unwrap();
        assert!(retained.retired && !retained.enabled);
        assert_eq!(retained.pairing.unwrap().handle, reference.handle);
        assert!(hosts.get(&result.added[0].id).unwrap().pairing.is_none());
        assert!(hosts.update(&old.id, None, Some(true)).is_err());
        assert!(hosts.export_portable(&[old.id]).is_err());
    }
    #[test]
    fn import_failure_never_partially_commits_and_duplicate_labels_are_identified() {
        let temp = Temp::new();
        let hosts = Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        let target = target();
        let old = hosts.save(None, "local", target.clone(), None).unwrap();
        let before = fs::read(temp.0.join("hosts.json")).unwrap();
        let mut a = PortableTarget::from(&target);
        a.host = "one.invalid".into();
        let mut b = a.clone();
        b.host = "two.invalid".into();
        let archive = Archive {
            version: 1,
            hosts: vec![
                PortableHost {
                    label: "local".into(),
                    provider: Provider::Direct,
                    target: a,
                },
                PortableHost {
                    label: "local".into(),
                    provider: Provider::Direct,
                    target: b,
                },
            ],
        };
        let plan = hosts.preview_import(&archive).unwrap();
        assert_eq!(plan.entries[0].same_label_indices, vec![1]);
        let choices = [
            ImportChoice {
                index: 0,
                action: ImportAction::Replace,
                replace_ids: vec![old.id.clone()],
            },
            ImportChoice {
                index: 1,
                action: ImportAction::Replace,
                replace_ids: vec![old.id],
            },
        ];
        assert!(
            hosts
                .apply_import(&archive, &plan.revision, &choices)
                .is_err()
        );
        assert_eq!(fs::read(temp.0.join("hosts.json")).unwrap(), before);
        let moved = temp.0.with_extension("moved");
        fs::rename(&temp.0, &moved).unwrap();
        fs::write(&temp.0, b"not a directory").unwrap();
        let choices = [
            ImportChoice {
                index: 0,
                action: ImportAction::Add,
                replace_ids: vec![],
            },
            ImportChoice {
                index: 1,
                action: ImportAction::Keep,
                replace_ids: vec![],
            },
        ];
        assert!(
            hosts
                .apply_import(&archive, &plan.revision, &choices)
                .is_err()
        );
        assert_eq!(fs::read(moved.join("hosts.json")).unwrap(), before);
        fs::remove_file(&temp.0).unwrap();
        fs::rename(moved, &temp.0).unwrap();
    }

    #[test]
    fn legacy_v1_hosts_default_provider_and_retirement() {
        let temp = Temp::new();
        let hosts = Hosts::default();
        hosts.init(temp.0.clone()).unwrap();
        let id = hosts.save(None, "legacy", target(), None).unwrap().id;
        drop(hosts);
        let path = temp.0.join("hosts.json");
        let mut disk: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        let record = disk["hosts"][0].as_object_mut().unwrap();
        record.remove("provider");
        record.remove("retired");
        record.remove("networkProfileId");
        disk.as_object_mut().unwrap().remove("networkProfiles");
        disk.as_object_mut().unwrap().remove("preferences");
        fs::write(path, serde_json::to_vec(&disk).unwrap()).unwrap();
        let reopened = Hosts::default();
        reopened.init(temp.0.clone()).unwrap();
        let saved = reopened.get(&id).unwrap();
        assert_eq!(saved.provider, Provider::Unspecified);
        assert_eq!(saved.network_profile_id, None);
        assert!(reopened.networks().unwrap().profiles.is_empty());
        assert!(!saved.retired);
    }
}
