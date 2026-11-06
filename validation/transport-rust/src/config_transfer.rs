//! Versioned, authenticated portable host metadata. No credentials or runtime state.
use crate::RemoteConfig;
use ring::{
    aead, pbkdf2,
    rand::{SecureRandom, SystemRandom},
};
use serde::{Deserialize, Serialize};
use std::num::NonZeroU32;
use zeroize::Zeroizing;

const MAGIC: &[u8; 4] = b"HPKT";
const HEADER: usize = 34;
const MAX_PLAINTEXT: usize = 65536;
const ITERATIONS: u32 = 600_000;

pub fn revision_digest(bytes: &[u8]) -> String {
    ring::digest::digest(&ring::digest::SHA256, bytes)
        .as_ref()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum Provider {
    #[default]
    Unspecified,
    Direct,
    Tailscale,
    Easytier,
    Zerotier,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PortableTarget {
    pub host: String,
    pub port: u16,
    pub username: String,
    pub expected_host_key: String,
    pub socket_path: String,
    pub herdr_path: String,
    pub session: String,
}
impl PortableTarget {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.username.starts_with('-') {
            return Err("transfer_invalid_schema");
        }
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
        .validate_pair_target()
        .map_err(|_| "transfer_invalid_schema")
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PortableHost {
    pub label: String,
    pub provider: Provider,
    pub target: PortableTarget,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Archive {
    pub version: u8,
    pub hosts: Vec<PortableHost>,
}
impl Archive {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.version != 1 || self.hosts.is_empty() || self.hosts.len() > 16 {
            return Err("transfer_invalid_schema");
        }
        for h in &self.hosts {
            if h.label.trim().is_empty()
                || h.label.len() > 96
                || h.label.chars().any(char::is_control)
            {
                return Err("transfer_invalid_schema");
            }
            h.target.validate()?;
        }
        Ok(())
    }
    pub fn parse(raw: &[u8]) -> Result<Self, &'static str> {
        if raw.is_empty() || raw.len() > MAX_PLAINTEXT || std::str::from_utf8(raw).is_err() {
            return Err("transfer_invalid_schema");
        }
        let result: Self = serde_json::from_slice(raw).map_err(|_| "transfer_invalid_schema")?;
        result.validate()?;
        Ok(result)
    }
}
fn password_ok(password: &str) -> bool {
    !password.is_empty() && password.len() <= 1024
}
fn derive(password: &str, salt: &[u8]) -> Zeroizing<[u8; 32]> {
    let mut key = Zeroizing::new([0u8; 32]);
    pbkdf2::derive(
        pbkdf2::PBKDF2_HMAC_SHA256,
        NonZeroU32::new(ITERATIONS).unwrap(),
        salt,
        password.as_bytes(),
        key.as_mut(),
    );
    key
}
fn encrypt_with_material(
    password: &str,
    plaintext: &[u8],
    salt: [u8; 16],
    nonce: [u8; 12],
) -> Result<Vec<u8>, &'static str> {
    if !password_ok(password) {
        return Err("transfer_invalid_password");
    }
    if plaintext.is_empty()
        || plaintext.len() > MAX_PLAINTEXT
        || std::str::from_utf8(plaintext).is_err()
    {
        return Err("transfer_invalid_plaintext");
    }
    let mut header = Vec::with_capacity(HEADER);
    header.extend_from_slice(MAGIC);
    header.extend_from_slice(&[1, 1]);
    header.extend_from_slice(&salt);
    header.extend_from_slice(&nonce);
    let derived = derive(password, &salt);
    let key = aead::LessSafeKey::new(
        aead::UnboundKey::new(&aead::AES_256_GCM, derived.as_ref())
            .map_err(|_| "transfer_crypto_failed")?,
    );
    let mut data = Zeroizing::new(plaintext.to_vec());
    key.seal_in_place_append_tag(
        aead::Nonce::assume_unique_for_key(nonce),
        aead::Aad::from(&header),
        &mut *data,
    )
    .map_err(|_| "transfer_crypto_failed")?;
    header.extend_from_slice(&data);
    Ok(header)
}
/// Fresh OS-generated salt and nonce per export. Input is validated as UTF-8 and bounded.
pub fn encrypt(password: &str, plaintext: &[u8]) -> Result<Vec<u8>, &'static str> {
    if !password_ok(password) || password.chars().count() < 12 {
        return Err("transfer_invalid_password");
    }
    let mut salt = [0; 16];
    let mut nonce = [0; 12];
    let rng = SystemRandom::new();
    rng.fill(&mut salt).map_err(|_| "transfer_crypto_failed")?;
    rng.fill(&mut nonce).map_err(|_| "transfer_crypto_failed")?;
    encrypt_with_material(password, plaintext, salt, nonce)
}
/// Rejects unbounded inputs before deriving the fixed-cost key; authentication precedes parsing.
pub fn decrypt(password: &str, archive: &[u8]) -> Result<Zeroizing<Vec<u8>>, &'static str> {
    if !password_ok(password) {
        return Err("transfer_invalid_password");
    }
    if archive.len() < HEADER + 16 + 1
        || archive.len() > HEADER + 16 + MAX_PLAINTEXT
        || &archive[..4] != MAGIC
    {
        return Err("transfer_invalid_format");
    }
    if archive[4] != 1 || archive[5] != 1 {
        return Err("transfer_unsupported_version");
    }
    let derived = derive(password, &archive[6..22]);
    let key = aead::LessSafeKey::new(
        aead::UnboundKey::new(&aead::AES_256_GCM, derived.as_ref())
            .map_err(|_| "transfer_crypto_failed")?,
    );
    let nonce: [u8; 12] = archive[22..34].try_into().unwrap();
    let mut data = Zeroizing::new(archive[HEADER..].to_vec());
    let len = key
        .open_in_place(
            aead::Nonce::assume_unique_for_key(nonce),
            aead::Aad::from(&archive[..HEADER]),
            &mut data,
        )
        .map_err(|_| "transfer_auth_failed")?
        .len();
    data.truncate(len);
    if data.is_empty() || std::str::from_utf8(&data).is_err() {
        return Err("transfer_invalid_plaintext");
    }
    Ok(data)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn authenticated_envelope_bounds_and_passwords() {
        let text = b"portable metadata";
        let password = "12字unicode-pass";
        let first = encrypt(password, text).unwrap();
        let second = encrypt(password, text).unwrap();
        assert_ne!(first, second);
        assert_eq!(&*decrypt(password, &first).unwrap(), text);
        assert!(decrypt("wrong", &first).is_err());
        for offset in [6, 22, 34, first.len() - 1] {
            let mut bad = first.clone();
            bad[offset] ^= 1;
            assert!(decrypt(password, &bad).is_err());
        }
        assert!(decrypt(password, &first[..first.len() - 1]).is_err());
        let mut bad = first.clone();
        bad[4] = 2;
        assert_eq!(
            decrypt(password, &bad).unwrap_err(),
            "transfer_unsupported_version"
        );
        assert!(encrypt("12345678901", text).is_err());
        assert!(encrypt(password, &[]).is_err());
        assert!(decrypt(password, &vec![0; HEADER + 16 + MAX_PLAINTEXT + 1]).is_err());
    }
    #[test]
    fn schema_rejects_unknown_and_secret_fields() {
        for input in [
            br#"{"version":1,"hosts":[]}"#.as_slice(),
            br#"{"version":1,"hosts":[],"password":"secret"}"#.as_slice(),
            br#"{"version":1,"hosts":[],"version":1}"#.as_slice(),
        ] {
            assert!(Archive::parse(input).is_err());
        }
    }
    #[test]
    fn independent_golden_fixture_and_legacy_short_password_import() {
        let fixture: serde_json::Value =
            serde_json::from_str(include_str!("../../shared/config-transfer-v1.json")).unwrap();
        fn hex(s: &str) -> Vec<u8> {
            (0..s.len())
                .step_by(2)
                .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
                .collect()
        }
        let password = fixture["password"].as_str().unwrap();
        let plaintext = fixture["plaintext"].as_str().unwrap().as_bytes();
        let salt: [u8; 16] = hex(fixture["saltHex"].as_str().unwrap())
            .try_into()
            .unwrap();
        let nonce: [u8; 12] = hex(fixture["nonceHex"].as_str().unwrap())
            .try_into()
            .unwrap();
        let expected = hex(fixture["archiveHex"].as_str().unwrap());
        assert_eq!(
            encrypt_with_material(password, plaintext, salt, nonce).unwrap(),
            expected
        );
        let decoded = decrypt(password, &expected).unwrap();
        assert_eq!(&*decoded, plaintext);
        let parsed = Archive::parse(&decoded).unwrap();
        assert_eq!(parsed.hosts[0].provider, Provider::Easytier);
        let mut forged: serde_json::Value = serde_json::from_slice(&decoded).unwrap();
        forged["hosts"][0]["target"]["privateKeyPem"] = "secret".into();
        assert!(Archive::parse(&serde_json::to_vec(&forged).unwrap()).is_err());
        forged["hosts"][0]["target"]
            .as_object_mut()
            .unwrap()
            .remove("privateKeyPem");
        forged["hosts"][0]["id"] = "external-id".into();
        assert!(Archive::parse(&serde_json::to_vec(&forged).unwrap()).is_err());
        let legacy = encrypt_with_material("short", plaintext, salt, nonce).unwrap();
        assert_eq!(&*decrypt("short", &legacy).unwrap(), plaintext);
    }
}
