use super::PairingState;
use base64ct::{Base64, Encoding};
use herdr_readonly_transport::{Result, pairing::KeyStore};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tauri::{
    Manager, Runtime,
    plugin::{Builder, PluginHandle, TauriPlugin},
};

#[derive(Serialize)]
struct Args<'a> {
    handle: &'a str,
    payload: &'a str,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Created {
    handle: String,
    public_key: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Public {
    public_key: String,
}
#[derive(Deserialize)]
struct Signed {
    signature: String,
}
struct AndroidStore<R: Runtime>(PluginHandle<R>);
impl<R: Runtime> KeyStore for AndroidStore<R> {
    fn create(&self) -> Result<(String, String)> {
        let r: Created = self
            .0
            .run_mobile_plugin("create", ())
            .map_err(|_| "key_unavailable")?;
        Ok((r.handle, r.public_key))
    }
    fn public(&self, handle: &str) -> Result<String> {
        let r: Public = self
            .0
            .run_mobile_plugin(
                "publicKey",
                Args {
                    handle,
                    payload: "",
                },
            )
            .map_err(|_| "key_unavailable")?;
        Ok(r.public_key)
    }
    fn sign(&self, handle: &str, data: &[u8]) -> Result<Vec<u8>> {
        if data.len() > 65536 {
            return Err("payload_too_large");
        }
        let payload = Base64::encode_string(data);
        let r: Signed = self
            .0
            .run_mobile_plugin(
                "sign",
                Args {
                    handle,
                    payload: &payload,
                },
            )
            .map_err(|_| "key_unavailable")?;
        let sig = Base64::decode_vec(&r.signature).map_err(|_| "key_unavailable")?;
        if sig.len() != 64 {
            return Err("key_unavailable");
        }
        Ok(sig)
    }
    fn delete(&self, handle: &str) -> Result<()> {
        let _: serde_json::Value = self
            .0
            .run_mobile_plugin(
                "delete",
                Args {
                    handle,
                    payload: "",
                },
            )
            .map_err(|_| "key_unavailable")?;
        Ok(())
    }
}
pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("devicekeys")
        .setup(|app, api| {
            let handle = api.register_android_plugin("org.herdr.pocket", "DeviceKeysPlugin")?;
            app.manage(PairingState::new(Arc::new(AndroidStore(handle))));
            Ok(())
        })
        .build()
}
