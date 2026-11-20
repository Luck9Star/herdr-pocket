//! Device-specific Ed25519 identities in an already unlocked Secret Service.
//! Namespace attributes prevent accidental cross-client lookup, not access by
//! other processes in the same unlocked desktop session.
use std::collections::HashMap;
use base64ct::{Base64, Encoding};
use ring::{rand::{SecureRandom, SystemRandom}, signature::{Ed25519KeyPair, KeyPair}};
use secret_service::{blocking::SecretService, EncryptionType};
use zeroize::Zeroizing;

pub const FLUTTER: &str = "herdr-pocket.flutter";
pub const TAURI: &str = "herdr-pocket.tauri";
const PURPOSE: &str = "ssh-pairing-v1";
const CONTENT: &str = "application/vnd.herdr-pocket.ed25519-seed";
pub type Result<T> = std::result::Result<T, &'static str>;

pub struct Store { app: &'static str }
impl Store {
    pub fn new(app: &'static str) -> Result<Self> {
        if app != FLUTTER && app != TAURI { return Err("key_unavailable"); }
        Ok(Self { app })
    }
    fn attributes<'a>(&'a self, handle: &'a str) -> HashMap<&'a str, &'a str> {
        HashMap::from([("application", self.app), ("purpose", PURPOSE), ("handle", handle)])
    }
    fn validate(handle: &str) -> Result<()> {
        if handle.len() != 32 || !handle.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)) {
            return Err("invalid_device_key");
        }
        Ok(())
    }
    fn service() -> Result<SecretService<'static>> {
        SecretService::connect(EncryptionType::Dh).map_err(|_| "key_unavailable")
    }
    fn unlocked_default<'a>(ss: &'a SecretService<'a>) -> Result<secret_service::blocking::Collection<'a>> {
        let col = ss.get_default_collection().map_err(|_| "key_unavailable")?;
        if col.is_locked().map_err(|_| "key_unavailable")? { return Err("key_locked"); }
        Ok(col)
    }
    fn exact_attributes(&self, item: &secret_service::blocking::Item<'_>, handle: &str) -> Result<()> {
        let got = item.get_attributes().map_err(|_| "key_unavailable")?;
        let expected = self.attributes(handle);
        // GNOME Keyring adds this standard schema attribute to generic items.
        if got.keys().any(|k| !expected.contains_key(k.as_str()) && k != "xdg:schema") ||
            got.get("xdg:schema").is_some_and(|v| v != "org.freedesktop.Secret.Generic") ||
            !expected.iter().all(|(k,v)| got.get(*k).is_some_and(|x| x == *v)) {
            return Err("key_unavailable");
        }
        Ok(())
    }
    fn read(&self, handle: &str) -> Result<Zeroizing<Vec<u8>>> {
        Self::validate(handle)?;
        let ss = Self::service()?;
        let col = Self::unlocked_default(&ss)?;
        let items = col.search_items(self.attributes(handle)).map_err(|_| "key_unavailable")?;
        if items.is_empty() { return Err("key_missing"); }
        if items.len() != 1 { return Err("key_unavailable"); }
        let item = &items[0];
        self.exact_attributes(item, handle)?;
        if item.is_locked().map_err(|_| "key_unavailable")? { return Err("key_locked"); }
        let seed = Zeroizing::new(item.get_secret().map_err(|_| "key_unavailable")?);
        if seed.len() != 32 { return Err("key_unavailable"); }
        Ok(seed)
    }
    fn public_for(seed: &[u8]) -> Result<String> {
        let key = Ed25519KeyPair::from_seed_unchecked(seed).map_err(|_| "key_unavailable")?;
        let mut blob = Vec::with_capacity(51);
        blob.extend_from_slice(&11u32.to_be_bytes()); blob.extend_from_slice(b"ssh-ed25519");
        blob.extend_from_slice(&32u32.to_be_bytes()); blob.extend_from_slice(key.public_key().as_ref());
        Ok(format!("ssh-ed25519 {}", Base64::encode_string(&blob)))
    }
    /// No Secret Service access; the caller must persist this handle before create_reserved.
    pub fn reserve() -> Result<String> {
        let mut id = [0u8; 16];
        SystemRandom::new().fill(&mut id).map_err(|_| "key_unavailable")?;
        Ok(id.iter().map(|b| format!("{b:02x}")).collect())
    }
    /// This is a single write; after key_write_unknown callers must only read
    /// this same handle until the outcome is explicitly reconciled.
    pub fn create_reserved(&self, handle: &str) -> Result<String> {
        Self::validate(handle)?;
        let ss = Self::service()?; let col = Self::unlocked_default(&ss)?;
        if !col.search_items(self.attributes(handle)).map_err(|_| "key_unavailable")?.is_empty() {
            return Err("key_exists");
        }
        let mut seed = Zeroizing::new([0u8; 32]);
        SystemRandom::new().fill(&mut *seed).map_err(|_| "key_unavailable")?;
        let public = Self::public_for(&*seed)?;
        let item = col.create_item("herdr-pocket SSH pairing", self.attributes(handle), &*seed, false, CONTENT)
            .map_err(|_| "key_write_unknown")?;
        self.exact_attributes(&item, handle).map_err(|_| "key_write_unknown")?;
        let items = col.search_items(self.attributes(handle)).map_err(|_| "key_write_unknown")?;
        if items.len() != 1 { return Err("key_write_unknown"); }
        let persisted = Zeroizing::new(items[0].get_secret().map_err(|_| "key_write_unknown")?);
        if persisted.as_slice() != seed.as_slice() { return Err("key_write_unknown"); }
        Ok(public)
    }
    pub fn public(&self, handle: &str) -> Result<String> { Self::public_for(&self.read(handle)?) }
    pub fn sign(&self, handle: &str, data: &[u8]) -> Result<Vec<u8>> {
        if data.len() > 65536 { return Err("payload_too_large"); }
        let seed = self.read(handle)?;
        let key = Ed25519KeyPair::from_seed_unchecked(&seed).map_err(|_| "key_unavailable")?;
        Ok(key.sign(data).as_ref().to_vec())
    }
    pub fn delete(&self, handle: &str) -> Result<()> {
        Self::validate(handle)?;
        let ss = Self::service()?; let col = Self::unlocked_default(&ss)?;
        let items = col.search_items(self.attributes(handle)).map_err(|_| "key_unavailable")?;
        if items.is_empty() { return Ok(()); }
        if items.len() != 1 { return Err("key_unavailable"); }
        let item = &items[0]; self.exact_attributes(item, handle)?;
        if item.is_locked().map_err(|_| "key_unavailable")? { return Err("key_locked"); }
        item.delete().map_err(|_| "key_write_unknown")
    }
}

