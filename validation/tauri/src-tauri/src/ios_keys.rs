use super::PairingState;
use base64ct::{Base64, Encoding};
use herdr_readonly_transport::{Result, pairing::KeyStore};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tauri::{
    Manager, Runtime,
    plugin::{Builder, PluginHandle, TauriPlugin},
};

tauri::ios_plugin_binding!(init_plugin_herdr_pocket_ios);

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
#[derive(Deserialize)]
struct RootPath {
    path: String,
}
#[derive(Deserialize)]
struct Scan {
    text: String,
}
#[derive(Deserialize)]
struct DocumentOpen { data: Option<String> }
#[derive(Deserialize)]
struct DocumentSave { saved: bool }

pub async fn open_document<R: Runtime>(app: &tauri::AppHandle<R>) -> std::result::Result<Option<Vec<u8>>, String> {
    let plugin=app.try_state::<IOSPlugin<R>>().ok_or("document_unavailable")?;
    let reply:DocumentOpen=plugin.0.run_mobile_plugin_async("openDocument", serde_json::json!({})).await.map_err(|_|"document_unavailable")?;
    let Some(data)=reply.data else {return Ok(None)};
    if data.len()>87448 {return Err("document_invalid".into());}
    let bytes=Base64::decode_vec(&data).map_err(|_|"document_invalid")?;
    if bytes.is_empty() || bytes.len()>65586 {return Err("document_invalid".into());}
    Ok(Some(bytes))
}
pub async fn save_document<R: Runtime>(app: &tauri::AppHandle<R>, bytes: &[u8]) -> std::result::Result<bool, String> {
    if bytes.is_empty() || bytes.len()>65586 {return Err("document_invalid".into());}
    let plugin=app.try_state::<IOSPlugin<R>>().ok_or("document_unavailable")?;
    let reply:DocumentSave=plugin.0.run_mobile_plugin_async("saveDocument",serde_json::json!({"data":Base64::encode_string(bytes)})).await.map_err(|_|"document_unavailable")?;
    Ok(reply.saved)
}

struct IOSStore<R: Runtime>(PluginHandle<R>);
struct IOSPlugin<R: Runtime>(PluginHandle<R>);
impl<R: Runtime> KeyStore for IOSStore<R> {
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
        let signature = Base64::decode_vec(&r.signature).map_err(|_| "key_unavailable")?;
        if signature.len() != 64 {
            return Err("key_unavailable");
        }
        Ok(signature)
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
            let handle = api.register_ios_plugin(init_plugin_herdr_pocket_ios)?;
            app.manage(IOSPlugin(handle.clone()));
            app.manage(PairingState::new(Arc::new(IOSStore(handle))));
            Ok(())
        })
        .build()
}

pub fn private_config_root<R: Runtime>(app: &tauri::AppHandle<R>) -> Result<std::path::PathBuf> {
    let plugin = app
        .try_state::<IOSPlugin<R>>()
        .ok_or("host_storage_unavailable")?;
    let root: RootPath = plugin
        .0
        .run_mobile_plugin("privateConfigRoot", ())
        .map_err(|_| "host_storage_unavailable")?;
    let path = std::path::PathBuf::from(root.path);
    if !path.is_absolute() {
        return Err("host_storage_unavailable");
    }
    Ok(path)
}

pub async fn scan<R: Runtime>(app: &tauri::AppHandle<R>) -> std::result::Result<String, String> {
    let plugin = app
        .try_state::<IOSPlugin<R>>()
        .ok_or("camera_unavailable")?;
    let reply: Scan = plugin
        .0
        .run_mobile_plugin_async("scan", serde_json::json!({}))
        .await
        .map_err(|_| "scan_cancelled_or_unavailable")?;
    if reply.text.is_empty() || reply.text.len() > 2048 {
        return Err("invalid_public_response".into());
    }
    Ok(reply.text)
}
