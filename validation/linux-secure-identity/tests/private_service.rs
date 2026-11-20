//! Run only inside a disposable account with a private D-Bus and test keyring.
use herdr_linux_secure_identity::{Store, FLUTTER, TAURI};
use base64ct::{Base64, Encoding};
use ring::signature::{UnparsedPublicKey, ED25519};
use secret_service::{blocking::SecretService, EncryptionType};
use std::{fs, process::Command};

#[test]
fn worker_process() {
    let Some(path) = std::env::var_os("HP_SECRET_TEST_WORKER") else { return };
    let fields = fs::read_to_string(path).unwrap();
    let mut fields = fields.lines();
    let handle = fields.next().unwrap(); let expected = fields.next().unwrap();
    let store = Store::new(TAURI).unwrap();
    assert_eq!(store.public(handle).unwrap(), expected);
    let signature = store.sign(handle, b"synthetic-message").unwrap();
    let blob = Base64::decode_vec(expected.strip_prefix("ssh-ed25519 ").unwrap()).unwrap();
    UnparsedPublicKey::new(&ED25519, &blob[19..]).verify(b"synthetic-message", &signature).unwrap();
}

#[test]
fn actual_service_restarts_and_preserves_namespace_isolation() {
    let Some(dir) = std::env::var_os("HP_SECRET_TEST_DIR") else { return };
    let path = std::path::Path::new(&dir).join("public-reference");
    let a = Store::new(TAURI).unwrap(); let b = Store::new(FLUTTER).unwrap();
    let first = Store::reserve().unwrap(); let second = Store::reserve().unwrap();
    let public = a.create_reserved(&first).unwrap();
    assert_eq!(a.create_reserved(&first), Err("key_exists"));
    assert_eq!(b.public(&first), Err("key_missing"));
    let other = a.create_reserved(&second).unwrap();
    fs::write(&path, format!("{first}\n{public}\n")).unwrap();
    assert!(Command::new(std::env::current_exe().unwrap()).args(["--exact", "worker_process"])
        .env("HP_SECRET_TEST_WORKER", &path).status().unwrap().success());
    a.delete(&first).unwrap();
    assert_eq!(a.public(&first), Err("key_missing"));
    assert_eq!(a.public(&second).unwrap(), other);
    a.delete(&second).unwrap();
    let service = SecretService::connect(EncryptionType::Dh).unwrap();
    let collection = service.get_default_collection().unwrap();
    collection.lock().unwrap();
    assert!(collection.is_locked().unwrap());
    assert_eq!(a.public(&first), Err("key_locked"));
    assert_eq!(a.create_reserved(&Store::reserve().unwrap()), Err("key_locked"));
    assert_eq!(a.delete(&first), Err("key_locked"));
}