mod ffi {
    use super::{Store, FLUTTER, TAURI};
    use std::{ffi::{c_char, CStr}, panic::{catch_unwind, AssertUnwindSafe}, ptr};
    fn code(error: &str) -> i32 {
        match error { "invalid_device_key" => 1, "key_missing" => 2, "key_locked" => 3,
            "key_write_unknown" => 5, "payload_too_large" => 6, "key_exists" => 7, _ => 4 }
    }
    unsafe fn text<'a>(p: *const c_char, max: usize) -> std::result::Result<&'a str, i32> {
        if p.is_null() { return Err(1); }
        let s = unsafe { CStr::from_ptr(p) }.to_str().map_err(|_| 1)?;
        if s.len() > max { return Err(1); }
        Ok(s)
    }
    unsafe fn store(app: *const c_char) -> std::result::Result<Store, i32> {
        match unsafe { text(app, 32)? } { FLUTTER => Store::new(FLUTTER), TAURI => Store::new(TAURI), _ => return Err(1) }.map_err(code)
    }
    unsafe fn output(out: *mut c_char, value: &str, capacity: usize) -> std::result::Result<(), i32> {
        if out.is_null() || value.len() + 1 > capacity { return Err(1); }
        unsafe { ptr::copy_nonoverlapping(value.as_ptr(), out.cast::<u8>(), value.len()); *out.add(value.len()) = 0; }
        Ok(())
    }
    fn boundary(panic_code: i32, f: impl FnOnce() -> std::result::Result<(), i32>) -> i32 {
        match catch_unwind(AssertUnwindSafe(f)) { Ok(Ok(())) => 0, Ok(Err(e)) => e, Err(_) => panic_code }
    }
    #[unsafe(no_mangle)]
    pub unsafe extern "C" fn hp_identity_reserve(out: *mut c_char) -> i32 {
        boundary(4, || unsafe { output(out, &Store::reserve().map_err(code)?, 33) })
    }
    #[unsafe(no_mangle)]
    pub unsafe extern "C" fn hp_identity_create_reserved(app: *const c_char, handle: *const c_char, out: *mut c_char) -> i32 {
        boundary(5, || unsafe { if out.is_null() { return Err(1); } let s = store(app)?; let h = text(handle, 32)?; output(out, &s.create_reserved(h).map_err(code)?, 128) })
    }
    #[unsafe(no_mangle)]
    pub unsafe extern "C" fn hp_identity_public(app: *const c_char, handle: *const c_char, out: *mut c_char) -> i32 {
        boundary(4, || unsafe { let s = store(app)?; let h = text(handle, 32)?; output(out, &s.public(h).map_err(code)?, 128) })
    }
    #[unsafe(no_mangle)]
    pub unsafe extern "C" fn hp_identity_sign(app: *const c_char, handle: *const c_char, data: *const u8, len: usize, out: *mut u8) -> i32 {
        boundary(4, || unsafe {
            if out.is_null() || (data.is_null() && len != 0) { return Err(1); }
            if len > 65536 { return Err(6); }
            let s = store(app)?; let h = text(handle, 32)?;
            let bytes = if len == 0 { &[] } else { std::slice::from_raw_parts(data, len) };
            let signature = s.sign(h, bytes).map_err(code)?;
            if signature.len() != 64 { return Err(4); }
            ptr::copy_nonoverlapping(signature.as_ptr(), out, 64); Ok(())
        })
    }
    #[unsafe(no_mangle)]
    pub unsafe extern "C" fn hp_identity_delete(app: *const c_char, handle: *const c_char) -> i32 {
        boundary(5, || unsafe { store(app)?.delete(text(handle, 32)?).map_err(code) })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reserved_handles_are_distinct_and_valid() {
        let a = Store::reserve().unwrap(); let b = Store::reserve().unwrap();
        assert_ne!(a, b); assert!(Store::validate(&a).is_ok());
        for value in ["", "../bad", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "a"] {
            assert_eq!(Store::validate(value), Err("invalid_device_key"));
        }
        assert!(Store::new("other").is_err());
    }
    #[test]
    fn public_is_canonical_openssh_for_ed25519_seed() {
        let seed = [7u8; 32];
        let key = Ed25519KeyPair::from_seed_unchecked(&seed).unwrap();
        let text = Store::public_for(&seed).unwrap();
        let blob = Base64::decode_vec(text.strip_prefix("ssh-ed25519 ").unwrap()).unwrap();
        assert_eq!(&blob[..15], b"\0\0\0\x0bssh-ed25519");
        assert_eq!(&blob[15..19], &32u32.to_be_bytes());
        assert_eq!(&blob[19..], key.public_key().as_ref());
    }
    #[test]
    fn unavailable_service_is_not_missing_or_success() {
        if std::env::var_os("HP_TEST_NO_SERVICE").is_none() { return; }
        let store = Store::new(TAURI).unwrap(); let handle = "0".repeat(32);
        assert_eq!(store.public(&handle), Err("key_unavailable"));
        assert_eq!(store.delete(&handle), Err("key_unavailable"));
        assert_eq!(store.create_reserved(&handle), Err("key_unavailable"));
    }
}
